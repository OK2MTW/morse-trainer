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
MACH_SPLIT = CONSTS['DEC_MACH_SPLIT']
MACH_WIN = int(CONSTS['DEC_MACH_WIN'])
MACH_WORD = CONSTS['DEC_MACH_WORD']
MACH_SEP = CONSTS['DEC_MACH_SEP']
MACH_LOOK = int(CONSTS['DEC_MACH_LOOK'])
MACH_WORD_LO = CONSTS['DEC_MACH_WORD_LO']
MACH_WORD_HI = CONSTS['DEC_MACH_WORD_HI']
MACH_GAPS = int(CONSTS['DEC_MACH_GAPS'])
MACH_MIN = int(CONSTS['DEC_MACH_MIN'])
MACH_SD = CONSTS['DEC_MACH_SD']
MACH_IN_N = int(CONSTS['DEC_MACH_IN_N'])
MACH_IN_LO = CONSTS['DEC_MACH_IN_LO']
MACH_IN_HI = CONSTS['DEC_MACH_IN_HI']
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


def machine_dot(lens, gaps, hint):
    """Dot length (ms) of a machine stream (0.14.0, HW keyer) from neighbouring tone lengths and gaps: two groups
    → the median of the shorter one; one group: a gap < half the length = inside a character → dashes, otherwise
    the hint (the last known dot) decides."""
    m = _apart(_split(lens), MACH_SPLIT)
    if m:
        return m[0]
    if not lens:
        return hint
    md = _median(lens)
    if gaps and min(gaps) < md / MACH_SPLIT:
        return md / 3
    return md if md < MACH_SPLIT * hint else md / 3


def inner_gap(gaps, u):
    """0.15.4: the gap inside a character (ms) from neighbouring gaps < MACH_SPLIT dots (late key events make tones
    longer and gaps shorter); fewer than MACH_IN_N → u, kept within MACH_IN_LO–HI × u."""
    g = [x for x in gaps if x < MACH_SPLIT * u]
    if len(g) < MACH_IN_N:
        return u
    return min(MACH_IN_HI * u, max(MACH_IN_LO * u, _median(g)))


def machine_tones(tones, hint):
    """Tones of a machine stream with known elements: {**tone, el, u} (u = the local dot in ms); the dot from
    earlier tones and at most MACH_LOOK tones ahead (0.15.4: older decisions do not change as the record grows)."""
    lens = [t['end'] - t['start'] for t in tones]
    gms = [tones[i]['start'] - tones[i - 1]['end'] for i in range(1, len(tones))]
    n = 2 * MACH_WIN + 1
    u = hint
    out = []
    for i, tn in enumerate(tones):
        m1 = min(len(lens), i + MACH_LOOK + 1)
        m0 = max(0, m1 - n)
        u = machine_dot(lens[m0:m1], gms[m0:m1 - 1], u)
        g = inner_gap(gms[m0:m1 - 1], u)
        out.append({**tn, 'el': DOT if lens[i] < MACH_SPLIT * u else DASH, 'u': u, 'g': g})
    return out


def machine_word_gap(units, start=None, learned_only=False):
    """Threshold between characters / words (in dots) from earlier human gaps of a machine stream (in dots): two
    groups in the log domain (k-means from 3 and 7 dots), threshold between them shifted by the group sizes
    (Bayes with a common spread), kept within MACH_WORD_LO–HI;
    fewer than MACH_MIN gaps or no two clear groups → start (0.16.3: learned earlier, else MACH_WORD; learned_only → None)."""
    fb = None if learned_only else min(MACH_WORD_HI, max(MACH_WORD_LO, start or MACH_WORD))
    if len(units) < MACH_MIN:
        return fb
    h = [math.log(x) for x in units]
    a, b = math.log(3), math.log(7)
    A, B = [], []
    for _ in range(15):
        A = [x for x in h if abs(x - a) <= abs(x - b)]
        B = [x for x in h if abs(x - a) > abs(x - b)]
        if A:
            a = sum(A) / len(A)
        if B:
            b = sum(B) / len(B)
    if len(A) < 2 or not B or b - a < math.log(MACH_SEP):
        return fb
    s2 = max((sum((x - a) ** 2 for x in A) + sum((x - b) ** 2 for x in B)) / len(h), MACH_SD ** 2)
    return min(MACH_WORD_HI, max(MACH_WORD_LO, math.exp((a + b) / 2 + s2 * math.log(len(A) / len(B)) / (b - a))))


def machine_gap_kind(ms, u, word):
    """Kind of a gap of a machine stream: inside a character (< MACH_SPLIT dots), between characters (< word
    dots) or words."""
    if ms < MACH_SPLIT * u:
        return 0
    return 1 if ms < word * u else 2


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


def decode_tones(tones, wpm, morse, machine=False, dot=None, word=None, model=False, gap_prior=None):
    """tones = [{start, end, el?}] in ms, time order; el = known element (automatic keyer), missing/None = classify
    by length (straight key, bug dashes – as the other station hears it). Returns
    {text, codes, chars: [{ch, code, i0, i1}], marks: [el per tone], gaps: [kind per tone, None for the first],
    fixes, dot, dash, g1, g3, wpm}. word = the word threshold learned earlier on this device (0.16.3)."""
    word_hint = word or MACH_WORD
    if machine:
        tones = machine_tones(tones, dot or 1200 / wpm)
    pre, conf, gm = (model_gaps(machine_units(tones), gap_prior) if machine and model else (None, None, None))
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
    human, units, words = [], [], []
    prev_end = None
    for i, tn in enumerate(tones):
        if prev_end is None:
            gaps.append(None)
            if machine:
                units.append(None)
                words.append(None)
        else:
            g0 = min(max(0, i - 1 - WIN), max(0, len(gms) - 2 * WIN - 1))
            near = gms[g0:g0 + 2 * WIN + 1]
            ms = tn['start'] - prev_end
            if machine:
                tu = (tn['u'] + tones[i - 1]['u']) / 2
                g = (tn['g'] + tones[i - 1]['g']) / 2
                u = (tu + g) / 2
                x = (ms + (tu - g) / 2) / u
                word = machine_word_gap(human[-MACH_GAPS:], word_hint)
                kind = st.gap(ms, pre[i] if pre else machine_gap_kind(x, 1, word))
                units.append(x)
                words.append(word)
                if x >= MACH_SPLIT:
                    human.append(x)
            else:
                thr = gap_thresholds(near, st.mid())
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
        'fixes': fixes, 'units': units, 'words': words, 'dot': st.dot, 'dash': st.dash, 'g1': st.g1, 'g3': st.g3, 'wpm': 1200 / st.unit(),
        'tones': tones, 'conf': conf, 'gm': gm,
    }


DIAG_WORDS = int(CONSTS['DEC_DIAG_WORDS'])
DIAG_NEAR = CONSTS['DEC_DIAG_NEAR']


def _near(x, thr):
    return abs(math.log(x / thr)) < math.log(DIAG_NEAR)


def gap_diagnostics(dec, morse, n_words=DIAG_WORDS):
    """0.15.4: the last n_words words of a decoded machine stream gap by gap (port of gapDiagnostics)."""
    tones, gaps, units, words = dec['tones'], dec['gaps'], dec['units'], dec['words']
    if not tones or len(units) != len(tones):
        return None
    by_code = {}
    for ch, code in morse.items():
        by_code.setdefault(code, ch)
    start, seen = 0, 0
    for i in range(len(gaps) - 1, 0, -1):
        if gaps[i] == 2:
            seen += 1
            if seen >= n_words:
                start = i
                break
    rows, row = [], None
    for i in range(start, len(tones)):
        if i == start or gaps[i] > 0:
            row = {'code': '', 'ch': None, 'before': None if i == start == 0 else units[i],
                   'kind': None if i == 0 else gaps[i], 'word': words[i], 'close': False, 'in_max': None,
                   'in_close': False}
            if row['before'] is not None:
                row['close'] = _near(row['before'], MACH_SPLIT) or _near(row['before'], row['word'])
            rows.append(row)
        else:
            row['in_max'] = max(row['in_max'] or 0, units[i])
            row['in_close'] = _near(row['in_max'], MACH_SPLIT)
        row['code'] += tones[i]['el']
    fix = re.compile(r'^\.{%d,}$' % FIX_DOTS)
    for r in rows:
        r['ch'] = '' if fix.match(r['code']) else by_code.get(r['code'])
    last = tones[-1]
    dot = (last['u'] + last['g']) / 2
    ws = [w for w in words if w is not None]
    return {'rows': rows, 'dot': dot, 'wpm': 1200 / dot, 'split': MACH_SPLIT, 'word': ws[-1] if ws else MACH_WORD}


def learned_word_gap(dec):
    """Port of learnedWordGap (0.16.3): the threshold learned from the human gaps of a decoding, or None."""
    h = [x for x in dec.get('units') or [] if x is not None and x >= MACH_SPLIT]
    return machine_word_gap(h[-MACH_GAPS:], learned_only=True)



# --- 1.1 K2: a gap model of the hand (Bell 1977: probabilities of gap classes instead of a threshold) ---------------
# Machine stream only: a gap < MACH_SPLIT dots is inside a character (the keyer makes it); the human gaps (≥ MACH_SPLIT)
# are a mixture of two log-normal classes – between characters / between words. Prior = the norm 3/7 with pseudocounts
# (cold start: a few gaps already move it), learned by EM (MAP) over the whole over plus what was learned in the earlier
# overs of the session (the model of the other station's hand). Every gap gets the probability of its class.
# Port of decoder.js GapModel / modelGaps (1.1 K2 part 2) – the constants come from decoder.js.
GM_NORM = (CONSTS['DEC_GM_CHAR'], CONSTS['DEC_GM_WORD'])   # prior means (dots) between characters / words
GM_SD = (CONSTS['DEC_GM_SD'], CONSTS['DEC_GM_SD'])          # prior spread (log)
GM_SD_MIN = CONSTS['DEC_GM_SD_MIN']
GM_N0 = CONSTS['DEC_GM_NPRIOR']
GM_KEEP = CONSTS['DEC_GM_KEEP']
GM_SEP = CONSTS['DEC_GM_SEP']
GM_ITER = int(CONSTS['DEC_GM_ITER'])
GM_W_WORD = CONSTS['DEC_GM_W_WORD']
GM_W_N = CONSTS['DEC_GM_W_N']
GM_WIN = int(CONSTS['DEC_GM_WIN'])
GM_SHRINK = CONSTS['DEC_GM_SHRINK']
GM_MIN = int(CONSTS['DEC_GM_MIN'])


class GapModel:
    """Two-class log-normal mixture of human gaps (in dots). prior = learned() of an earlier over or None (= norm)."""

    def __init__(self, prior=None):
        if prior:
            self.m0, self.s0, self.n0 = list(prior['m']), list(prior['s']), [max(1.0, n) for n in prior['n']]
        else:
            self.m0 = [math.log(v) for v in GM_NORM]
            self.s0, self.n0 = list(GM_SD), [GM_N0, GM_N0]
        self.m, self.s, self.w = list(self.m0), list(self.s0), [0.75, 0.25]
        self.nk = [0.0, 0.0]

    def _resp(self, h):
        p = [self.w[c] / self.s[c] * math.exp(-0.5 * ((h - self.m[c]) / self.s[c]) ** 2) for c in (0, 1)]
        t = p[0] + p[1]
        if t <= 0:                       # far outside both: the nearer mean
            return [1.0, 0.0] if abs(h - self.m[0]) < abs(h - self.m[1]) else [0.0, 1.0]
        return [p[0] / t, p[1] / t]

    def _start(self, hs):
        # EM from a split of the data, not from the prior (from 3/7 a slow hand's gaps between characters around 6–8
        # dots pulled the word class down – a local optimum): Otsu – the split with the largest between-class variance
        if len(hs) < GM_MIN:
            return
        h = sorted(hs)
        n, tot = len(h), sum(h)
        best, k, acc = -1.0, 0, 0.0
        for i in range(1, n):
            acc += h[i - 1]
            a, b = acc / i, (tot - acc) / (n - i)
            v = i * (n - i) * (b - a) ** 2
            if v > best:
                best, k = v, i
        a, b = sum(h[:k]) / k, sum(h[k:]) / (n - k)
        if b - a >= math.log(GM_SEP):
            self.m, self.w = [a, b], [k / n, (n - k) / n]

    def fit(self, xs):
        """EM over the human gaps of an over (time order) with a slowly changing tempo of the hand: every gap has an
        offset (log) = the smoothed residual of its neighbours (±GM_WIN gaps), shrunk towards 0 (Bell: a model of the
        speed change; the hand drifts during a session – globally the classes overlap, locally not)."""
        hs = [math.log(x) for x in xs]
        n = len(hs)
        self.hs, self.off = hs, [0.0] * n
        self._start(hs)
        reach = 3 * GM_WIN
        for it in range(GM_ITER if hs else 0):
            zs = [h - o for h, o in zip(hs, self.off)]
            rs = [self._resp(z) for z in zs]
            vs, ns = 0.0, 0.0
            for c in (0, 1):
                nk = sum(r[c] for r in rs)
                tot = self.n0[c] + nk
                m = (self.n0[c] * self.m0[c] + sum(r[c] * z for r, z in zip(rs, zs))) / tot
                # the spread has its own prior (not inflated by a mean far from the norm) and is common to both
                # classes (a wide word class took the slow gaps between characters – self-reinforcing)
                vs += self.n0[c] * self.s0[c] ** 2 + sum(r[c] * (z - m) ** 2 for r, z in zip(rs, zs))
                ns += tot
                self.m[c], self.nk[c] = m, nk
            sd = max(GM_SD_MIN, math.sqrt(vs / ns))
            self.s = [sd, sd]
            if self.m[1] - self.m[0] < math.log(GM_SEP):
                mid = (self.m[0] + self.m[1]) / 2
                self.m = [mid - math.log(GM_SEP) / 2, mid + math.log(GM_SEP) / 2]
            # the share of word gaps has its own prior (a text has ~1 word gap per 3–4 gaps between characters);
            # with overlapping classes (a beginner) the EM alone let the word class grow to a half
            pw = [1 - GM_W_WORD, GM_W_WORD]
            t = GM_W_N + self.nk[0] + self.nk[1]
            self.w = [(GM_W_N * pw[c] + self.nk[c]) / t for c in (0, 1)]
            if n >= GM_MIN and it >= 2:
                res = [h - (r[0] * self.m[0] + r[1] * self.m[1]) for h, r in zip(hs, rs)]
                off = []
                for i in range(n):
                    a, b = 0.0, GM_SHRINK
                    for j in range(max(0, i - reach), min(n, i + reach + 1)):
                        k = math.exp(-0.5 * ((i - j) / GM_WIN) ** 2)
                        a += k * res[j]
                        b += k
                    off.append(a / b)
                self.off = off
        return self

    def word_probs(self):
        """P(word gap) of every human gap of the fitted over (with its local tempo)."""
        return [self._resp(h - o)[1] for h, o in zip(self.hs, self.off)]

    def word_prob(self, x):
        """P(word gap | x dots) for a human gap at the mean tempo."""
        return self._resp(math.log(x))[1]

    def learned(self):
        """The model for the next over: means, spreads and counts (capped – the hand may change)."""
        n = [self.n0[c] + self.nk[c] for c in (0, 1)]
        k = min(1.0, GM_KEEP / sum(n))            # capped in proportion (capping each class equalised the weights)
        return {'m': list(self.m), 's': list(self.s), 'n': [k * v for v in n]}


def machine_units(tones):
    """Gaps of a machine stream (output of machine_tones) in local dots, as decode_tones computes them; None first."""
    out = [None]
    for i in range(1, len(tones)):
        tn, pv = tones[i], tones[i - 1]
        tu = (tn['u'] + pv['u']) / 2
        g = (tn['g'] + pv['g']) / 2
        u = (tu + g) / 2
        out.append((tn['start'] - pv['end'] + (tu - g) / 2) / u)
    return out


def model_gaps(units, prior=None):
    """1.1 K2: the gap classes of one over from the gap model → (kinds, conf, model). kinds[i] = 0/1/2 (None first),
    conf[i] = the probability of the chosen class."""
    human = [x for x in units[1:] if x >= MACH_SPLIT]
    gm = GapModel(prior).fit(human)
    probs = iter(gm.word_probs())
    kinds, conf = [None], [None]
    for x in units[1:]:
        if x < MACH_SPLIT:
            kinds.append(0)
            conf.append(1.0)
        else:
            p = next(probs)
            kinds.append(2 if p >= 0.5 else 1)
            conf.append(max(p, 1 - p))
    return kinds, conf, gm
