import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from methodology import metric, items, solve_bwm, aggregate_weights


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATA_DIR': self.temp.name, 'ADMIN_KEY': 'test-access-key'})
        self.admin = self.app.test_client()
        self.assertEqual(self.admin.post('/api/admin/login', json={'key': 'test-access-key'}).status_code, 200)
        self.acsrf = self.admin.get('/api/admin/state').json['csrf']

    def tearDown(self):
        self.temp.cleanup()

    def ap(self, path, data):
        return self.admin.post('/api/admin/' + path, json=data, headers={'X-CSRF-Token': self.acsrf})

    def expert(self, email='one@example.org', context='department', eligible=None):
        r = self.ap('invitations', {'name': 'Эксперт', 'email': email})
        self.assertEqual(r.status_code, 200, r.json)
        token = r.json['link'].split('#invite=')[1]
        c = self.app.test_client()
        self.assertEqual(c.post('/api/invite', json={'token': token}).status_code, 200)
        csrf = c.get('/api/state').json['csrf']
        profile = {'name': 'Эксперт', 'organization': 'Организация', 'position': 'Руководитель',
                   'levels': 'Регион', 'domains': 'Качество', 'involvement': 'Нет',
                   'years': 10, 'context': context, 'consent': True, 'eligible_blocks': eligible or [1, 2]}
        self.assertEqual(c.post('/api/profile', json=profile, headers={'X-CSRF-Token': csrf}).status_code, 200)
        return c, csrf

    def ep(self, c, csrf, path, data):
        return c.post('/api/' + path, json=data, headers={'X-CSRF-Token': csrf})

    def fill(self, c, csrf, na=False):
        s = c.get('/api/state').json
        for k in s['targets'] + ['block:' + str(b) for b in sorted({int(k.split(':')[0][1:]) for k in s['targets']})]:
            data = {'completeness': 4} if k.startswith('block:') else {'relevance': 'na' if na else 4, 'clarity': 3, 'observability': 4}
            revision = s['answers'].get(k, {}).get('revision', 0)
            r = self.ep(c, csrf, 'answer', {'round': s['round']['id'], 'item': k, 'data': data, 'revision': revision})
            self.assertEqual(r.status_code, 200, r.json)
        r = self.ep(c, csrf, 'submit', {'round': s['round']['id']})
        self.assertEqual(r.status_code, 200, r.json)
        return s

    def test_balanced_persistent_assignments(self):
        clients = [self.expert(f'balance{i}@example.org', eligible=list(range(1, 9))) for i in range(8)]
        counts = {i: 0 for i in range(1, 9)}
        for c, csrf in clients:
            s = c.get('/api/state').json
            self.assertEqual(len(s['assigned_blocks']), 2)
            self.assertEqual(len(s['targets']), 6)
            self.assertEqual(c.get('/api/state').json['assigned_blocks'], s['assigned_blocks'])
            for n in s['assigned_blocks']:
                counts[n] += 1
            other = next(k for k in items(s['model']) if k not in s['targets'])
            self.assertEqual(self.ep(c, csrf, 'answer', {'round': s['round']['id'], 'item': other, 'data': {'relevance': 4}, 'revision': 0}).status_code, 400)
        self.assertEqual(set(counts.values()), {2})
        coverage = self.admin.get('/api/admin/state').json['coverage']['department']
        self.assertTrue(all(b['assigned'] == 2 and b['submitted'] == 0 for b in coverage))

    def test_replacement_preserves_draft_and_excludes_statistics(self):
        c, csrf = self.expert(eligible=list(range(1, 9)))
        s = c.get('/api/state').json
        key = s['targets'][0]
        block = int(key.split(':')[0][1:])
        self.ep(c, csrf, 'answer', {'round': s['round']['id'], 'item': key, 'data': {'relevance': 1}, 'revision': 0})
        r = self.ep(c, csrf, 'replace-block', {'round': s['round']['id'], 'block': block, 'reason': 'Недостаточно опыта в этом блоке'})
        self.assertEqual(r.status_code, 200, r.json)
        new = c.get('/api/state').json
        self.assertNotIn(block, new['assigned_blocks'])
        self.assertIn(key, new['answers'])
        self.fill(c, csrf)
        result = self.admin.get('/api/admin/results?context=department').json['report']['items'][key]['relevance']
        self.assertEqual((result['n'], result['missing']), (0, 0))
        self.assertEqual(self.ep(c, csrf, 'replace-block', {'round': s['round']['id'], 'block': new['assigned_blocks'][0], 'reason': 'Хочу сменить'}).status_code, 409)

    def test_round2_outside_assignment_is_not_required(self):
        c, csrf = self.expert(eligible=[1, 2])
        s = self.fill(c, csrf)
        other, token = self.expert('other@example.org', eligible=[3, 4])
        t = self.fill(other, token)
        self.assertEqual(self.ap('round2', {'targets': [t['targets'][0]], 'rationale': 'Пересмотр только третьего блока.'}).status_code, 200)
        new = c.get('/api/state').json
        self.assertEqual(new['targets'], [])
        self.assertTrue(new['content_finished'])
        self.assertFalse(new['submitted'])
        self.assertEqual(self.ep(c, csrf, 'submit', {'round': new['round']['id']}).status_code, 400)

    def test_auth_isolation_and_revocation(self):
        outsider = self.app.test_client()
        self.assertEqual(outsider.get('/api/admin/export').status_code, 401)
        self.assertEqual(outsider.post('/api/admin/login', json={'key': 'wrong'}).status_code, 401)
        self.assertEqual(self.admin.post('/api/admin/invitations', json={}).status_code, 403)
        self.assertEqual(self.admin.post('/api/admin/invitations', json={}, headers={'Origin': 'https://evil.example', 'X-CSRF-Token': self.acsrf}).status_code, 403)
        c, csrf = self.expert()
        d, dcsrf = self.expert('two@example.org')
        self.assertNotEqual(c.get('/api/state').json['expert']['id'], d.get('/api/state').json['expert']['id'])
        self.assertEqual(c.get('/api/admin/state').status_code, 401)
        self.ap('invitations', {'name': 'Эксперт', 'email': 'one@example.org'})
        self.assertEqual(c.get('/api/state').status_code, 401)
        self.assertEqual(d.get('/api/state').status_code, 200)

    def test_validation_revision_and_locked_submit(self):
        c, csrf = self.expert()
        s = c.get('/api/state').json
        data = {'round': s['round']['id'], 'item': s['targets'][0], 'data': {'relevance': 4}, 'revision': 0}
        self.assertEqual(self.ep(c, csrf, 'answer', dict(data, data={'relevance': True})).status_code, 400)
        self.assertEqual(self.ep(c, csrf, 'answer', dict(data, data={'comments': [{'target': 'knows:999', 'kind': 'error', 'text': 'Ошибка'}]})).status_code, 400)
        self.assertEqual(self.ep(c, csrf, 'answer', data).status_code, 200)
        self.assertEqual(self.ep(c, csrf, 'answer', data).status_code, 409)
        self.assertEqual(self.ep(c, csrf, 'submit', {'round': s['round']['id']}).status_code, 400)
        p = c.get('/api/state').json['profile']
        self.assertEqual(self.ep(c, csrf, 'profile', dict(p, context='system')).status_code, 409)
        report = self.admin.get('/api/admin/results?context=department').json['report']
        self.assertEqual(report['submitted'], 0)
        self.fill(c, csrf, na=True)
        self.assertEqual(self.ep(c, csrf, 'answer', dict(data, revision=2)).status_code, 409)
        m = self.admin.get('/api/admin/results?context=department').json['report']['items'][s['targets'][0]]['relevance']
        self.assertEqual((m['n'], m['na'], m['positive_fraction']), (0, 1, None))

    def test_demo_excluded_and_snapshot_independent(self):
        c = self.app.test_client()
        c.post('/api/demo', json={})
        s = c.get('/api/state').json
        self.assertEqual(s['study']['demo'], 1)
        self.assertEqual(len(self.admin.get('/api/admin/state').json['experts']), 0)
        self.assertEqual(len(self.admin.get('/api/admin/export').json['experts']), 0)

    def test_full_round2_bwm_and_export(self):
        c, csrf = self.expert()
        s = self.fill(c, csrf)
        model = copy.deepcopy(s['model'])
        model['blocks'][0]['competencies'][0]['title'] += ' — новая редакция'
        r = self.ap('round2', {'model': model, 'targets': [], 'rationale': 'Уточнена формулировка после замечаний экспертов.'})
        self.assertEqual(r.status_code, 200, r.json)
        new = c.get('/api/state').json
        self.assertEqual(new['targets'], [s['targets'][0]])
        self.assertNotEqual(new['round']['version'], s['round']['version'])
        self.assertEqual(new['previous_model'], s['model'])
        self.assertTrue(new['feedback']['hidden'])
        self.assertEqual(self.ep(c, csrf, 'answer', {'round': s['round']['id']}).status_code, 409)
        self.assertEqual(self.ap('phase', {'phase': 'weights'}).status_code, 400)
        self.fill(c, csrf)
        self.assertEqual(self.ap('phase', {'phase': 'weights'}).status_code, 200)
        value = {'best': '1', 'worst': '8', 'comparisons': {**{f'1:{i}': 1 for i in range(2, 9)}, **{f'{i}:8': 1 for i in range(2, 8)}}}
        payload = {'version': new['round']['version'], 'revision': 0, 'data': value, 'submit': True}
        result = self.ep(c, csrf, 'priorities', payload)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertAlmostEqual(result.json['result']['weights']['1'], .125)
        self.assertEqual(self.ep(c, csrf, 'priorities', dict(payload, revision=1)).status_code, 409)
        report = self.admin.get('/api/admin/results?context=department').json
        self.assertEqual(report['priorities']['n'], 1)
        archive = self.admin.get('/api/admin/export').json
        self.assertEqual(len(archive['versions']), 2)
        self.assertNotIn('sessions', archive)
        self.assertNotIn('invitations', archive)
        self.assertEqual(len(archive['submissions']), 2)
        self.assertTrue(self.admin.get('/api/admin/export?format=csv').data.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(self.ap('phase', {'phase': 'closed'}).status_code, 200)

    def test_feedback_separated_by_context(self):
        clients = [self.expert(f'{i}@example.org') for i in range(3)]
        system, token = self.expert('sys@example.org', 'system')
        for c, csrf in clients:
            s = self.fill(c, csrf)
        self.fill(system, token, na=True)
        r = self.ap('round2', {'targets': [s['targets'][0]], 'rationale': 'Повторная оценка спорной формулировки.'})
        self.assertEqual(r.status_code, 200)
        fb = clients[0][0].get('/api/state').json['feedback']
        self.assertEqual(fb['submitted'], 3)
        self.assertEqual(fb['items'][s['targets'][0]]['relevance']['n'], 3)
        self.assertTrue(system.get('/api/state').json['feedback']['hidden'])


class CalculationTests(unittest.TestCase):
    def test_cvi(self):
        m = metric([1, 2, 3, 4, 'na', None])
        self.assertEqual((m['n'], m['na'], m['missing'], m['positive_fraction']), (4, 1, 1, .5))
        self.assertEqual(metric([4] * 7)['flag'], 'Мало данных')
        self.assertEqual(metric([4] * 8)['flag'], 'Ориентир достигнут')

    def test_bwm_known_ratios(self):
        blocks = [{'number': i} for i in range(1, 9)]
        value = {'best': '1', 'worst': '8', 'comparisons': {**{f'1:{i}': 2 for i in range(2, 9)}, **{f'{i}:8': 1 for i in range(2, 8)}}}
        r = solve_bwm(blocks, value)
        self.assertAlmostEqual(r['weights']['1'], 2 / 9)
        self.assertAlmostEqual(r['weights']['8'], 1 / 9)
        self.assertAlmostEqual(r['residual'], 0)
        self.assertAlmostEqual(sum(r['weights'].values()), 1)
        avg = aggregate_weights([r, r])
        self.assertAlmostEqual(avg['blocks']['1']['sd'], 0)
        value['comparisons'].pop('2:8')
        with self.assertRaises(ValueError):
            solve_bwm(blocks, value)


if __name__ == '__main__':
    unittest.main()
