# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/content.js (content of copy-behind lessons, M7 + M8). Constants, templates and lists are read from the JS."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_JS = (ROOT / 'web/js/content.js').read_text(encoding='utf-8')
WORDS_JS = (ROOT / 'web/js/words.js').read_text(encoding='utf-8')
VOCAB_JS = (ROOT / 'web/js/vocab.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'export const ([A-Z_]+) = ([0-9.]+);', CONTENT_JS)}
GROUP_MIN, GROUP_MAX = int(CONSTS['GROUP_MIN']), int(CONSTS['GROUP_MAX'])
SHARE_LETTERS, SHARE_DIGITS = CONSTS['SHARE_LETTERS'], CONSTS['SHARE_DIGITS']
PSEUDO_MIN, PSEUDO_MAX = int(CONSTS['PSEUDO_MIN']), int(CONSTS['PSEUDO_MAX'])
WORDS_MIN = int(CONSTS['WORDS_MIN'])
PSEUDO_TEMPLATES = re.findall(r"'([CV]+)'", re.search(r'PSEUDO_TEMPLATES = \[(.*?)\]', CONTENT_JS).group(1))
WORDS = [w for w in re.search(r'WORDS = `(.*?)`', WORDS_JS, re.S).group(1).split() if 2 <= len(w) <= 5]
WORDS_LONG = [w for w in re.search(r'WORDS_LONG = `(.*?)`', WORDS_JS, re.S).group(1).split() if 6 <= len(w) <= 7]
# 0.10.9: abbreviations and Q codes for copy behind = quiz forms of items mastered in the vocabulary trainer (vocab.js)
VOCAB_QUIZ = {}
for _list, _name in (('abbr', 'ABBR_TABLE'), ('q', 'Q_TABLE')):
    VOCAB_QUIZ[_list] = {}
    for _line in re.search(rf'const {_name} = `(.*?)`', VOCAB_JS, re.S).group(1).strip().splitlines():
        _code, _show, _quiz, *_ = (x.strip() for x in _line.split('|'))
        VOCAB_QUIZ[_list][_code] = _quiz.split()
COPY_VOCAB_LISTS = re.findall(r"'(\w+)'", re.search(r'COPY_VOCAB_LISTS = \[(.*?)\]', VOCAB_JS).group(1))
PROSIGNS = re.findall(r'(\w+): \'<', re.search(r'PROSIGNS = \{(.*?)\}', VOCAB_JS).group(1))
VOCAB_MASTER_N = int(re.search(r'VOCAB_MASTER_N = (\d+)', VOCAB_JS).group(1))
VOCAB_MASTER_ACC = float(re.search(r'VOCAB_MASTER_ACC = ([0-9.]+)', VOCAB_JS).group(1))
ABBR_MIN, LONG_MIN = int(CONSTS['ABBR_MIN']), int(CONSTS['LONG_MIN'])
CALL_SLASH, MIX_WORDS, MIX_ABBR = CONSTS['CALL_SLASH'], CONSTS['MIX_WORDS'], CONSTS['MIX_ABBR']
CALL_PREFIXES = re.findall(r"'([LD]+)'", re.search(r'CALL_PREFIXES = \[(.*?)\]', CONTENT_JS).group(1))
CALL_SUFFIX = [int(x) for x in re.search(r'CALL_SUFFIX = \[(.*?)\]', CONTENT_JS).group(1).split(',')]
LETTERS, DIGITS, VOWELS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '0123456789', 'AEIOU'


def pick(arr, rng):
    return arr[int(rng() * len(arr))]


def pools(chars):
    return {'L': [c for c in chars if c in LETTERS], 'D': [c for c in chars if c in DIGITS],
            'P': [c for c in chars if c not in LETTERS and c not in DIGITS]}


def group(chars, rng):
    p = pools(chars)
    n = GROUP_MIN + int(rng() * (GROUP_MAX - GROUP_MIN + 1))
    out = ''
    for _ in range(n):
        r = rng()
        pool = p['L'] if r < SHARE_LETTERS else p['D'] if r < SHARE_LETTERS + SHARE_DIGITS else p['P']
        if not pool:
            pool = p['L'] or chars
        out += pick(pool, rng)
    return out


def pseudo(chars, rng):
    L = pools(chars)['L']
    if not L:
        return group(chars, rng)
    V = [c for c in L if c in VOWELS]
    K = [c for c in L if c not in VOWELS]
    return ''.join(pick((V if x == 'V' else K) or L, rng) for x in pick(PSEUDO_TEMPLATES, rng))


def words_for(chars):
    s = set(chars)
    return [w for w in WORDS if all(c in s for c in w)]


def word(chars, rng, avail=None):
    avail = words_for(chars) if avail is None else avail
    if len(avail) >= WORDS_MIN or (avail and rng() < len(avail) / WORDS_MIN):
        return pick(avail, rng)
    return pseudo(chars, rng)


def list_for(lst, chars):
    s = set(chars)
    return [w for w in lst if all(c in s for c in w)]


def from_list(avail, mn, rng, fb):
    if len(avail) >= mn or (avail and rng() < len(avail) / mn):
        return pick(avail, rng)
    return fb()


def vocab_mastered(s):
    return bool(s) and s[0] >= VOCAB_MASTER_N and (s[0] - s[1]) / s[0] >= VOCAB_MASTER_ACC - 1e-9 and s[2] == 1


def copy_abbr_forms(stat):
    """Port of vocab.js copyAbbrForms: quiz forms of mastered abbreviations and Q codes, without prosigns."""
    out = set()
    for lst in COPY_VOCAB_LISTS:
        for code, forms in VOCAB_QUIZ[lst].items():
            if vocab_mastered(stat(lst, code)):
                out.update(f for f in forms if f not in PROSIGNS)
    return sorted(out)


ALL_ABBR = copy_abbr_forms(lambda lst, code: [3, 0, 1])  # everything mastered


def abbr(chars, rng, avail=()):
    return from_list(list(avail), ABBR_MIN, rng, lambda: word(chars, rng))


def long_word(chars, rng):
    return from_list(list_for(WORDS_LONG, chars), LONG_MIN, rng, lambda: word(chars, rng))


def call(chars, rng):
    p = pools(chars)
    first = [c for c in p['L'] if c != 'Q']
    if not p['D'] or not first:
        return word(chars, rng)
    out = ''
    for x in pick(CALL_PREFIXES, rng):
        out += pick(p['D'], rng) if x == 'D' else pick(p['L'] if out else first, rng)
    out += pick(p['D'], rng)
    for _ in range(pick(CALL_SUFFIX, rng)):
        out += pick(p['L'], rng)
    sl = [c for c in 'PM' if c in p['L']]
    if '/' in chars and sl and rng() < CALL_SLASH:
        out += '/' + pick(sl, rng)
    return out


def mixed(chars, rng, abbr_avail=()):
    r = rng()
    if r < MIX_WORDS / 2:
        return word(chars, rng)
    if r < MIX_WORDS:
        return long_word(chars, rng)
    if r < MIX_WORDS + MIX_ABBR:
        return abbr(chars, rng, abbr_avail)
    return call(chars, rng)


def _js_list(name):
    return re.findall(r"'([^']*)'", re.search(rf'export const {name} = \[(.*?)\];', CONTENT_JS, re.S).group(1))


QSO_TEMPLATES = _js_list('QSO_TEMPLATES')
QSO_LISTS = {k: _js_list(f'QSO_{k}') for k in ('NAMES', 'QTH', 'WX', 'RIG', 'ANT', 'PWR')}


def qso_line(chars, rng):
    """M9 (U5): one QSO line as words from mastered characters, None when no template fits."""
    cs = set(chars)
    ok = lambda s: all(c in cs for c in s)  # noqa: E731

    def pick_ok(lst):
        lst = [x for x in lst if ok(x)]
        return pick(lst, rng) if lst else None
    a = call(chars, rng)
    b = call(chars, rng)
    for _ in range(5):
        if b != a:
            break
        b = call(chars, rng)
    v = {'A': a, 'B': b, 'RST': '5' + pick(['5', '7', '9'], rng) + '9', 'NR': str(1 + int(rng() * 400)).zfill(3),
         'NAME': pick_ok(QSO_LISTS['NAMES']), 'QTH': pick_ok(QSO_LISTS['QTH']), 'WX': pick_ok(QSO_LISTS['WX']),
         'RIG': pick_ok(QSO_LISTS['RIG']), 'ANT': pick_ok(QSO_LISTS['ANT']), 'PWR': pick_ok(QSO_LISTS['PWR']),
         'TEMP': str(int(rng() * 25))}
    fits = [s for s in (re.sub(r'\{(\w+)\}', lambda m: v.get(m.group(1)) or '\0', tpl) for tpl in QSO_TEMPLATES)
            if ok(s.replace(' ', ''))]
    return pick(fits, rng).split(' ') if fits else None


def qso(chars, n, rng):
    out = []
    for _ in range(n):
        if len(out) >= n:
            break
        line = qso_line(chars, rng)
        if not line:
            return [mixed(chars, rng) for _ in range(n)]
        out += line
    return out[:n]


GENERATORS = {'groups': group, 'pseudo': pseudo, 'words': word, 'abbr': abbr, 'calls': call,
              'long': long_word, 'mix': mixed, 'qso': lambda chars, rng: qso(chars, 1, rng)[0]}


def make_items(content, chars, n, rng, abbr_forms=()):
    if content == 'qso':
        return qso(chars, n, rng)
    gen = GENERATORS.get(content, group)
    if content in ('abbr', 'mix'):
        av = list_for(abbr_forms, chars)
        gen = (lambda c, r: abbr(c, r, av)) if content == 'abbr' else (lambda c, r: mixed(c, r, av))
    out = []
    for _ in range(n * 10):
        if len(out) >= n:
            break
        it = gen(chars, rng)
        if it and (not out or it != out[-1]):
            out.append(it)
    return out
