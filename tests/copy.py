# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/copy.js (copy behind, M7 + M8) – alignment, lag, word results, fatigue.
When copy.js changes, update this copy too (test_copy.py checks the constants)."""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY_JS = (ROOT / 'web/js/copy.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'export const ([A-Z_]+) = ([0-9.]+);', COPY_JS)}
ROUND_ITEMS = int(CONSTS['ROUND_ITEMS'])
ROUND_TAIL_MS = CONSTS['ROUND_TAIL_MS']
COPY_MIN_CHARS = int(CONSTS['COPY_MIN_CHARS'])
FAT_BASE_ROUNDS, FAT_WIN_ROUNDS = int(CONSTS['FAT_BASE_ROUNDS']), int(CONSTS['FAT_WIN_ROUNDS'])
FAT_ACC_DROP, FAT_ACC_FLOOR, FAT_MISS_UP = CONSTS['FAT_ACC_DROP'], CONSTS['FAT_ACC_FLOOR'], CONSTS['FAT_MISS_UP']
FAT_HOLD_S, FAT_SNOOZE_S = CONSTS['FAT_HOLD_S'], CONSTS['FAT_SNOOZE_S']


def js_round(x):
    return math.floor(x + 0.5)


def align(sent, typed):
    n, m = len(sent), len(typed)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j - 1] + (sent[i - 1] != typed[j - 1]), d[i - 1][j] + 1, d[i][j - 1] + 1)
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        cur = d[i][j]
        if i > 0 and j > 0 and cur == d[i - 1][j - 1] + (sent[i - 1] != typed[j - 1]):
            ops.append({'op': 'ok' if sent[i - 1] == typed[j - 1] else 'sub', 's': i - 1, 't': j - 1})
            i, j = i - 1, j - 1
        elif i > 0 and cur == d[i - 1][j] + 1:
            ops.append({'op': 'del', 's': i - 1, 't': None})
            i -= 1
        else:
            ops.append({'op': 'ins', 's': None, 't': j - 1})
            j -= 1
    return ops[::-1]


def ignored_ops(ops, skip):
    """M9 part 2: operations on a masked sent character and extra characters right next to one do not count."""
    out = [False] * len(ops)
    if not skip or not any(skip):
        return out
    prev, nxt, m = [False] * len(ops), [False] * len(ops), False
    for k, o in enumerate(ops):
        prev[k] = m
        if o['s'] is not None:
            m = bool(skip[o['s']])
    m = False
    for k in range(len(ops) - 1, -1, -1):
        nxt[k] = m
        if ops[k]['s'] is not None:
            m = bool(skip[ops[k]['s']])
    return [bool(skip[o['s']]) if o['s'] is not None else prev[k] or nxt[k] for k, o in enumerate(ops)]


def score(ops, sent, typed, skip=None):
    c = {'ok': 0, 'sub': 0, 'del': 0, 'ins': 0, 'mask': 0}
    conf = {}
    ign = ignored_ops(ops, skip)
    for k, o in enumerate(ops):
        if ign[k]:
            if o['s'] is not None:
                c['mask'] += 1
            continue
        c[o['op']] += 1
        if o['op'] == 'sub':
            k = f"{sent[o['s']]}→{typed[o['t']]}"
            conf[k] = conf.get(k, 0) + 1
    n = len(sent) - c['mask']
    den = n + c['ins']
    return {**c, 'n': n, 'acc': c['ok'] / den if den else None, 'conf': conf}


def median(arr):
    if not arr:
        return None
    s = sorted(arr)
    h = len(s) >> 1
    return s[h] if len(s) % 2 else (s[h - 1] + s[h]) / 2


def percentile(arr, p):
    if not arr:
        return None
    s = sorted(arr)
    return s[min(len(s) - 1, math.floor(p * len(s)))]


def lag_samples(ops, ends, times, word_of=None):
    w_end = {}
    if word_of:
        for i, w in enumerate(word_of):
            w_end[w] = ends[i]
    nw = max(w_end) + 1 if w_end else 0
    out = []
    for o in ops:
        if o['op'] not in ('ok', 'sub'):
            continue
        t = times[o['t']]
        ch = 0
        k = o['s'] + 1
        while k < len(ends) and ends[k] <= t:
            ch += 1
            k += 1
        x = {'s': o['s'], 'ms': js_round(t - ends[o['s']]), 'ch': ch}
        if word_of:
            wd, k = 0, word_of[o['s']] + 1
            while k < nw and w_end[k] <= t:
                wd += 1
                k += 1
            x['wd'] = wd
        out.append(x)
    return out


def r1(x):
    return None if x is None else js_round(x * 10) / 10


def lag_summary(samples):
    if not samples:
        return {k: None for k in ('lagMs', 'lagP90', 'lagCh', 'lagChP90', 'lagChMax', 'drift', 'lagW', 'lagWP90')}
    ms = [x['ms'] for x in samples]
    ch = [x['ch'] for x in samples]
    third = len(ch) // 3
    drift = median(ch[-third:]) - median(ch[:third]) if third >= 3 else None
    return {'lagMs': js_round(median(ms)), 'lagP90': percentile(ms, 0.9), 'lagCh': r1(median(ch)),
            'lagChP90': percentile(ch, 0.9), 'lagChMax': max(ch), 'drift': r1(drift), **word_lag(samples)}


def word_lag(samples):
    wd = [x['wd'] for x in samples if 'wd' in x]
    return {'lagW': r1(median(wd)), 'lagWP90': percentile(wd, 0.9)} if wd else {'lagW': None, 'lagWP90': None}


def word_results(words, ops, skip=None):
    word_of = [k for k, wd in enumerate(words) for _ in wd]
    ok = [True] * len(words)
    next_word = [-1] * len(ops)
    nw = -1
    for k in range(len(ops) - 1, -1, -1):
        next_word[k] = nw
        if ops[k]['s'] is not None:
            nw = word_of[ops[k]['s']]
    ign = ignored_ops(ops, skip)
    last = -1
    for k, o in enumerate(ops):
        if o['s'] is not None:
            last = word_of[o['s']]
            if o['op'] != 'ok' and not ign[k]:
                ok[last] = False
        elif not ign[k] and last >= 0 and next_word[k] == last:
            ok[last] = False
    return ok


def evaluate(words, chars, typed):
    sent = [c['ch'] for c in chars]
    tch = [x['ch'] for x in typed]
    ops = align(sent, tch)
    skip = [bool(c.get('mask')) for c in chars] if any(c.get('mask') for c in chars) else None
    return {'ops': ops, 'sc': score(ops, sent, tch, skip),
            'lags': lag_samples(ops, [c['end'] for c in chars], [x['t'] for x in typed], [c['w'] for c in chars]),
            'words': word_results(words, ops, skip)}


def lesson_summary(rounds):
    c = {'ok': 0, 'sub': 0, 'del': 0, 'ins': 0, 'n': 0, 'mask': 0}
    conf, lags, wn, wok = {}, [], 0, 0
    for r in rounds:
        for k in c:
            c[k] += r['ev']['sc'].get(k) or 0
        for k, v in r['ev']['sc']['conf'].items():
            conf[k] = conf.get(k, 0) + v
        lags += r['ev']['lags']
        wn += len(r['ev']['words'])
        wok += sum(1 for x in r['ev']['words'] if x)
    den = c['n'] + c['ins']
    confusions = [{'pair': k, 'n': v} for k, v in sorted(conf.items(), key=lambda kv: -kv[1])]
    return {**c, 'acc': c['ok'] / den if den else None, **lag_summary(lags), 'words': {'n': wn, 'ok': wok},
            'rounds': len(rounds), 'confusions': confusions[:30]}


# ---------- fatigue in copy behind (M8) ----------
def round_stats(lst):
    ok, n, ins, d = (sum(x[k] for x in lst) for k in ('ok', 'n', 'ins', 'del'))
    return {'acc': ok / (n + ins) if n + ins else 0, 'miss': d / n if n else 0, 'n': n}


class CopyFatigue:
    def __init__(self):
        self.base_rounds, self.base, self.win = [], None, []
        self.since, self.snooze_until = None, 0
        self.last = {'tired': False, 'accDrop': None, 'missUp': None}

    def reset(self):
        self.win, self.since = [], None

    def snooze(self, active_s):
        self.snooze_until, self.since = active_s + FAT_SNOOZE_S, None

    def add(self, sc, start_s, end_s):
        none = {'propose': False, 'kind': None, 'accDrop': None, 'missUp': None}
        r = {'ok': sc['ok'], 'n': sc['n'], 'ins': sc['ins'], 'del': sc['del'], 'startS': start_s}
        if not self.base:
            self.base_rounds.append(r)
            if len(self.base_rounds) >= FAT_BASE_ROUNDS:
                self.base = round_stats(self.base_rounds)
            return none
        self.win.append(r)
        if len(self.win) > FAT_WIN_ROUNDS:
            self.win.pop(0)
        if len(self.win) < FAT_WIN_ROUNDS:
            self.since = None
            return none
        cur = round_stats(self.win)
        acc_drop = js_round((self.base['acc'] - cur['acc']) * 1000) / 1000
        miss_up = js_round((cur['miss'] - self.base['miss']) * 1000) / 1000
        acc_t = acc_drop >= FAT_ACC_DROP - 1e-9 and cur['acc'] < FAT_ACC_FLOOR - 1e-9
        miss_t = miss_up >= FAT_MISS_UP - 1e-9
        self.last = {'tired': acc_t or miss_t, 'accDrop': acc_drop, 'missUp': miss_up}
        if not self.last['tired']:
            self.since = None
            return none
        if self.since is None:
            self.since = self.win[0]['startS']
        propose = end_s - self.since > FAT_HOLD_S and end_s >= self.snooze_until
        return {'propose': propose, 'kind': 'acc' if acc_t else 'miss', 'accDrop': acc_drop, 'missUp': miss_up}


# ---------- line simulation (for tests): sent characters with end times, a typist with a lag ----------
def stream(words, char_ms=400, gap_ms=180, word_ms=1200):
    """Simplified end times of characters for a stream of words."""
    chars, t = [], 0
    for w, wd in enumerate(words):
        for i, ch in enumerate(wd):
            t += char_ms
            chars.append({'ch': ch, 'w': w, 'end': t})
            t += gap_ms
        t += word_ms
    return chars
