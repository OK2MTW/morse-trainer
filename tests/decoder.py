# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/decoder.js (VK D3, 0.11.3) – adaptive decoder of keyed tones.
When decoder.js changes, update this copy too (test_decoder.py checks the constants and shared vectors)."""
import math
import re
from pathlib import Path

DECODER_JS = (Path(__file__).resolve().parent.parent / 'web/js/decoder.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = ([\d.]+);', DECODER_JS)}

ALPHA = CONSTS['DEC_ALPHA']
RATIO_LO = CONSTS['DEC_RATIO_LO']
RATIO_HI = CONSTS['DEC_RATIO_HI']
GAP_IN_LO = CONSTS['DEC_GAP_IN_LO']
GAP_IN_HI = CONSTS['DEC_GAP_IN_HI']
CHAR_GAP_LO = CONSTS['DEC_CHAR_GAP_LO']
CHAR_GAP_HI = CONSTS['DEC_CHAR_GAP_HI']
WORD_GAP = CONSTS['DEC_WORD_GAP']
FIX_DOTS = int(CONSTS['DEC_FIX_DOTS'])
INIT_N = int(CONSTS['DEC_INIT_N'])
SPLIT = CONSTS['DEC_SPLIT']
WIN = int(CONSTS['DEC_WIN'])
GAP_SPLIT = CONSTS['DEC_GAP_SPLIT']
WORD_SPLIT = CONSTS['DEC_WORD_SPLIT']
IN_MAX = CONSTS['DEC_IN_MAX']
WORD_MID = CONSTS['DEC_WORD_MID']
IN_ONE = CONSTS['DEC_IN_ONE']
DOT, DASH = '.', '-'


def _median(a):
    a = sorted(a)
    n = len(a)
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2


def initial_dot(tones, wpm):
    """Starting estimate of the dot (ms) from the first INIT_N tones, so that the set speed does not have to match.
    Known elements decide directly; otherwise the lengths of tones split into two groups with the least spread
    (log domain) whose medians differ ≥ SPLIT; one group only (e.g. EISH, TMO) → the shortest gaps (≈ 1 unit
    inside a character) tell whether those are dots or dashes. Nothing to go by → the set speed."""
    head = tones[:INIT_N]
    known = [t['end'] - t['start'] if t.get('el') == DOT else (t['end'] - t['start']) / 3
             for t in head if t.get('el')]
    if known:
        return _median(known)
    lens = sorted(max(1.0, t['end'] - t['start']) for t in head)
    if not lens:
        return 1200 / wpm
    # two groups with the least spread in the log domain (Otsu); accepted when their medians differ ≥ SPLIT
    lg = [math.log(x) for x in lens]
    best, at = None, None
    for i in range(1, len(lg)):
        a, b = lg[:i], lg[i:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        v = sum((x - ma) ** 2 for x in a) + sum((x - mb) ** 2 for x in b)
        if best is None or v < best:
            best, at = v, i
    if at is not None and _median(lens[at:]) >= SPLIT * _median(lens[:at]):
        return (_median(lens[:at]) + _median(lens[at:]) / 3) / 2
    m = _median(lens)
    gaps = sorted(head[i]['start'] - head[i - 1]['end'] for i in range(1, len(head)))
    if gaps:
        g = gaps[0] if len(gaps) < 3 else _median(gaps[:max(1, len(gaps) // 3)])
        return m if m < 2 * g else m / 3
    u = 1200 / wpm
    return m if m < 2 * u else m / 3


def _split(vals):
    """Sorted vals split into two groups with the least spread in the log domain (Otsu, prefix sums) →
    (lower group, upper group), or None when there are fewer than 2 values."""
    a = sorted(max(1.0, v) for v in vals)
    n = len(a)
    if n < 2:
        return None
    lg = [math.log(x) for x in a]
    s1, s2 = [0.0], [0.0]
    for x in lg:
        s1.append(s1[-1] + x)
        s2.append(s2[-1] + x * x)

    def sse(i, j):
        return s2[j] - s2[i] - (s1[j] - s1[i]) ** 2 / (j - i)
    best = min(range(1, n), key=lambda i: sse(0, i) + sse(i, n))
    return a[:best], a[best:]


def _apart(grp, ratio):
    """Medians of two groups (lower, upper) when the medians differ ≥ ratio, otherwise None."""
    if not grp:
        return None
    lo, hi = _median(grp[0]), _median(grp[1])
    if hi >= ratio * lo:
        return lo, hi
    return None


def mark_threshold(lens):
    """Dot/dash threshold (ms) from the lengths of neighbouring tones, None = one group only (e.g. EISH)."""
    m = _apart(_split(lens), SPLIT)
    return math.sqrt(m[0] * m[1]) if m else None


def gap_thresholds(gaps, mid):
    """(inside/between characters, between characters/words) thresholds in ms from the neighbouring gaps, None =
    too few gaps (the running estimates decide). Top down: gaps inside characters against the rest, then the rest
    split into gaps between characters and words by their own ratio (a hand may keep long gaps between characters
    against its tones – Farnsworth-like). mid = the dot/dash threshold from the tone lengths (≈ 1.7 units) only tells
    whether a group can be gaps inside characters (< IN_MAX × mid; otherwise e.g. E T E) and, when the gaps between
    characters and words cannot be told apart by their ratio, whether the long group is words (≥ WORD_MID × mid)."""
    if len(gaps) < 2:
        return None
    grp = _split(gaps)
    m = _apart(grp, GAP_SPLIT)
    if not m:
        # one group only: gaps inside characters when clearly short, otherwise between characters (E T E)
        md = _median(gaps)
        t1 = md * GAP_SPLIT if md < IN_ONE * mid else md / GAP_SPLIT
        return t1, max(WORD_MID * mid, t1 * WORD_GAP)
    a, b = m
    if a >= IN_MAX * mid:   # no gaps inside characters: between characters | words
        return a / GAP_SPLIT, math.sqrt(a * b)
    mb = _apart(_split(grp[1]), WORD_SPLIT)
    if mb:                  # inside | between characters | words
        return math.sqrt(a * mb[0]), math.sqrt(mb[0] * mb[1])
    # the upper group is one kind: between characters, or words far apart (then the lower group holds both the
    # gaps inside and between characters)
    ma = _apart(_split(grp[0]), WORD_SPLIT)
    if ma and b >= WORD_MID * mid and b >= WORD_SPLIT * ma[1]:
        return math.sqrt(ma[0] * ma[1]), math.sqrt(ma[1] * b)
    return math.sqrt(a * b), max(b * WORD_GAP, WORD_MID * mid)


class DecoderState:
    """Running estimates in ms: dot, dash, gap inside a character (g1) and between characters (g3)."""

    def __init__(self, u):
        self.dot, self.dash, self.g1, self.g3 = u, 3 * u, u, 3 * u
        self.n_mark = 0
        self.n_gap = 0

    def _alpha(self, n):
        # warm-up: the prior from the set speed counts as one observation, then the moving average
        return max(ALPHA, 1 / (n + 2))

    def mark(self, ms, el=None):
        """Classifies one tone (el given = known element of an automatic keyer) and updates the estimates."""
        if el is None:
            el = DOT if ms < math.sqrt(self.dot * self.dash) else DASH
        a = self._alpha(self.n_mark)
        self.n_mark += 1
        if el == DOT:
            self.dot += a * (ms - self.dot)
        else:
            self.dash += a * (ms - self.dash)
        mid = math.sqrt(self.dot * self.dash)
        r = self.dash / self.dot
        if r < RATIO_LO or r > RATIO_HI:
            half = math.sqrt(min(RATIO_HI, max(RATIO_LO, r)))
            self.dot, self.dash = mid / half, mid * half
        return el

    def mid(self):
        return math.sqrt(self.dot * self.dash)

    def gap(self, ms, kind=None):
        """0 = inside a character, 1 = between characters, 2 = between words (kind given = decided from the
        neighbouring gaps, only updates the estimates)."""
        if kind is None:
            kind = 0 if ms < math.sqrt(self.g1 * self.g3) else (1 if ms < self.g3 * WORD_GAP else 2)
        if kind == 0:
            self.g1 += self._alpha(self.n_gap) * (ms - self.g1)
            self.n_gap += 1
        elif kind == 1:
            self.g3 += ALPHA * (ms - self.g3)
        self.g1 = min(GAP_IN_HI * self.dot, max(GAP_IN_LO * self.dot, self.g1))
        self.g3 = min(CHAR_GAP_HI * self.dot, max(CHAR_GAP_LO * self.g1, self.g3))
        return kind

    def unit(self):
        return (self.dot + self.dash / 3) / 2


def decode_tones(tones, wpm, morse):
    """tones = [{start, end, el?}] in ms, time order; el = known element (automatic keyer), missing/None = classify
    by length (straight key, bug dashes – as the other station hears it). Returns
    {text, codes, chars: [{ch, code, i0, i1}], marks: [el per tone], gaps: [kind per tone, None for the first],
    fixes, dot, dash, g1, g3, wpm}."""
    by_code = {}
    for ch, code in morse.items():
        by_code.setdefault(code, ch)
    st = DecoderState(initial_dot(tones, wpm))
    chars, marks, gaps = [], [], []
    fixes = 0
    code, i0 = '', 0
    fix_re = re.compile(r'^\.{%d,}$' % FIX_DOTS)

    def flush(i1):
        nonlocal code, fixes
        if not code:
            return
        if fix_re.match(code):
            fixes += 1
            # error sign: drops the word in progress, or the previous word right after a word gap
            while chars and chars[-1]['ch'] == ' ':
                chars.pop()
            while chars and chars[-1]['ch'] != ' ':
                chars.pop()
        else:
            chars.append({'ch': by_code.get(code, '*'), 'code': code, 'i0': i0, 'i1': i1})
        code = ''

    # the rhythm of the hand from the neighbourhood (WIN tones / gaps on each side): it is learned from all the
    # data around, not only from what the decoder has already accepted (a self-locking estimate read a hand with
    # longer gaps inside characters as T/E only – validation #31)
    lens = [t['end'] - t['start'] for t in tones]
    gms = [tones[i]['start'] - tones[i - 1]['end'] for i in range(1, len(tones))]
    prev_end = None
    for i, tn in enumerate(tones):
        if prev_end is None:
            gaps.append(None)
        else:
            g0 = min(max(0, i - 1 - WIN), max(0, len(gms) - 2 * WIN - 1))
            thr = gap_thresholds(gms[g0:g0 + 2 * WIN + 1], st.mid())
            ms = tn['start'] - prev_end
            kind = st.gap(ms, None if thr is None else (0 if ms < thr[0] else (1 if ms < thr[1] else 2)))
            gaps.append(kind)
            if kind:
                flush(i - 1)
                i0 = i
                if kind == 2 and chars and chars[-1]['ch'] != ' ':
                    chars.append({'ch': ' ', 'code': ' ', 'i0': i, 'i1': i - 1})
        el = tn.get('el')
        if not el:
            m0 = min(max(0, i - WIN), max(0, len(lens) - 2 * WIN - 1))
            thr = mark_threshold(lens[m0:m0 + 2 * WIN + 1])
            if thr is not None:
                el = DOT if lens[i] < thr else DASH
        el = st.mark(lens[i], el)
        marks.append(el)
        code += el
        prev_end = tn['end']
    flush(len(tones) - 1)
    while chars and chars[-1]['ch'] == ' ':
        chars.pop()
    text = ''.join(c['ch'] for c in chars)
    return {
        'text': text, 'codes': [c['code'] for c in chars], 'chars': chars, 'marks': marks, 'gaps': gaps,
        'fixes': fixes, 'dot': st.dot, 'dash': st.dash, 'g1': st.g1, 'g3': st.g3, 'wpm': 1200 / st.unit(),
    }
