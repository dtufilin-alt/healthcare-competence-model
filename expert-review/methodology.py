"""Project-specific content review statistics and the linear BWM (Rezaei 2016)."""
from statistics import median, mean, pstdev
from scipy.optimize import linprog

CONTEXTS = {
    'department': 'Подразделение', 'organization': 'Медицинская организация',
    'region': 'Регион', 'system': 'Система здравоохранения',
}
CRITERIA = ('relevance', 'clarity', 'observability')


def items(model):
    return {f'b{b["number"]}:{c["id"]}': dict(c, block=b['number'],
            block_title=b['title'], code=f'{b["number"]}.{i + 1}')
            for b in model['blocks'] for i, c in enumerate(b['competencies'])}


def validate_model(model):
    if not isinstance(model, dict) or not isinstance(model.get('blocks'), list) or len(model['blocks']) != 8:
        raise ValueError('Модель должна содержать восемь блоков.')
    keys = set()
    for i, block in enumerate(model['blocks'], 1):
        if not isinstance(block, dict) or type(block.get('number')) is not int or block['number'] != i or not isinstance(block.get('title'), str) or not block['title'].strip():
            raise ValueError('Нужны номера блоков 1–8 и их названия.')
        cs = block.get('competencies')
        if not isinstance(cs, list) or not 1 <= len(cs) <= 20:
            raise ValueError('В каждом блоке должно быть от 1 до 20 компетенций.')
        for c in cs:
            import re
            if not isinstance(c, dict):
                raise ValueError('Компетенция должна быть объектом с полями.')
            cid = c.get('id', '')
            if not isinstance(cid, str) or not re.fullmatch(r'[a-z0-9-]{1,80}', cid) or (i, cid) in keys:
                raise ValueError('Идентификаторы компетенций должны быть уникальны в блоке.')
            keys.add((i, cid))
            for k in ('title', 'example'):
                if not isinstance(c.get(k), str) or not 1 <= len(c[k]) <= 10000:
                    raise ValueError('Проверьте название и пример компетенции.')
            for k in ('knows', 'skills'):
                if not isinstance(c.get(k), list) or not 1 <= len(c[k]) <= 30 or any(not isinstance(s, str) or not 1 <= len(s) <= 10000 for s in c[k]):
                    raise ValueError('Знания и умения должны быть непустыми списками строк.')
    return model


def metric(values):
    valid = [v for v in values if type(v) is int and 1 <= v <= 4]
    n = len(valid)
    positive = sum(v >= 3 for v in valid)
    cvi = positive / n if n else None
    return {'n': n, 'na': values.count('na'), 'missing': values.count(None),
            'distribution': {str(v): valid.count(v) for v in range(1, 5)},
            'median': median(valid) if n else None, 'min': min(valid) if n else None,
            'max': max(valid) if n else None, 'positive_fraction': cvi,
            'flag': 'Мало данных' if n < 8 else ('Обсудить' if cvi < .78 else 'Ориентир достигнут')}


def solve_bwm(blocks, data):
    ids = [str(b['number']) for b in blocks]
    best, worst = str(data.get('best', '')), str(data.get('worst', ''))
    if best not in ids or worst not in ids or best == worst:
        raise ValueError('Выберите разные наиболее и наименее важные блоки.')
    comparisons = data.get('comparisons', {})
    pairs = [(best, j) for j in ids if j != best] + [(j, worst) for j in ids if j not in (best, worst)]
    expected = {f'{i}:{j}' for i, j in pairs}
    if set(comparisons) != expected or any(type(v) is not int or not 1 <= v <= 9 for v in comparisons.values()):
        raise ValueError('Заполните все 13 сравнений числами от 1 до 9.')
    n = len(ids)
    a = []
    for i, j in pairs:
        row = [0.] * (n + 1)
        row[ids.index(i)] = 1.
        row[ids.index(j)] = -comparisons[f'{i}:{j}']
        row[-1] = -1.
        a.extend([row, [-v for v in row[:-1]] + [-1.]])
    fit = linprog([0.] * n + [1.], A_ub=a, b_ub=[0.] * len(a),
                  A_eq=[[1.] * n + [0.]], b_eq=[1.], bounds=[(0, None)] * (n + 1), method='highs')
    if not fit.success:
        raise ValueError('Расчёт не завершён. Ответы сохранены; попробуйте ещё раз.')
    warnings = []
    bw = comparisons[f'{best}:{worst}']
    if any(v > bw for v in comparisons.values()):
        warnings.append('Есть сравнение сильнее, чем между наиболее и наименее важным блоками. Проверьте суждения.')
    weights = {k: float(fit.x[i]) for i, k in enumerate(ids)}
    if weights[best] < max(weights.values()) - 1e-7 or weights[worst] > min(weights.values()) + 1e-7:
        warnings.append('Полученный порядок весов отличается от выбранных крайних блоков.')
    return {'weights': weights, 'residual': float(fit.x[-1]), 'warnings': warnings,
            'method': 'Linear BWM, Rezaei 2016; residual is not a consistency ratio'}


def aggregate_weights(results):
    if not results:
        return {'n': 0, 'blocks': {}}
    return {'n': len(results), 'blocks': {k: {'mean': mean(r['weights'][k] for r in results),
            'sd': pstdev(r['weights'][k] for r in results),
            'min': min(r['weights'][k] for r in results), 'max': max(r['weights'][k] for r in results)}
            for k in results[0]['weights']}}
