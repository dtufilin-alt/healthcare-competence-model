import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import time
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from methodology import CONTEXTS, CRITERIA, items, validate_model, metric, solve_bwm, aggregate_weights

ROOT = Path(__file__).resolve().parent


def encode(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def digest(x):
    return hashlib.sha256(x.encode()).hexdigest()


def create_app(config=None):
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    app.config.update(DATA_DIR=str(ROOT / '.data'), MODEL=str(ROOT.parent / 'model-content.json'),
                      MAX_CONTENT_LENGTH=1024 * 1024, TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    if config:
        app.config.update(config)
    data_dir = Path(app.config['DATA_DIR'])
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = data_dir / 'admin-access.txt'
    if not app.config.get('ADMIN_KEY'):
        if not key_path.exists():
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(secrets.token_urlsafe(32) + '\n')
        app.config['ADMIN_KEY'] = key_path.read_text().strip()
    db_path = data_dir / 'review.sqlite3'
    if not db_path.exists():
        fd = os.open(db_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(db_path, timeout=15)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    def one(sql, args=()):
        return db().execute(sql, args).fetchone()

    def rows(sql, args=()):
        return db().execute(sql, args).fetchall()

    def insert(sql, args=()):
        return db().execute(sql, args).lastrowid

    @app.teardown_appcontext
    def close_db(exc):
        if 'db' in g:
            g.db.close()

    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS studies(id INTEGER PRIMARY KEY, demo INTEGER NOT NULL, phase TEXT NOT NULL DEFAULT 'content');
        CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, study INTEGER REFERENCES studies(id), payload TEXT NOT NULL, hash TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS rounds(id INTEGER PRIMARY KEY, study INTEGER REFERENCES studies(id), number INTEGER NOT NULL, version INTEGER REFERENCES versions(id), targets TEXT NOT NULL, status TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '{}', rationale TEXT NOT NULL DEFAULT '', UNIQUE(study,number));
        CREATE TABLE IF NOT EXISTS experts(id INTEGER PRIMARY KEY, study INTEGER REFERENCES studies(id), email TEXT NOT NULL, name TEXT NOT NULL, profile TEXT NOT NULL DEFAULT '{}', context TEXT NOT NULL DEFAULT '', UNIQUE(study,email));
        CREATE TABLE IF NOT EXISTS invitations(id INTEGER PRIMARY KEY, expert INTEGER REFERENCES experts(id), hash TEXT UNIQUE NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, role TEXT NOT NULL, expert INTEGER REFERENCES experts(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS answers(expert INTEGER REFERENCES experts(id), round INTEGER REFERENCES rounds(id), item TEXT NOT NULL, data TEXT NOT NULL, revision INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(expert,round,item));
        CREATE TABLE IF NOT EXISTS submissions(expert INTEGER REFERENCES experts(id), round INTEGER REFERENCES rounds(id), created REAL NOT NULL, PRIMARY KEY(expert,round));
        CREATE TABLE IF NOT EXISTS priorities(expert INTEGER REFERENCES experts(id), version INTEGER REFERENCES versions(id), data TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', submitted INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL, PRIMARY KEY(expert,version));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, action TEXT NOT NULL, details TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS assignments(expert INTEGER PRIMARY KEY REFERENCES experts(id), blocks TEXT NOT NULL, excluded TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
        ''')
        if not one('SELECT id FROM studies WHERE demo=0'):
            model = validate_model(json.loads(Path(app.config['MODEL']).read_text()))
            sid = insert('INSERT INTO studies(demo) VALUES(0)')
            vid = insert('INSERT INTO versions(study,payload,hash,created) VALUES(?,?,?,?)', (sid, encode(model), digest(encode(model)), time.time()))
            insert('INSERT INTO rounds(study,number,version,targets,status) VALUES(?,1,?,?,?)', (sid, vid, encode(list(items(model))), 'open'))
        db().commit()

    def fail(message, status=400):
        raise ReviewError(message, status)

    class ReviewError(Exception):
        def __init__(self, message, status):
            self.message, self.status = message, status

    @app.errorhandler(ReviewError)
    def review_error(e):
        return jsonify(error=e.message), e.status

    @app.errorhandler(ValueError)
    def bad_value(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify(error='Запрос отклонён: ' + e.name), e.code

    @app.before_request
    def origin():
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                fail('Запрос с другого адреса отклонён.', 403)
            if not request.is_json:
                fail('Ожидается JSON.', 415)

    @app.after_request
    def security(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            fail('Ожидается объект с полями.')
        return value

    def auth(role):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                s = one('SELECT * FROM sessions WHERE hash=? AND role=? AND expires>?',
                        (digest(request.cookies.get(role + '_session', '')), role, time.time()))
                if not s:
                    fail('Войдите заново по персональной ссылке.' if role == 'expert' else 'Нужен вход организатора.', 401)
                if request.method != 'GET' and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), s['csrf']):
                    fail('Обновите страницу и повторите действие.', 403)
                g.session = s
                if role == 'expert':
                    g.expert = one('SELECT * FROM experts WHERE id=?', (s['expert'],))
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    def login(role, expert=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        insert('INSERT INTO sessions VALUES(?,?,?,?,?)', (digest(token), role, expert, csrf, time.time() + 7 * 86400))
        db().commit()
        response = jsonify(ok=True, csrf=csrf)
        response.set_cookie(role + '_session', token, max_age=7 * 86400, httponly=True, samesite='Strict', secure=request.is_secure)
        return response

    attempts = {}

    def throttle():
        now = time.time()
        key = request.remote_addr
        attempts[key] = [t for t in attempts.get(key, []) if now - t < 60]
        if len(attempts[key]) >= 20:
            fail('Слишком много попыток. Подождите минуту.', 429)
        attempts[key].append(now)

    def log(action, detail):
        insert('INSERT INTO audit(action,details,created) VALUES(?,?,?)', (action, encode(detail), time.time()))

    def real_study():
        return one('SELECT * FROM studies WHERE demo=0')

    def current(sid):
        r = one('SELECT * FROM rounds WHERE study=? ORDER BY number DESC LIMIT 1', (sid,))
        v = one('SELECT * FROM versions WHERE id=?', (r['version'],))
        return r, json.loads(v['payload'])

    def assigned_blocks(eid):
        a = one('SELECT blocks FROM assignments WHERE expert=?', (eid,))
        return json.loads(a['blocks']) if a else []

    def choose_blocks(e, candidates, count, keep=()):
        coverage = {b: 0 for b in candidates}
        for row in rows('SELECT a.blocks FROM assignments a JOIN experts e ON e.id=a.expert WHERE e.study=? AND e.context=? AND e.id!=?', (e['study'], e['context'], e['id'])):
            for b in json.loads(row['blocks']):
                if b in coverage:
                    coverage[b] += 1
        pool = [b for b in candidates if b not in keep]
        secrets.SystemRandom().shuffle(pool)
        pool.sort(key=lambda b: coverage[b])
        return sorted(list(keep) + pool[:count])

    def round_keys(r, eid=None):
        targets = json.loads(r['targets'])
        if eid is not None:
            blocks = assigned_blocks(eid)
            targets = [k for k in targets if int(k.split(':')[0][1:]) in blocks]
        return targets + ['block:' + str(n) for n in sorted({int(k.split(':')[0][1:]) for k in targets})]

    def content_finished(e, r):
        if submitted(e['id'], r['id']):
            return True
        if r['number'] == 2 and not round_keys(r, e['id']):
            prev = one('SELECT id FROM rounds WHERE study=? AND number=1', (e['study'],))
            return submitted(e['id'], prev['id'])
        return False

    def answers_for(eid, rid):
        return {a['item']: {'data': json.loads(a['data']), 'revision': a['revision']} for a in rows('SELECT * FROM answers WHERE expert=? AND round=?', (eid, rid))}

    def submitted(eid, rid):
        return bool(one('SELECT 1 FROM submissions WHERE expert=? AND round=?', (eid, rid)))

    def profile_ready(e):
        return bool(json.loads(e['profile']).get('consent')) and e['context'] in CONTEXTS

    def require_round(e, r, d=None):
        study = one('SELECT * FROM studies WHERE id=?', (e['study'],))
        if study['phase'] not in ('content', 'round2') or r['status'] != 'open':
            fail('Раунд закрыт. Обновите страницу.', 409)
        if d is not None and d.get('round') != r['id']:
            fail('Версия раунда изменилась. Обновите страницу.', 409)
        if submitted(e['id'], r['id']):
            fail('Ответы уже отправлены и защищены от изменений.', 409)
        if not profile_ready(e):
            fail('Сначала заполните профиль эксперта.')
        if r['number'] == 2:
            prev = one('SELECT id FROM rounds WHERE study=? AND number=1', (e['study'],))
            if not submitted(e['id'], prev['id']):
                fail('Повторный раунд доступен участникам, завершившим первый раунд.', 403)

    def valid_rating(v):
        return v == 'na' or type(v) is int and 1 <= v <= 4

    def validate_answer(key, value, model):
        if not isinstance(value, dict):
            fail('Некорректный ответ.')
        if key.startswith('block:'):
            fields = ('completeness',)
            if set(value) - {'completeness', 'missing', 'duplicates'}:
                fail('Неизвестные поля ответа.')
            for f in ('missing', 'duplicates'):
                if not isinstance(value.get(f, ''), str) or len(value.get(f, '')) > 5000:
                    fail('Комментарий: не более 5000 символов.')
        else:
            fields = CRITERIA
            if set(value) - {*CRITERIA, 'comments'}:
                fail('Неизвестные поля ответа.')
            comments = value.get('comments', [])
            if not isinstance(comments, list) or len(comments) > 100:
                fail('Некорректные комментарии.')
            c = items(model)[key]
            targets = ['general'] + [f'{kind}:{i}' for kind in ('knows', 'skills') for i in range(len(c[kind]))]
            for comment in comments:
                if not isinstance(comment, dict) or comment.get('target') not in targets or comment.get('kind') not in ('clarify', 'error', 'duplicate', 'level', 'rewrite') or not isinstance(comment.get('text'), str) or not 1 <= len(comment['text'].strip()) <= 5000:
                    fail('Проверьте пункт и текст комментария.')
        if any(f in value and not valid_rating(value[f]) for f in fields):
            fail('Оценка должна быть от 1 до 4 или «Недостаточно опыта».')

    def complete(key, data):
        return all(valid_rating(data.get(f)) for f in (('completeness',) if key.startswith('block:') else CRITERIA))

    def stats(r, model, context=None):
        es = rows('SELECT e.* FROM experts e JOIN submissions s ON s.expert=e.id WHERE s.round=?', (r['id'],))
        if context:
            es = [e for e in es if e['context'] == context]
        all_answers = {e['id']: answers_for(e['id'], r['id']) for e in es}
        output = {}
        for key in round_keys(r):
            fields = ('completeness',) if key.startswith('block:') else CRITERIA
            assigned = [e for e in es if key in round_keys(r, e['id'])]
            output[key] = {f: dict(metric([all_answers[e['id']].get(key, {}).get('data', {}).get(f) for e in assigned]), assigned_submitted=len(assigned)) for f in fields}
        return {'submitted': len(es), 'items': output}

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.post('/api/admin/login')
    def admin_login():
        throttle()
        key = body().get('key', '')
        if not isinstance(key, str) or not hmac.compare_digest(key, app.config['ADMIN_KEY']):
            fail('Ключ не подошёл.', 401)
        return login('admin')

    @app.post('/api/invite')
    def exchange_invite():
        throttle()
        token = body().get('token', '')
        if not isinstance(token, str):
            fail('Некорректная ссылка.')
        invite = one('SELECT * FROM invitations WHERE hash=? AND revoked=0 AND expires>?', (digest(token), time.time()))
        if not invite:
            fail('Ссылка недействительна или истекла. Обратитесь к организатору.', 401)
        return login('expert', invite['expert'])

    @app.post('/api/demo')
    def demo():
        throttle()
        _, model = current(real_study()['id'])
        sid = insert('INSERT INTO studies(demo) VALUES(1)')
        vid = insert('INSERT INTO versions(study,payload,hash,created) VALUES(?,?,?,?)', (sid, encode(model), digest(encode(model)), time.time()))
        insert('INSERT INTO rounds(study,number,version,targets,status) VALUES(?,1,?,?,?)', (sid, vid, encode(list(items(model))), 'open'))
        eid = insert('INSERT INTO experts(study,email,name) VALUES(?,?,?)', (sid, 'demo@example.invalid', 'Демо-эксперт'))
        return login('expert', eid)

    @app.get('/api/state')
    @auth('expert')
    def state():
        e = g.expert
        study = dict(one('SELECT * FROM studies WHERE id=?', (e['study'],)))
        r, model = current(e['study'])
        p = one('SELECT * FROM priorities WHERE expert=? AND version=?', (e['id'], r['version']))
        result = {'csrf': g.session['csrf'], 'study': study, 'expert': dict(e), 'profile': json.loads(e['profile']),
                  'contexts': CONTEXTS, 'model': model, 'round': dict(r), 'targets': [k for k in round_keys(r, e['id']) if not k.startswith('block:')],
                  'assigned_blocks': assigned_blocks(e['id']), 'content_finished': content_finished(e, r),
                  'answers': answers_for(e['id'], r['id']), 'submitted': submitted(e['id'], r['id']),
                  'priority': dict(p) if p else None, 'eligible': True}
        if p:
            result['priority'].update(data=json.loads(p['data']), result=json.loads(p['result']))
        result['round'].pop('feedback')
        if r['number'] == 2:
            prev = one('SELECT * FROM rounds WHERE study=? AND number=1', (e['study'],))
            result['previous_model'] = json.loads(one('SELECT payload FROM versions WHERE id=?', (prev['version'],))['payload'])
            result['previous_answers'] = answers_for(e['id'], prev['id'])
            feedback = json.loads(r['feedback']).get(e['context'], {})
            # Privacy threshold applies per assigned item, not to the whole context panel.
            feedback = dict(feedback)
            feedback['items'] = {k: v for k, v in feedback.get('items', {}).items() if max((m.get('assigned_submitted', 0) for m in v.values()), default=0) >= 3}
            result['feedback'] = feedback if feedback.get('items') else {'hidden': True}
            result['eligible'] = submitted(e['id'], prev['id'])
        return jsonify(result)

    @app.post('/api/profile')
    @auth('expert')
    def profile():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        required = ('name', 'organization', 'position', 'domains', 'levels', 'involvement')
        if any(not isinstance(d.get(k), str) or not 1 <= len(d[k].strip()) <= 2000 for k in required):
            fail('Заполните все поля профиля.')
        if d.get('context') not in CONTEXTS or type(d.get('years')) is not int or not 0 <= d['years'] <= 80 or d.get('consent') is not True:
            fail('Укажите контекст, стаж и подтвердите участие.')
        eligible = d.get('eligible_blocks')
        if not isinstance(eligible, list) or any(type(b) is not int or b not in range(1, 9) for b in eligible) or len(set(eligible)) < 2:
            fail('Отметьте минимум два блока, в которых у вас достаточно опыта.')
        existing = assigned_blocks(g.expert['id'])
        if existing and (d['context'] != g.expert['context'] or not set(existing).issubset(eligible)):
            fail('Контекст зафиксирован после начала оценки. Обратитесь к организатору.', 409)
        db().execute('UPDATE experts SET name=?,context=?,profile=? WHERE id=?', (d['name'].strip(), d['context'], encode({k: d[k] for k in (*required, 'context', 'years', 'consent', 'eligible_blocks')}), g.expert['id']))
        if not existing:
            e = dict(g.expert, context=d['context'])
            chosen = choose_blocks(e, sorted(set(eligible)), 2)
            insert('INSERT INTO assignments(expert,blocks,created) VALUES(?,?,?)', (e['id'], encode(chosen), time.time()))
            log('blocks_assigned', {'expert': e['id'], 'blocks': chosen, 'context': e['context']})
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/replace-block')
    @auth('expert')
    def replace_block():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        r, _ = current(g.expert['study'])
        require_round(g.expert, r, d)
        if r['number'] != 1:
            fail('Во втором раунде состав блоков сохраняется.', 409)
        a = one('SELECT * FROM assignments WHERE expert=?', (g.expert['id'],))
        blocks, excluded = json.loads(a['blocks']), json.loads(a['excluded'])
        b = d.get('block')
        reason = d.get('reason', '')
        if b not in blocks or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
            fail('Выберите назначенный блок и укажите причину замены.')
        excluded = sorted(set(excluded + [b]))
        candidates = [n for n in json.loads(g.expert['profile'])['eligible_blocks'] if n not in excluded and n not in blocks]
        if not candidates:
            fail('Нет других подходящих блоков. Добавьте области опыта в профиле или используйте ответ «Недостаточно опыта».')
        chosen = choose_blocks(g.expert, candidates, 1, [n for n in blocks if n != b])
        db().execute('UPDATE assignments SET blocks=?,excluded=? WHERE expert=?', (encode(chosen), encode(excluded), g.expert['id']))
        log('block_replaced', {'expert': g.expert['id'], 'removed': b, 'blocks': chosen, 'reason': reason})
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/answer')
    @auth('expert')
    def answer():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        r, model = current(g.expert['study'])
        require_round(g.expert, r, d)
        key = d.get('item')
        if key not in round_keys(r, g.expert['id']):
            fail('Пункт отсутствует в этом раунде.')
        value = d.get('data')
        validate_answer(key, value, model)
        old = one('SELECT revision FROM answers WHERE expert=? AND round=? AND item=?', (g.expert['id'], r['id'], key))
        revision = old['revision'] if old else 0
        if d.get('revision') != revision:
            fail('Ответ изменён в другом окне. Обновите страницу, чтобы не затереть его.', 409)
        db().execute('INSERT INTO answers VALUES(?,?,?,?,?,?) ON CONFLICT(expert,round,item) DO UPDATE SET data=excluded.data,revision=excluded.revision,updated=excluded.updated',
                     (g.expert['id'], r['id'], key, encode(value), revision + 1, time.time()))
        db().commit()
        return jsonify(ok=True, revision=revision + 1)

    @app.post('/api/submit')
    @auth('expert')
    def submit():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        r, _ = current(g.expert['study'])
        require_round(g.expert, r, d)
        saved = answers_for(g.expert['id'], r['id'])
        keys = round_keys(r, g.expert['id'])
        if not keys:
            fail('Для вас в этом раунде нет назначенных карточек.')
        missing = [key for key in keys if not complete(key, saved.get(key, {}).get('data', {}))]
        if missing:
            return jsonify(error='Остались незаполненные оценки.', missing=missing), 400
        insert('INSERT INTO submissions VALUES(?,?,?)', (g.expert['id'], r['id'], time.time()))
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/priorities')
    @auth('expert')
    def priorities():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        r, model = current(g.expert['study'])
        study = one('SELECT * FROM studies WHERE id=?', (g.expert['study'],))
        if study['phase'] != 'weights' or d.get('version') != r['version'] or not content_finished(g.expert, r):
            fail('Этап приоритетов ещё не доступен для вашего участия.', 409)
        old = one('SELECT * FROM priorities WHERE expert=? AND version=?', (g.expert['id'], r['version']))
        revision = old['revision'] if old else 0
        if old and old['submitted'] or d.get('revision') != revision:
            fail('Ответ отправлен или изменён в другом окне. Обновите страницу.', 409)
        value = d.get('data')
        if not isinstance(value, dict) or not isinstance(value.get('comparisons', {}), dict):
            fail('Некорректные сравнения.')
        done = d.get('submit') is True
        result = solve_bwm(model['blocks'], value) if done or d.get('preview') else {}
        if len(encode(value)) > 10000:
            fail('Слишком большой ответ.')
        db().execute('INSERT INTO priorities VALUES(?,?,?,?,?,?) ON CONFLICT(expert,version) DO UPDATE SET data=excluded.data,result=excluded.result,submitted=excluded.submitted,revision=excluded.revision',
                     (g.expert['id'], r['version'], encode(value), encode(result), int(done), revision + 1))
        db().commit()
        return jsonify(ok=True, revision=revision + 1, result=result)

    @app.get('/api/admin/state')
    @auth('admin')
    def admin_state():
        study = real_study()
        r, model = current(study['id'])
        es = []
        for e in rows('SELECT * FROM experts WHERE study=? ORDER BY id', (study['id'],)):
            a = answers_for(e['id'], r['id'])
            keys = round_keys(r, e['id'])
            es.append(dict(dict(e), profile=json.loads(e['profile']), blocks=assigned_blocks(e['id']), completed=sum(complete(k, v['data']) for k, v in a.items() if k in keys), total=len(keys), submitted=submitted(e['id'], r['id'])))
        coverage = {context: [] for context in CONTEXTS}
        for context in CONTEXTS:
            for b in model['blocks']:
                key = 'block:' + str(b['number'])
                assigned = [e for e in es if e['context'] == context and key in round_keys(r, e['id'])]
                started = sum(any(k == key or k.startswith(f'b{b["number"]}:') for k in answers_for(e['id'], r['id'])) for e in assigned)
                coverage[context].append({'block': b['number'], 'title': b['title'], 'assigned': len(assigned), 'started': started, 'submitted': sum(e['submitted'] for e in assigned)})
        return jsonify(csrf=g.session['csrf'], study=dict(study), round=dict(r), model=model, contexts=CONTEXTS, experts=es,
                       coverage=coverage,
                       rounds=[dict(x) for x in rows('SELECT id,number,version,status FROM rounds WHERE study=?', (study['id'],))])

    @app.post('/api/admin/invitations')
    @auth('admin')
    def invitations():
        import re
        d = body()
        study = real_study()
        email, name = d.get('email', ''), d.get('name', '')
        if not isinstance(email, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
            fail('Укажите имя и корректный email.')
        email = email.strip().lower()
        e = one('SELECT * FROM experts WHERE study=? AND email=?', (study['id'], email))
        if e:
            eid = e['id']
            db().execute('UPDATE invitations SET revoked=1 WHERE expert=?', (eid,))
            db().execute('DELETE FROM sessions WHERE expert=?', (eid,))
        else:
            if study['phase'] != 'content':
                fail('Новых участников добавляют в первом раунде. Сейчас можно только переиздать существующее приглашение.')
            eid = insert('INSERT INTO experts(study,email,name) VALUES(?,?,?)', (study['id'], email, name.strip()))
        token = secrets.token_urlsafe(32)
        insert('INSERT INTO invitations(expert,hash,expires) VALUES(?,?,?)', (eid, digest(token), time.time() + 30 * 86400))
        log('invitation_created', {'expert': eid})
        db().commit()
        return jsonify(link=request.host_url + '#invite=' + token, expert=eid)

    @app.get('/api/admin/results')
    @auth('admin')
    def results():
        study = real_study()
        r, model = current(study['id'])
        rid = request.args.get('round', type=int)
        if rid:
            r = one('SELECT * FROM rounds WHERE study=? AND id=?', (study['id'], rid))
            if not r:
                fail('Раунд не найден.', 404)
            model = json.loads(one('SELECT payload FROM versions WHERE id=?', (r['version'],))['payload'])
        context = request.args.get('context', 'department')
        if context not in CONTEXTS:
            fail('Выберите контекст.')
        report = stats(r, model, context)
        comments = []
        for e in rows('SELECT e.* FROM experts e JOIN submissions s ON s.expert=e.id WHERE s.round=? AND e.context=?', (r['id'], context)):
            for k, a in answers_for(e['id'], r['id']).items():
                if k not in round_keys(r, e['id']):
                    continue
                value = a['data']
                for c in value.get('comments', []):
                    comments.append(dict(c, item=k, expert=e['id']))
                for field in ('missing', 'duplicates'):
                    if value.get(field):
                        comments.append({'item': k, 'expert': e['id'], 'target': field, 'kind': field, 'text': value[field]})
        ps = [json.loads(p['result']) for p in rows('SELECT p.result FROM priorities p JOIN experts e ON e.id=p.expert WHERE e.study=? AND e.context=? AND p.version=? AND p.submitted=1', (study['id'], context, r['version']))]
        return jsonify(report=report, comments=comments, priorities=aggregate_weights(ps), model=model, round=dict(r), context=context)

    @app.post('/api/admin/round2')
    @auth('admin')
    def round2():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        study = real_study()
        r, old = current(study['id'])
        if study['phase'] != 'content':
            fail('Повторный раунд уже открыт или исследование перешло дальше.', 409)
        n = one('SELECT COUNT(*) AS n FROM submissions WHERE round=?', (r['id'],))['n']
        if not n:
            fail('Нужен хотя бы один завершённый ответ первого раунда.')
        model = validate_model(d.get('model', old))
        previous, new = items(old), items(model)
        selected = d.get('targets', [])
        if not isinstance(selected, list) or any(k not in new for k in selected):
            fail('Проверьте список повторной оценки.')
        changed = [k for k, c in new.items() if k not in previous or any(c.get(f) != previous[k].get(f) for f in ('title', 'knows', 'skills', 'example', 'block_title'))]
        targets = sorted(set(selected + changed), key=list(new).index)
        if not targets:
            fail('Выберите хотя бы одну компетенцию для повторной оценки.')
        rationale = d.get('rationale', '')
        if not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 20000:
            fail('Добавьте обоснование изменений и обезличенную обратную связь (10–20000 символов).')
        feedback = {context: stats(r, old, context) for context in CONTEXTS}
        vid = insert('INSERT INTO versions(study,payload,hash,created) VALUES(?,?,?,?)', (study['id'], encode(model), digest(encode(model)), time.time()))
        db().execute("UPDATE rounds SET status='closed' WHERE id=?", (r['id'],))
        insert('INSERT INTO rounds(study,number,version,targets,status,feedback,rationale) VALUES(?,2,?,?,?,?,?)', (study['id'], vid, encode(targets), 'open', encode(feedback), rationale))
        db().execute("UPDATE studies SET phase='round2' WHERE id=?", (study['id'],))
        log('round2_opened', {'version': vid, 'targets': targets, 'removed': list(set(previous) - set(new)), 'rationale': rationale})
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/admin/phase')
    @auth('admin')
    def phase():
        d = body()
        db().execute('BEGIN IMMEDIATE')
        study = real_study()
        r, _ = current(study['id'])
        target = d.get('phase')
        if target == 'weights' and study['phase'] == 'round2':
            if not one('SELECT 1 FROM submissions WHERE round=? LIMIT 1', (r['id'],)):
                fail('Сначала получите завершённые ответы второго раунда.')
        elif target == 'closed' and study['phase'] == 'weights':
            pass
        else:
            fail('Переход недоступен: содержание → повторный раунд → приоритеты → завершение.', 409)
        db().execute('UPDATE studies SET phase=? WHERE id=?', (target, study['id']))
        db().execute("UPDATE rounds SET status='closed' WHERE id=?", (r['id'],))
        log('phase_changed', {'from': study['phase'], 'to': target})
        db().commit()
        return jsonify(ok=True)

    @app.get('/api/admin/export')
    @auth('admin')
    def export():
        sid = real_study()['id']
        experts = [dict(x) for x in rows('SELECT * FROM experts WHERE study=?', (sid,))]
        answers = [dict(x) for x in rows('SELECT a.* FROM answers a JOIN experts e ON e.id=a.expert WHERE e.study=?', (sid,))]
        submissions = [dict(x) for x in rows('SELECT s.* FROM submissions s JOIN experts e ON e.id=s.expert WHERE e.study=?', (sid,))]
        done = {(s['expert'], s['round']) for s in submissions}
        if request.args.get('format') == 'csv':
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(['expert_id', 'context', 'round', 'item', 'submitted', 'relevance', 'clarity', 'observability', 'completeness', 'comments', 'missing', 'duplicates'])
            contexts = {e['id']: e['context'] for e in experts}
            def safe(v):
                s = str(v)
                return "'" + s if s.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else s
            for a in answers:
                d = json.loads(a['data'])
                assigned = int(a['item'].split(':')[1]) if a['item'].startswith('block:') else int(a['item'].split(':')[0][1:])
                writer.writerow([safe(v) for v in [a['expert'], contexts[a['expert']], a['round'], a['item'], (a['expert'], a['round']) in done and assigned in assigned_blocks(a['expert']),
                                 *[d.get(k, '') for k in CRITERIA], d.get('completeness', ''), encode(d.get('comments', [])), d.get('missing', ''), d.get('duplicates', '')]])
            response = app.response_class('\ufeff' + out.getvalue(), mimetype='text/csv')
            response.headers['Content-Disposition'] = 'attachment; filename=review-answers.csv'
            return response
        payload = {'schema': 1, 'exported': time.time(), 'experts': experts, 'answers': answers, 'submissions': submissions,
                   'assignments': [dict(x) for x in rows('SELECT a.* FROM assignments a JOIN experts e ON e.id=a.expert WHERE e.study=?', (sid,))],
                   'versions': [dict(x) for x in rows('SELECT * FROM versions WHERE study=?', (sid,))],
                   'rounds': [dict(x) for x in rows('SELECT * FROM rounds WHERE study=?', (sid,))],
                   'priorities': [dict(x) for x in rows('SELECT p.* FROM priorities p JOIN experts e ON e.id=p.expert WHERE e.study=?', (sid,))],
                   'audit': [dict(x) for x in rows('SELECT * FROM audit')]}
        response = jsonify(payload)
        response.headers['Content-Disposition'] = 'attachment; filename=review-complete.json'
        return response

    @app.post('/api/logout/<role>')
    def logout(role):
        if role not in ('expert', 'admin'):
            fail('Неизвестная роль.')
        @auth(role)
        def perform():
            db().execute('DELETE FROM sessions WHERE hash=?', (g.session['hash'],))
            db().commit()
            response = jsonify(ok=True)
            response.delete_cookie(role + '_session')
            return response
        return perform()

    # One-time migration: preserve all previously answered blocks and every submitted scope.
    with app.app_context():
        db().execute('BEGIN IMMEDIATE')
        for e in rows('SELECT * FROM experts WHERE id NOT IN (SELECT expert FROM assignments)'):
            if not profile_ready(e):
                continue
            p = json.loads(e['profile'])
            p.setdefault('eligible_blocks', list(range(1, 9)))
            db().execute('UPDATE experts SET profile=? WHERE id=?', (encode(p), e['id']))
            existing = rows('SELECT item FROM answers WHERE expert=?', (e['id'],))
            keep = sorted({int(a['item'].split(':')[1]) if a['item'].startswith('block:') else int(a['item'].split(':')[0][1:]) for a in existing})
            if one('SELECT 1 FROM submissions WHERE expert=?', (e['id'],)):
                keep = list(range(1, 9))
            chosen = choose_blocks(e, p['eligible_blocks'], max(0, 2 - len(keep)), keep)
            insert('INSERT INTO assignments(expert,blocks,created) VALUES(?,?,?)', (e['id'], encode(chosen), time.time()))
            log('assignment_migrated', {'expert': e['id'], 'blocks': chosen, 'preserved_existing': keep})
        db().commit()
    return app


if __name__ == '__main__':
    app = create_app()
    print('Локальный пилот: http://127.0.0.1:8766 — ключ организатора: expert-review/.data/admin-access.txt')
    app.run(host='127.0.0.1', port=int(os.environ.get('REVIEW_PORT', '8766')), debug=False)
