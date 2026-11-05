# SPDX-License-Identifier: EUPL-1.2
"""Python port logiky trenéra z web/js/drill.js (pro simulace a testy – na Pi není JS engine).

Konstanty a tabulky se čtou přímo z JS souborů, aby se port nerozešel s originálem.
Při změně drill.js upravit i tuto kopii (test_trainer.py hlídá konstanty a tabulky).
"""
import math
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRILL_JS = (ROOT / 'web/js/drill.js').read_text(encoding='utf-8')
CHARSET_JS = (ROOT / 'web/js/charset.js').read_text(encoding='utf-8')

CONSTS = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'export const ([A-Z_]+) = ([0-9.]+);', DRILL_JS)}
ADVANCE_WINDOW = int(CONSTS['ADVANCE_WINDOW'])
ADVANCE_ACCURACY = CONSTS['ADVANCE_ACCURACY']
NEW_MIN_N = int(CONSTS['NEW_MIN_N'])
NEW_ACCURACY = CONSTS['NEW_ACCURACY']
NEW_TTR_RATIO = CONSTS['NEW_TTR_RATIO']
PRIOR_N = CONSTS['PRIOR_N']
PRIOR_MIN_N = CONSTS['PRIOR_MIN_N']
DEFAULT_ERR = CONSTS['DEFAULT_ERR']
DISCRIM_TRIALS = int(CONSTS['DISCRIM_TRIALS'])
TREND_MIN_N = CONSTS['TREND_MIN_N']
TREND_MIN_CUR = CONSTS['TREND_MIN_CUR']
MIN_WPM = int(CONSTS['MIN_WPM'])
DISCRIM_SIMILAR_FROM = int(CONSTS['DISCRIM_SIMILAR_FROM'])
MAINTAIN_MIN = CONSTS['MAINTAIN_MIN']
MAINTAIN_MAX = CONSTS['MAINTAIN_MAX']
MASTER_MIN_N = CONSTS['MASTER_MIN_N']
MASTER_ACC = CONSTS['MASTER_ACC']
SCATTER_MIN_CHARS = int(CONSTS['SCATTER_MIN_CHARS'])
BAND_LO = CONSTS['BAND_LO']
BAND_HI = CONSTS['BAND_HI']
DIFF_WINDOW = int(CONSTS['DIFF_WINDOW'])
DIFF_EVERY = int(CONSTS['DIFF_EVERY'])
DIFF_STEP = CONSTS['DIFF_STEP']
DIFF_MIN = CONSTS['DIFF_MIN']
DIFF_MAX = CONSTS['DIFF_MAX']
MAINTAIN_EASY_MAX = CONSTS['MAINTAIN_EASY_MAX']
TTR_STABLE_RATIO = CONSTS['TTR_STABLE_RATIO']
STABLE_REL_MIN = int(CONSTS['STABLE_REL_MIN'])
NEW_SHARE_MAX = CONSTS['NEW_SHARE_MAX']
CONF_BONUS = CONSTS['CONF_BONUS']
CONF_CAP = CONSTS['CONF_CAP']
GAP_EASE_ACC = CONSTS['GAP_EASE_ACC']
GAP_BACK_ACC = CONSTS['GAP_BACK_ACC']
GAP_EASE_MAX = int(CONSTS['GAP_EASE_MAX'])
GAP_EASE_STEP = int(CONSTS['GAP_EASE_STEP'])
GAP_EVERY = int(CONSTS['GAP_EVERY'])
FW_MIN = int(CONSTS['FW_MIN'])


def _js_str_list(src):
    return [a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", src)]


_koch = re.search(r'KOCH_ORDER = \[(.*?)\];', CHARSET_JS, re.S).group(1)
KOCH_ORDER = _js_str_list(_koch)
_morse = re.search(r'MORSE = Object.fromEntries\(\[(.*?)\]\);', CHARSET_JS, re.S).group(1)
MORSE = {}
for pair in re.findall(r"\[((?:'[^']*'|\"[^\"]*\")), '([.-]+)'\]", _morse):
    MORSE[_js_str_list(pair[0])[0]] = pair[1]


def js_round(x):
    return math.floor(x + 0.5)


def median(arr):
    if not arr:
        return None
    s = sorted(arr)
    m = len(s) >> 1
    return s[m] if len(s) % 2 else js_round((s[m - 1] + s[m]) / 2)


def chars_for_level(level):
    return KOCH_ORDER[:max(2, min(len(KOCH_ORDER), level))]


class Drill:
    def __init__(self, chars, new_char=None, rng=random.random, prior=None):
        self.chars = list(chars)
        self.new_char = new_char
        self.rng = rng
        self.prior = prior or {}
        self.prior_ttr = median([self.prior[c]['ttr'] for c in chars
                                 if c in self.prior and self.prior[c].get('ttr') is not None
                                 and self.prior[c]['n'] >= PRIOR_MIN_N])
        self.trials = []
        self.stats = {c: {'n': 0, 'err': 0, 'ttrs': []} for c in chars}
        self.diff = 1
        self.diff_at = 0
        self.diff_log = []
        self.gap_ease = 0
        self.gap_at = 0
        self.gap_log = []
        self.regulation = True  # jen pro simulace (vypnutí smyčky a)
        self.exclude = set()
        self.conf_n = {c: 0 for c in self.chars}
        for c, p in self.prior.items():
            for x in (p or {}).get('conf') or []:
                if c in self.conf_n:
                    self.conf_n[c] += x.get('n') or 0
                if x.get('ans') in self.conf_n:
                    self.conf_n[x['ans']] += x.get('n') or 0

    def set_exclude(self, lst):
        rest = [c for c in self.chars if c not in lst]
        self.exclude = set(lst) if len(rest) >= 2 else set()

    def regulate(self):
        n = len(self.trials)
        if not self.regulation or n < DIFF_WINDOW:
            return
        acc = sum(1 for t in self.trials[-DIFF_WINDOW:] if t['ok']) / DIFF_WINDOW
        if n - self.diff_at >= DIFF_EVERY:
            d = self.diff
            if acc > BAND_HI:
                d = min(DIFF_MAX, d + DIFF_STEP)
            elif acc < BAND_LO:
                d = max(DIFF_MIN, d - DIFF_STEP)
            if d != self.diff:
                self.diff = js_round(d * 100) / 100
                self.diff_at = n
                self.diff_log.append([n, self.diff])
        if n - self.gap_at >= GAP_EVERY:
            g = self.gap_ease
            if acc < GAP_EASE_ACC and self.diff <= DIFF_MIN + 1e-9:
                g = min(GAP_EASE_MAX, g + 1)
            elif acc >= GAP_BACK_ACC:
                g = max(0, g - 1)
            if g != self.gap_ease:
                self.gap_ease = g
                self.gap_at = n
                self.gap_log.append([n, g])

    def lesson_fwpm(self, fwpm):
        return max(FW_MIN, min(fwpm, fwpm - GAP_EASE_STEP * self.gap_ease)) if self.gap_ease else fwpm

    def prior_err(self, c):
        p = self.prior.get(c)
        if p and p['n'] >= PRIOR_MIN_N and p.get('acc') is not None:
            return 1 - p['acc']
        return DEFAULT_ERR

    def weight(self, c):
        if c in self.exclude:
            return 0
        s = self.stats[c]
        recent = [t for t in self.trials if t['ch'] == c][-10:]
        errs = sum(1 for t in recent if not t['ok'])
        err = (errs + PRIOR_N * self.prior_err(c)) / (len(recent) + PRIOR_N)
        allm = median([t['ttr'] for t in self.trials if t['ok'] and t['ttr'] is not None and t['ch'] != self.new_char])
        mine = median(s['ttrs'][-10:])
        slow = 1
        p = self.prior.get(c)
        if allm and mine:
            slow = mine / allm
        elif self.prior_ttr and p and p.get('ttr') and p['n'] >= PRIOR_MIN_N:
            slow = p['ttr'] / self.prior_ttr
        slow = min(2, max(0.5, slow))
        w = 1 + 4 * err + 1.5 * (slow - 1) + CONF_BONUS * min(CONF_CAP, self.conf_n.get(c, 0))
        if c == self.new_char:
            w *= 1.8
            if len(self.chars) >= SCATTER_MIN_CHARS and self.trials and self.trials[-1]['ch'] == c:
                w = 0
        last2 = [t['ch'] for t in self.trials[-2:]]
        if len(last2) == 2 and last2[0] == c and last2[1] == c:
            w = 0
        return max(0, w)

    def is_mastered(self, c):
        if c == self.new_char:
            return False
        p = self.prior.get(c)
        if not p or p['n'] < MASTER_MIN_N or p.get('acc') is None or p['acc'] < MASTER_ACC:
            return False
        recent = [t for t in self.trials if t['ch'] == c][-10:]
        return sum(1 for t in recent if not t['ok']) < 2

    def mix_weights(self):
        ws = [self.weight(c) ** self.diff for c in self.chars]
        m = [self.is_mastered(c) for c in self.chars]
        s_m = sum(w for w, x in zip(ws, m) if x)
        s_a = sum(w for w, x in zip(ws, m) if not x)
        if s_m > 0 and s_a > 0:
            share = s_m / (s_m + s_a)
            easy = max(0, min(1, (1 - self.diff) / (1 - DIFF_MIN)))
            mx = MAINTAIN_MAX + easy * (MAINTAIN_EASY_MAX - MAINTAIN_MAX)
            goal = min(mx, max(MAINTAIN_MIN, share))
            if goal != share:
                f = (goal * s_a) / ((1 - goal) * s_m)
                ws = [w * f if x else w for w, x in zip(ws, m)]
        if self.new_char in self.chars:
            k = self.chars.index(self.new_char)
            rest = sum(ws) - ws[k]
            if ws[k] > 0 and rest > 0 and ws[k] / (ws[k] + rest) > NEW_SHARE_MAX:
                ws[k] = NEW_SHARE_MAX * rest / (1 - NEW_SHARE_MAX)
        return ws

    def next(self):
        ws = self.mix_weights()
        r = self.rng() * sum(ws)
        for c, w in zip(self.chars, ws):
            r -= w
            if r <= 0:
                return c
        return self.chars[-1]

    def record(self, ch, ans, ttr, repeats=0, timeout=False):
        ok = not timeout and ans == ch
        self.trials.append({'ch': ch, 'ans': ans, 'ok': ok, 'ttr': ttr, 'repeats': repeats, 'timeout': timeout})
        s = self.stats[ch]
        s['n'] += 1
        if not ok:
            s['err'] += 1
        if ok and ttr is not None:
            s['ttrs'].append(ttr)
        self.regulate()
        return ok

    def recent_accuracy(self):
        if len(self.trials) < ADVANCE_WINDOW:
            return None
        w = self.trials[-ADVANCE_WINDOW:]
        return sum(1 for t in w if t['ok']) / len(w)

    def stable_ttrs(self, a, b):
        def rel(ts):
            out = []
            for t in ts:
                p = self.prior.get(t['ch'])
                if t['ok'] and t['ttr'] is not None and t['ch'] != self.new_char and p and p.get('ttr') \
                        and p['n'] >= PRIOR_MIN_N:
                    out.append(t['ttr'] * 1000 / p['ttr'])
            return out
        ra, rb = rel(a), rel(b)
        if len(ra) >= STABLE_REL_MIN and len(rb) >= STABLE_REL_MIN:
            return median(ra), median(rb)
        raw = lambda ts: median([t['ttr'] for t in ts if t['ok'] and t['ttr'] is not None])
        return raw(a), raw(b)

    def advance_check(self):
        r = {'ok': False, 'reason': None, 'recent': self.recent_accuracy(), 'newN': 0,
             'newAcc': None, 'newTtr': None, 'othersTtr': None}
        if r['recent'] is None:
            r['reason'] = 'few'
            return r
        if r['recent'] < ADVANCE_ACCURACY:
            r['reason'] = 'acc'
            return r
        win = self.trials[-ADVANCE_WINDOW:]
        half = len(win) >> 1
        t1, t2 = self.stable_ttrs(win[:half], win[half:])
        r['ttrRatio'] = js_round(t2 / t1 * 100) / 100 if t1 and t2 else None
        if r['ttrRatio'] is not None and r['ttrRatio'] > TTR_STABLE_RATIO:
            r['reason'] = 'ttrUnstable'
            return r
        s = self.stats.get(self.new_char) if self.new_char else None
        if s:
            r['newN'] = s['n']
            if s['n'] < NEW_MIN_N:
                r['reason'] = 'newFew'
                return r
            r['newAcc'] = (s['n'] - s['err']) / s['n']
            if r['newAcc'] < NEW_ACCURACY:
                r['reason'] = 'newAcc'
                return r
            r['newTtr'] = median(s['ttrs'])
            r['othersTtr'] = median([t['ttr'] for t in self.trials
                                     if t['ok'] and t['ch'] != self.new_char and t['ttr'] is not None])
            if (r['newTtr'] is not None and r['othersTtr'] is not None
                    and r['newTtr'] > NEW_TTR_RATIO * r['othersTtr']):
                r['reason'] = 'newSlow'
                return r
        r['ok'] = True
        return r


def trend_arrow(cur, base):
    if not cur or not base or cur.get('acc') is None or base.get('acc') is None:
        return None
    if cur['n'] < TREND_MIN_CUR or base['n'] < TREND_MIN_N:
        return None
    d_acc = cur['acc'] - base['acc']
    ratio = cur['ttr'] / base['ttr'] if cur.get('ttr') and base.get('ttr') else 1
    if d_acc <= -0.1 or (d_acc < 0.05 and ratio >= 1.2):
        return 'down'
    if d_acc >= 0.1 or (d_acc > -0.05 and ratio <= 0.85):
        return 'up'
    return 'flat'


def code_distance(a, b):
    x, y = MORSE.get(a, ''), MORSE.get(b, '')
    prev = list(range(len(y) + 1))
    for i in range(1, len(x) + 1):
        cur = [i]
        for j in range(1, len(y) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if x[i - 1] == y[j - 1] else 1)))
        prev = cur
    return prev[len(y)]


def pick_contrasts(target, known, conf=None, mx=2, set_size=None):
    conf = conf or {}
    set_size = len(KOCH_ORDER) if set_size is None else set_size
    items = [c for c in known if c != target]
    if set_size < DISCRIM_SIMILAR_FROM:
        far = [c for c in items if conf.get(c, 0) > 0 or code_distance(target, c) > 1]
        if far:
            items = far
    items.sort(key=lambda c: (-conf.get(c, 0), code_distance(target, c), -KOCH_ORDER.index(c)))
    return items[:mx]


def discrim_sequence(targets, contrasts, n=DISCRIM_TRIALS, rng=random.random):
    seq = []
    for i in range(n):
        from_t = not contrasts or i % 2 == 0
        lst = targets if from_t else contrasts
        seq.append(lst[(i // (2 if contrasts else 1)) % len(lst)])

    def run_ok(s):
        return all(i < 2 or not (s[i - 1] == c and s[i - 2] == c) for i, c in enumerate(s))

    for _ in range(30):
        for i in range(len(seq) - 1, 0, -1):
            j = math.floor(rng() * (i + 1))
            seq[i], seq[j] = seq[j], seq[i]
        if run_ok(seq):
            break
    return seq
