# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/vo.js (0.16.0 virtual operator of the CW room) – constants are read from the JS."""
import math
import re
from pathlib import Path

from tests import content as C

VO_JS = (Path(__file__).resolve().parent.parent / 'web/js/vo.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const (VO_[A-Z_]+) = ([\d.]+);', VO_JS)}
VO_WPM = int(CONSTS['VO_WPM'])
VO_WPM_MIN = int(CONSTS['VO_WPM_MIN'])
VO_WPM_MAX = int(CONSTS['VO_WPM_MAX'])
VO_QRS = int(CONSTS['VO_QRS'])
VO_TOPICS_MIN = int(CONSTS['VO_TOPICS_MIN'])
VO_TOPICS_MAX = int(CONSTS['VO_TOPICS_MAX'])
VO_TOPICS_PER_OVER = int(CONSTS['VO_TOPICS_PER_OVER'])


def _list(name, src=VO_JS):
    return re.findall(r"'([^']*)'", re.search(name + r" = \[(.*?)\];", src).group(1))


VO_MODES = _list('VO_MODES')
VO_TOPICS = _list('VO_TOPICS')
OVER_ENDS = _list('OVER_ENDS')
PROSIGNS = dict(re.findall(r"'([.-]+)': '(\w+)'", re.search(r'PROSIGNS = \{(.*?)\};', VO_JS).group(1)))
PROSIGN_CODES = {p: c for c, p in PROSIGNS.items()}
QSO = {k: _list('QSO_' + k, C.CONTENT_JS) for k in ('NAMES', 'QTH', 'WX', 'RIG', 'ANT', 'PWR')}
VO_PREFIXES = _list('VO_PREFIXES')
LETTERS = list('ABCDEFGHIJKLMNOPRSTUVWXYZ')
FILLER = ['IS', 'HR', 'NR', 'OP', 'ES']
RST_RE = re.compile(r'^[1-5][1-9N][1-9N]$')
CALL_RE = re.compile(r'^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{3,7}(/[A-Z0-9]{1,3})?$')


def pick(lst, rng):
    return lst[int(rng() * len(lst))]


def looks_like_call(s):
    return bool(CALL_RE.match(s))


def edit_distance(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        p, d[0] = d[0], i
        for k in range(1, len(b) + 1):
            p, d[k] = d[k], min(d[k] + 1, d[k - 1] + 1, p + (a[i - 1] != b[k - 1]))
    return d[len(b)]


def same_call(heard, call_sign):
    return bool(heard) and bool(call_sign) and (
        heard == call_sign or (len(call_sign) >= 4 and edit_distance(heard, call_sign) <= 1))


VO_TOLS = _list('VO_TOLS')
VO_TOL_JOIN = {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", re.search(r'VO_TOL_JOIN = \{(.*?)\};', VO_JS).group(1))}
VO_WORDS = re.findall(r"'([^']*)'", re.search(r'VO_WORDS = \[(.*?)\];', VO_JS, re.S).group(1))
KNOWN = set(VO_WORDS) | set(VO_TOPICS) | set(OVER_ENDS)


def tol_for_step(index):
    return 'mid' if index >= 2 else 'high'


def mend_spacing(text, tol, calls=()):
    tokens = text.split()
    mx = VO_TOL_JOIN.get(tol, 0)
    if not mx:
        return ' '.join(tokens)
    cs = [c for c in calls if c]

    def known(w):
        return w in KNOWN or bool(RST_RE.match(w)) or w in cs
    out = []
    i = 0
    while i < len(tokens):
        n = min(mx, len(tokens) - i)
        while n >= 2:
            part = tokens[i:i + n]
            if not (any('?' in tk for tk in part[:-1]) or any(not _token(tk) for tk in part)):
                q = part[-1][len(_token(part[-1])):]
                word = ''.join(_token(tk) for tk in part)
                if known(word):
                    out.append(word + q)
                    break
            n -= 1
        if n >= 2:
            i += n
            continue
        tk = tokens[i]
        i += 1
        base = _token(tk)
        q = tk[len(base):]
        split = None
        if not known(base):
            for k in range(len(base) - 1, 0, -1):
                a, b = base[:k], base[k:]
                if known(a) and known(b) and len(a) >= 2 and (len(b) >= 2 or b in OVER_ENDS):
                    split = [a, b + q]
                    break
        out.extend(split or [tk])
    return ' '.join(out)


def over_text(chars):
    out = ''.join(f" {PROSIGNS[c['code']]} " if c['code'] in PROSIGNS else c['ch'] for c in chars)
    return ' '.join(out.split())


def over_ended(text):
    words = text.split()
    return bool(words) and words[-1] in OVER_ENDS


def vo_call(rng):
    out = pick(VO_PREFIXES, rng) + str(1 + int(rng() * 9))
    for _ in range(2 + int(rng() * 2)):
        out += pick(LETTERS, rng)
    return out


def persona(rng, year=2026):
    years = 1 + int(rng() * 50)
    return {
        'call': vo_call(rng), 'name': pick(QSO['NAMES'], rng), 'qth': pick(QSO['QTH'], rng),
        'rig': pick(QSO['RIG'], rng), 'ant': pick(QSO['ANT'], rng), 'pwr': pick(QSO['PWR'], rng),
        'wx': pick(QSO['WX'], rng), 'temp': str(int(rng() * 25)),
        'age': str(max(18 + years, 20 + int(rng() * 60))), 'since': str(year - years),
        'qsl': pick(['BURO', 'LOTW', 'EQSL'], rng), 'rst': pick(['599', '579', '589', '5NN'], rng),
    }


def topic_line(topic, p):
    return {
        'RIG': f"RIG HR {p['rig']}", 'ANT': f"ANT {p['ant']}", 'PWR': f"PWR {p['pwr']}W",
        'WX': f"WX {p['wx']} TEMP {p['temp']}C", 'AGE': f"AGE {p['age']} ES HAM SINCE {p['since']}",
    }.get(topic, f"QSL VIA {p['qsl']}")


def _token(tk):
    return tk.rstrip('?')


def _after(tokens, keys):
    for i, tk in enumerate(tokens):
        if _token(tk) not in keys:
            continue
        k = i + 1
        while k < len(tokens) and tokens[k] in FILLER:
            k += 1
        if k < len(tokens) and not tokens[k].endswith('?') and tokens[k] != '=':
            return tokens[k]
    return None


def hear(text, vo_call, user_call=''):
    tokens = text.split()
    plain = [_token(t) for t in tokens]
    h = {'cq': 'CQ' in plain, 'to_vo': any(same_call(_token(t), vo_call) for t in tokens), 'from': None, 'rst': None,
         'name': None, 'qth': None, 'agn': False, 'qrs': False, 'qrq': False, 'asks': [], 'bye': False,
         'end': over_ended(text), 'empty': not tokens}
    if 'DE' in plain:
        de = plain.index('DE')
        if de + 1 < len(plain) and CALL_RE.match(plain[de + 1]):
            h['from'] = plain[de + 1]
    if not h['from'] and user_call:
        h['from'] = next((t for t in plain if same_call(t, user_call)), None)
    if not h['from']:
        h['from'] = next((t for t in plain if CALL_RE.match(t) and not same_call(t, vo_call) and not RST_RE.match(t)),
                         None)
    rst = _after(tokens, ['RST', 'UR'])
    h['rst'] = rst if rst and RST_RE.match(rst) else next((t for t in plain if RST_RE.match(t)), None)
    h['name'] = _after(tokens, ['NAME', 'OP'])
    h['qth'] = _after(tokens, ['QTH'])
    for i, (tk, p) in enumerate(zip(tokens, plain)):
        if tk == '?' or p in ('AGN', 'RPT'):
            h['agn'] = True
        if p == 'QRS':
            h['qrs'] = True
        if p == 'QRQ':
            h['qrq'] = True
        asked = tk.endswith('?') or (i + 1 < len(tokens) and tokens[i + 1] == '?')
        if asked and p in VO_TOPICS and p not in h['asks']:
            h['asks'].append(p)
        if p in ('73', 'SK', 'GB'):
            h['bye'] = True
    return h


def greeting(hour):
    return 'GM' if hour < 12 else ('GA' if hour < 18 else 'GE')


class VirtualOperator:
    def __init__(self, mode='quick', user_call='', rng=None, hour=12, year=2026, wpm=None, tol='off'):
        self.mode = mode if mode in VO_MODES else 'quick'
        self.rng = rng
        self.p = persona(rng, year)
        self.hour = hour
        self.user = user_call or ''
        self.user_name = None
        self.wpm = wpm or VO_WPM
        self.tol = tol if tol in VO_TOL_JOIN else 'off'
        self.phase = 'listen'
        self.last = None
        n = VO_TOPICS_MIN + int(rng() * (VO_TOPICS_MAX - VO_TOPICS_MIN + 1))
        topics = list(VO_TOPICS)
        self.topics = []
        while len(self.topics) < n:
            self.topics.append(topics.pop(int(rng() * len(topics))))

    @property
    def call(self):
        return self.p['call']

    def _say(self, text):
        self.last = text
        return text

    def _out(self, text, heard):
        return {'text': text, 'heard': heard, 'phase': self.phase, 'done': self.phase == 'done', 'wpm': self.wpm}

    def _hdr(self):
        return f"{self.user} DE {self.p['call']}"

    def cq(self):
        self.phase = 'cq'
        v = self.p['call']
        return self._out(self._say(f'CQ CQ CQ DE {v} {v} {v} K'), None)

    def _report(self):
        p = self.p
        return (f"{self._hdr()} {greeting(self.hour)} TNX FER CALL = UR RST {p['rst']} {p['rst']} = NAME {p['name']} "
                f"{p['name']} = QTH {p['qth']} {p['qth']} = HW? {self._hdr()} KN")

    def _topics(self, asks):
        own = [t for t in self.topics if t not in asks][:max(0, VO_TOPICS_PER_OVER - len(asks))]
        out = list(asks) + own
        self.topics = [t for t in self.topics if t not in out]
        return [topic_line(t, self.p) for t in out]

    def _bye(self):
        self.phase = 'done'
        dr = f' {self.user_name}' if self.user_name else ''
        return f'{self._hdr()} TNX FER QSO{dr} = 73 GL = {self._hdr()} SK'

    def read(self, text, units=None):
        calls = [self.p['call'], self.user]
        return segment(units, self.tol, calls) if units else mend_spacing(text, self.tol, calls)

    def reply(self, text, units=None):
        read = self.read(text, units)
        h = hear(read, self.p['call'], self.user)
        h['read'] = read if read != ' '.join(text.split()) else None
        h['marks'] = unsure_marks(units, read) if units else None
        if h['from'] and not self.user:
            self.user = h['from']
        if h['from'] and self.user and not same_call(h['from'], self.user) and self.phase == 'listen':
            self.user = h['from']
        if h['name']:
            self.user_name = h['name']
        if h['empty'] or self.phase == 'done':
            return self._out(None, h)
        others = h['cq'] or h['to_vo'] or h['rst'] or h['name'] or h['qth'] or h['asks'] or h['bye']
        if h['qrs']:
            self.wpm = max(VO_WPM_MIN, self.wpm - VO_QRS)
        if h['qrq']:
            self.wpm = min(VO_WPM_MAX, self.wpm + VO_QRS)
        if (h['agn'] or h['qrs'] or h['qrq']) and self.last and not (h['rst'] or h['name'] or h['qth'] or h['asks']):
            return self._out(self.last, h)
        v = self.p['call']
        if not self.user:
            return self._out(self._say(f'QRZ? DE {v} K'), h)
        hdr = self._hdr()
        if self.phase in ('listen', 'cq'):
            if h['to_vo']:
                self.phase = 'reported'
                return self._out(self._say(self._report()), h)
            if h['cq']:
                self.phase = 'called'
                return self._out(self._say(f'{self.user} DE {v} {v} K'), h)
            if self.phase == 'cq' and h['from']:
                self.phase = 'reported'
                return self._out(self._say(self._report()), h)
            return self._out(self._say(f'QRZ? DE {v} K'), h)
        if self.phase == 'called':
            if h['bye'] and not h['rst']:
                return self._out(self._say(self._bye()), h)
            if not (h['rst'] or h['name'] or h['qth']):
                return self._out(self._say(f'{hdr} PSE AGN K'), h)
            p = self.p
            dr = f' DR {self.user_name}' if self.user_name else ''
            lines = [f'R TNX FER RPRT{dr}', f"UR RST {p['rst']} {p['rst']}", f"NAME {p['name']} {p['name']}",
                     f"QTH {p['qth']} {p['qth']}"]
            if self.mode == 'chatty':
                lines += self._topics(h['asks'])
                self.phase = 'rag'
            else:
                self.phase = 'final'
            return self._out(self._say(f"{hdr} {' = '.join(lines)} = HW? {hdr} K"), h)
        if self.phase == 'reported':
            if h['bye'] and not h['rst'] and not h['name']:
                return self._out(self._say(self._bye()), h)
            if not (h['rst'] or h['name'] or h['qth'] or h['asks']):
                return self._out(self._say(f'{hdr} PSE AGN K'), h)
            dr = f' DR {self.user_name}' if self.user_name else ''
            if self.mode == 'quick':
                self.phase = 'done'
                return self._out(self._say(f'{hdr} R TNX FER RPRT{dr} = TNX QSO ES 73 GL = {hdr} SK'), h)
            self.phase = 'rag'
            lines = [f'R TNX FER RPRT{dr}'] + self._topics(h['asks'])
            return self._out(self._say(f"{hdr} {' = '.join(lines)} = {hdr} K"), h)
        if self.phase == 'final':
            if h['bye'] or others:
                return self._out(self._say(self._bye()), h)
            return self._out(self._say(f'{hdr} PSE AGN K'), h)
        if h['bye'] and not h['asks']:
            return self._out(self._say(self._bye()), h)
        lines = self._topics(h['asks'])
        if not lines:
            return self._out(self._say(self._bye()), h)
        return self._out(self._say(f"{hdr} R {' = '.join(lines)} = {hdr} K"), h)


def vo_timings(text, wpm, fwpm, morse):
    u = 1200 / wpm
    cg, wg = 3 * u, 7 * u
    if fwpm and fwpm < wpm:
        ta = (60000 * wpm - 37200 * fwpm) / (wpm * fwpm)
        cg, wg = 3 * ta / 19, 7 * ta / 19
    els, t = [], 0.0
    for wi, w in enumerate(text.split()):
        if wi:
            t += wg - cg
        codes = [PROSIGN_CODES[w]] if w in PROSIGN_CODES else [morse[c] for c in w if c in morse]
        for ci, code in enumerate(codes):
            if ci or wi:
                t += cg - u
            for e in code:
                on = 3 * u if e == '-' else u
                els.append({'start': t, 'end': t + on, 'word': wi})
                t += on + u
    return {'els': els, 'end': els[-1]['end'] if els else 0}


# --- 1.1 K3: the spacing of an over from the gap model and a lexicon (Viterbi over the word boundaries) -------------
# Every gap between two characters has P(word gap) from the gap model of the hand (decoder GapModel); the best split
# of the over into words maximises P(gaps)·P(text)^weight, P(text) = a product of word costs: a known word (VO words,
# topics, ends, abbreviations, Q codes, QSO lists, the calls of the QSO) is cheap, a pattern (call, RST, number) a bit
# more, anything else costs per word and per character. Characters are never changed (only the spacing).
# the constants live in web/js/vo.js (export const VO_LEX_*)
VO_LEX_WORD = CONSTS['VO_LEX_WORD']
VO_LEX_PATTERN = CONSTS['VO_LEX_PATTERN']
VO_LEX_UNKNOWN = CONSTS['VO_LEX_UNKNOWN']
VO_LEX_CHAR = CONSTS['VO_LEX_CHAR']
VO_LEX_PMIN = CONSTS['VO_LEX_PMIN']
VO_LEX_LONG = int(CONSTS['VO_LEX_LONG'])
VO_LEX_LONG_CHAR = CONSTS['VO_LEX_LONG_CHAR']
VO_LEX_MAXLEN = int(CONSTS['VO_LEX_MAXLEN'])
VO_LEX_WEIGHT = {k: float(v) for k, v in re.findall(r"(\w+): ([\d.]+)",
                                                    re.search(r'VO_LEX_WEIGHT = \{(.*?)\};', VO_JS).group(1))}
NUM_RE = re.compile(r'^\d{1,4}[A-Z]{0,2}$')
LEXICON = (KNOWN | {w for lst in QSO.values() for w in lst} | {k for t in C.VOCAB_QUIZ.values() for k in t})


def word_cost(w, calls=()):
    """−log P(word) (up to a constant) for one word of an over; a trailing '?' is not part of the word."""
    base = _token(w)
    if not base or '?' in base or '*' in base:
        return VO_LEX_WORD + VO_LEX_UNKNOWN + VO_LEX_CHAR * len(w)
    if base in LEXICON or base in calls:
        return VO_LEX_WORD
    if RST_RE.match(base) or NUM_RE.match(base) or looks_like_call(base) or any(same_call(base, c) for c in calls):
        return VO_LEX_WORD + VO_LEX_PATTERN
    return (VO_LEX_WORD + VO_LEX_UNKNOWN + VO_LEX_CHAR * len(base)
            + VO_LEX_LONG_CHAR * max(0, len(base) - VO_LEX_LONG))


def segment(units, tol='mid', calls=()):
    """units = [(text, pw)]: the characters of an over in order (a prosign as its name) with P(word gap) of the gap
    BEFORE it (None for the first; 1 = a fixed boundary). Returns the over as text with the most probable spacing."""
    lam = VO_LEX_WEIGHT.get(tol, 1.0)
    cs = tuple(c for c in calls if c)
    out = []
    # split into runs between fixed boundaries (prosigns, the start)
    runs, cur = [], []
    for i, (t, pw) in enumerate(units):
        fixed = t in PROSIGN_CODES or (i and units[i - 1][0] in PROSIGN_CODES)
        if cur and (pw is None or pw >= 1 or fixed):
            runs.append(cur)
            cur = []
        cur.append((t, pw))
    if cur:
        runs.append(cur)
    for run in runs:
        if len(run) == 1 or run[0][0] in PROSIGN_CODES:
            out.append(''.join(t for t, _ in run))
            continue
        n = len(run)
        ps = [None] + [min(1 - VO_LEX_PMIN, max(VO_LEX_PMIN, run[k][1])) for k in range(1, n)]
        split = [0.0] + [-math.log(p) for p in ps[1:]]
        join = [0.0] + [-math.log(1 - p) for p in ps[1:]]
        jsum = [0.0] * n                            # jsum[k] = Σ join[1..k]; joins inside run[a:b] = jsum[b-1] − jsum[a]
        for k in range(1, n):
            jsum[k] = jsum[k - 1] + join[k]
        best, back = [0.0] + [math.inf] * n, [0] * (n + 1)
        for b in range(1, n + 1):
            for a in range(max(0, b - VO_LEX_MAXLEN), b):
                w = ''.join(t for t, _ in run[a:b])
                c = best[a] + split[a] + (jsum[b - 1] - jsum[a]) + lam * word_cost(w, cs)
                if c < best[b]:
                    best[b], back[b] = c, a
        words, b = [], n
        while b > 0:
            a = back[b]
            words.append(''.join(t for t, _ in run[a:b]))
            b = a
        out.extend(reversed(words))
    return ' '.join(out)


def over_units(dec):
    """The characters of an over decoded with the gap model for segment: [(text, P(word gap before))], a prosign as
    its name; None without the model. After the error sign the gap before the next character is the word gap that
    preceded the error sign (its index in the space)."""
    if not dec or dec.get('conf') is None:
        return None
    out, sp = [], None
    for c in dec['chars']:
        if c['ch'] == ' ':
            sp = c['i0']
            continue
        i = c['i0'] if sp is None else sp
        k, p = dec['gaps'][i], dec['conf'][i]
        pw = None if not out else (1.0 if p is None else (p if k == 2 else 1 - p if k == 1 else 0.0))
        out.append((PROSIGNS.get(c['code'], c['ch']), pw))
        sp = None
    return out


VO_UNSURE = CONSTS['VO_UNSURE']


def unsure_marks(units, read):
    """The unsure gaps of a read over: [(text, unsure)] – words/parts (False), a space ' ' or a join '' (True) at a
    gap with P(word gap) in [VO_UNSURE, 1 − VO_UNSURE]; None when no gap is unsure or the read does not match."""
    if not units or not read:
        return None
    out, pos, word, any_ = [], 0, '', False
    for k, (t, pw) in enumerate(units):
        sep = ''
        if k > 0 and read[pos:pos + 1] == ' ':
            sep, pos = ' ', pos + 1
        if read[pos:pos + len(t)] != t:
            return None
        pos += len(t)
        if (k > 0 and pw is not None and pw < 1 and VO_UNSURE <= pw <= 1 - VO_UNSURE
                and t not in PROSIGN_CODES and units[k - 1][0] not in PROSIGN_CODES):   # a prosign is always a word
            if word:
                out.append((word, False))
            out.append((sep, True))
            word, any_ = '', True
        else:
            word += sep
        word += t
    if pos != len(read):
        return None
    if word:
        out.append((word, False))
    return out if any_ else None
