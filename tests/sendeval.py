# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/sendeval.js (VK D3, 0.11.4) – evaluation of sending (form metrics, correctness, focus).
When sendeval.js changes, update this copy too (test_sendeval.py checks the constants and shared fragments)."""
import math
import re
from pathlib import Path

from tests.content import SHARE_DIGITS, SHARE_LETTERS, pools, word
from tests.copy import align, score

SENDEVAL_JS = (Path(__file__).resolve().parent.parent / 'web/js/sendeval.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = ([\d.]+);', SENDEVAL_JS)}
BANDS = {m.group(1): [float(x) for x in m.group(2).split(',')]
         for m in re.finditer(r'export const (EVAL_[A-Z_]+) = \[([^\]]*)\];', SENDEVAL_JS)}

MIN_N = int(CONSTS['EVAL_MIN_N'])
WINDOW = int(CONSTS['EVAL_WINDOW'])
RATIO = BANDS['EVAL_RATIO']
IN_GAP = BANDS['EVAL_IN_GAP']
CHAR_GAP = BANDS['EVAL_CHAR_GAP']
WORD_GAP = BANDS['EVAL_WORD_GAP']
CV_GOOD = CONSTS['EVAL_CV_GOOD']
CV_OK = CONSTS['EVAL_CV_OK']
ACC_GOOD = CONSTS['EVAL_ACC_GOOD']
ACC_OK = CONSTS['EVAL_ACC_OK']
SEND_KINDS = re.findall(r"'(\w+)'", re.search(r'export const SEND_KINDS = \[([^\]]*)\]', SENDEVAL_JS).group(1))
SEND_TASKS = int(CONSTS['SEND_TASKS'])
SEND_MIN_CHARS = int(CONSTS['SEND_MIN_CHARS'])
SEND_GROUP_LEN = int(CONSTS['SEND_GROUP_LEN'])
SEND_END_MS = CONSTS['SEND_END_MS']
SEND_END_UNITS = CONSTS['SEND_END_UNITS']
DOT = '.'


def median(arr):
    if not arr:
        return None
    a = sorted(arr)
    n = len(a)
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2


def robust_cv(arr):
    if len(arr) < MIN_N:
        return None
    m = median(arr)
    if not m:
        return None
    return 1.4826 * median([abs(x - m) for x in arr]) / m


def band(v, b):
    if b[1] <= v <= b[2]:
        return 'good'
    if b[3] <= v <= b[4]:
        return 'ok'
    return 'bad'


def text_units(codes):
    u, prev = 0, None
    for c in codes:
        if c == ' ':
            prev = ' '
            continue
        if prev is not None:
            u += 7 if prev == ' ' else 3
        for el in c:
            u += 2 if el == DOT else 4
        u -= 1
        prev = c
    return u


def form_values(tones, dec):
    def length(i):
        return tones[i]['end'] - tones[i]['start']
    v = {'dots': [], 'dashes': [], 'handDots': [], 'hand': 0, 'inGaps': [], 'charGaps': [], 'wordGaps': [],
         'units': 0, 'dur': 0, 'dot': dec['dot']}
    for i, el in enumerate(dec['marks']):
        if not tones[i].get('el'):
            v['hand'] += 1
        (v['dots'] if el == DOT else v['dashes']).append(length(i))
        if el == DOT and not tones[i].get('el'):
            v['handDots'].append(length(i))
    for i, kind in enumerate(dec['gaps']):
        if kind is None:
            continue
        g = tones[i]['start'] - tones[i - 1]['end']
        if kind == 0:
            if not tones[i].get('el') and not tones[i - 1].get('el'):
                v['inGaps'].append(g)
        elif kind == 1:
            v['charGaps'].append(g)
        else:
            v['wordGaps'].append(g)
    if tones and any(c != ' ' for c in dec['codes']):
        v['units'] = text_units(dec['codes'])
        v['dur'] = tones[-1]['end'] - tones[0]['start']
    return v


def metrics_from(v):
    dots, dashes = v['dots'], v['dashes']
    unit = median(dots) if dots else (median(dashes) / 3 if dashes else v['dot'])
    m = {'unit': unit, 'charWpm': 1200 / unit, 'effWpm': None, 'ratio': None, 'inGap': None, 'charGap': None,
         'wordGap': None, 'stability': None}
    if v['hand'] and len(dots) >= MIN_N and len(dashes) >= MIN_N:
        x = median(dashes) / median(dots)
        m['ratio'] = {'v': x, 'st': band(x, RATIO)}
    if len(v['inGaps']) >= MIN_N:
        x = median(v['inGaps']) / unit
        m['inGap'] = {'v': x, 'st': band(x, IN_GAP)}
    if len(v['charGaps']) >= MIN_N:
        x = median(v['charGaps']) / unit
        m['charGap'] = {'v': x, 'st': band(x, CHAR_GAP)}
    if v['wordGaps']:
        x = median(v['wordGaps']) / unit
        m['wordGap'] = {'v': x, 'st': band(x, WORD_GAP)}
    cv_dot, cv_gap = robust_cv(v['handDots']), robust_cv(v['charGaps'])
    cvs = [x for x in (cv_dot, cv_gap) if x is not None]
    if cvs:
        x = max(cvs)
        m['stability'] = {'v': x, 'dot': cv_dot, 'gap': cv_gap,
                          'st': 'good' if x <= CV_GOOD else ('ok' if x <= CV_OK else 'bad')}
    if v['dur'] > 0:
        m['effWpm'] = 1200 * v['units'] / v['dur']
    return m


def send_metrics(tones, dec):
    values = form_values(tones, dec)
    return {**metrics_from(values), 'values': values}


def evaluate_sending(target, tones, dec, morse):
    sent = list(re.sub(r'\s+', '', target))
    got = [c for c in dec['chars'] if c['ch'] != ' ']
    typed = [c['ch'] for c in got]
    ops = align(sent, typed)
    sc = score(ops, sent, typed)
    v = sc['acc'] if sc['acc'] is not None else 0
    subs = [{'want': sent[o['s']], 'wantCode': morse.get(sent[o['s']], ''), 'got': typed[o['t']],
             'gotCode': got[o['t']]['code']} for o in ops if o['op'] == 'sub']
    return {
        'ops': ops,
        'acc': {'ok': sc['ok'], 'sub': sc['sub'], 'del': sc['del'], 'ins': sc['ins'], 'n': sc['n'], 'v': v,
                'st': 'good' if v >= ACC_GOOD else ('ok' if v >= ACC_OK else 'bad')},
        'subs': subs,
        'fixes': dec['fixes'],
        'metrics': send_metrics(tones, dec),
    }


FORM = [('ratio', RATIO), ('inGap', IN_GAP), ('charGap', CHAR_GAP), ('wordGap', WORD_GAP)]


def focus_of(metrics, ev=None):
    if ev and ev['acc']['st'] != 'good' and ev['subs']:
        cnt = {}
        for s in ev['subs']:
            k = s['want'] + s['got']
            cnt[k] = cnt.get(k, 0) + 1
        top = ev['subs'][0]
        for s in ev['subs']:
            if cnt[s['want'] + s['got']] > cnt[top['want'] + top['got']]:
                top = s
        return {'key': 'acc', 'dir': None, 'v': ev['acc']['v'], 'sub': top}
    rank = {'bad': 2, 'ok': 1, 'good': 0}
    best = None
    for key, b in FORM:
        x = metrics[key]
        if not x or x['st'] == 'good':
            continue
        d = 'low' if x['v'] < b[0] else 'high'
        dist = abs(math.log(x['v'] / b[0])) / math.log(b[0] / b[3] if d == 'low' else b[4] / b[0])
        c = {'key': key, 'dir': d, 'v': x['v'], 'r': rank[x['st']], 'dist': dist}
        if not best or c['r'] > best['r'] or (c['r'] == best['r'] and c['dist'] > best['dist']):
            best = c
    s = metrics['stability']
    if s and s['st'] != 'good':
        c = {'key': 'stability', 'dir': 'high', 'v': s['v'], 'r': rank[s['st']], 'dist': s['v'] / CV_OK}
        if not best or c['r'] > best['r']:
            best = c
    if not best:
        return {'key': 'good', 'dir': None, 'v': None}
    return {'key': best['key'], 'dir': best['dir'], 'v': best['v']}


def send_task(kind, chars, rng, prev=None):
    """rng() → float in [0, 1) as in JS."""
    if kind == 'group':
        p = pools(chars)
        out = ''
        for _ in range(SEND_GROUP_LEN):
            r = rng()
            pool = p['L'] if r < SHARE_LETTERS else (p['D'] if r < SHARE_LETTERS + SHARE_DIGITS else p['P'])
            if not pool:
                pool = p['L'] or chars
            out += pool[int(rng() * len(pool))]
        return out
    if kind == 'qso':
        return qso_line(rng) if qso_ready(chars) else word(chars, rng)
    if kind == 'word':
        return word(chars, rng)
    avail = [c for c in chars if c != prev] if len(chars) > 1 else chars
    return avail[int(rng() * len(avail))]


def session_summary(lst):
    c = {'ok': 0, 'sub': 0, 'del': 0, 'ins': 0, 'n': 0}
    subs, fixes = [], 0
    for ev in lst:
        for k in c:
            c[k] += ev['acc'][k]
        subs += ev['subs']
        fixes += ev['fixes']
    den = c['n'] + c['ins']
    v = c['ok'] / den if den else 0
    cnt = {}
    for s in subs:
        k = s['want'] + s['got']
        if k not in cnt:
            cnt[k] = {**s, 'n': 0}
        cnt[k]['n'] += 1
    conf = sorted(cnt.values(), key=lambda x: -x['n'])[:3]

    pool = {'dots': [], 'dashes': [], 'handDots': [], 'hand': 0, 'inGaps': [], 'charGaps': [], 'wordGaps': [],
            'units': 0, 'dur': 0, 'dot': None}
    dots_est = []
    for ev in lst:
        fv = ev['metrics']['values']
        for k in ('dots', 'dashes', 'handDots', 'inGaps', 'charGaps', 'wordGaps'):
            pool[k] += fv[k]
        pool['hand'] += fv['hand']
        pool['units'] += fv['units']
        pool['dur'] += fv['dur']
        dots_est.append(fv['dot'])
    pool['dot'] = median(dots_est) if dots_est else 60
    metrics = metrics_from(pool)
    return {'acc': {**c, 'v': v, 'st': 'good' if v >= ACC_GOOD else ('ok' if v >= ACC_OK else 'bad')},
            'subs': subs, 'conf': conf, 'fixes': fixes, 'metrics': metrics, 'tasks': len(lst)}


# 0.17.0 D4 + Z-24 (ports of qsoReady / qsoCall / qsoLine / handHabits / oneElement)
SEND_STEPS = re.findall(r"'(\w+)'", re.search(r'export const SEND_STEPS = \[([^\]]*)\]', SENDEVAL_JS).group(1))
SEND_PASS_ACC = CONSTS['SEND_PASS_ACC']
SEND_PASS_N = int(CONSTS['SEND_PASS_N'])
HABIT_WORD_RATIO = CONSTS['HABIT_WORD_RATIO']
HABIT_CHAR_LONG = CONSTS['HABIT_CHAR_LONG']
HABIT_PADDLE_N = int(CONSTS['HABIT_PADDLE_N'])
QSO_LINES = re.findall(r"'([^']*)'", re.search(r'const QSO_LINES = \[(.*?)\];', SENDEVAL_JS, re.S).group(1))
QSO_PFX = re.findall(r"'(\w+)'", re.search(r'const QSO_PFX = \[(.*?)\];', SENDEVAL_JS, re.S).group(1))
QSO_NAMES = re.findall(r"'(\w+)'", re.search(r'const QSO_NAMES = \[(.*?)\];', SENDEVAL_JS, re.S).group(1))
QSO_QTH = re.findall(r"'(\w+)'", re.search(r'const QSO_QTH = \[(.*?)\];', SENDEVAL_JS, re.S).group(1))
QSO_WX = re.findall(r"'(\w+)'", re.search(r'const QSO_WX = \[(.*?)\];', SENDEVAL_JS, re.S).group(1))
LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
DIGITS = '0123456789'


def _pick(arr, rng):
    return arr[int(rng() * len(arr))]


def qso_ready(chars):
    have = set(chars)
    return all(c in have for c in LETTERS + DIGITS)


def qso_call(rng):
    s = _pick(QSO_PFX, rng) + _pick(DIGITS, rng)
    n = 2 if rng() < 0.5 else 3
    for _ in range(n):
        s += _pick(LETTERS, rng)
    return s


def qso_line(rng):
    c = qso_call(rng)
    m = qso_call(rng)
    v = {'c': c, 'm': m, 'n': str(3 + int(rng() * 7)), 'name': _pick(QSO_NAMES, rng), 'qth': _pick(QSO_QTH, rng),
         'p': str(_pick([5, 10, 50, 100], rng)), 'wx': _pick(QSO_WX, rng), 't': str(int(rng() * 30))}
    return re.sub(r'\{(\w+)\}', lambda mo: v[mo.group(1)], _pick(QSO_LINES, rng))


def one_element(a, b):
    if not a or not b or abs(len(a) - len(b)) != 1:
        return False
    lo, sh = (a, b) if len(a) > len(b) else (b, a)
    return any(lo[:i] + lo[i + 1:] == sh for i in range(len(lo)))


def hand_habits(metrics, ev=None):
    out = []
    cg = (metrics.get('charGap') or {}).get('v')
    wg = (metrics.get('wordGap') or {}).get('v')
    if cg and wg and wg / cg < HABIT_WORD_RATIO:
        out.append({'key': 'wordShort', 'v': wg / cg})
    if cg and cg > HABIT_CHAR_LONG:
        out.append({'key': 'charLong', 'v': cg})
    n = sum(1 for x in ((ev or {}).get('subs') or []) if one_element(x['wantCode'], x['gotCode']))
    if n >= HABIT_PADDLE_N:
        out.append({'key': 'paddle', 'v': n})
    return out
