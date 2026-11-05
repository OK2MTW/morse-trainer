# SPDX-License-Identifier: EUPL-1.2
"""Python port web/js/content.js (obsah lekce ve skluzu, M7 + M8). Konstanty, šablony a seznamy čte z JS."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_JS = (ROOT / 'web/js/content.js').read_text(encoding='utf-8')
WORDS_JS = (ROOT / 'web/js/words.js').read_text(encoding='utf-8')
ABBR_JS = (ROOT / 'web/js/abbr.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'export const ([A-Z_]+) = ([0-9.]+);', CONTENT_JS)}
GROUP_MIN, GROUP_MAX = int(CONSTS['GROUP_MIN']), int(CONSTS['GROUP_MAX'])
SHARE_LETTERS, SHARE_DIGITS = CONSTS['SHARE_LETTERS'], CONSTS['SHARE_DIGITS']
PSEUDO_MIN, PSEUDO_MAX = int(CONSTS['PSEUDO_MIN']), int(CONSTS['PSEUDO_MAX'])
WORDS_MIN = int(CONSTS['WORDS_MIN'])
PSEUDO_TEMPLATES = re.findall(r"'([CV]+)'", re.search(r'PSEUDO_TEMPLATES = \[(.*?)\]', CONTENT_JS).group(1))
WORDS = [w for w in re.search(r'WORDS = `(.*?)`', WORDS_JS, re.S).group(1).split() if 2 <= len(w) <= 5]
WORDS_LONG = [w for w in re.search(r'WORDS_LONG = `(.*?)`', WORDS_JS, re.S).group(1).split() if 6 <= len(w) <= 7]
ABBR = re.search(r'ABBR = `(.*?)`', ABBR_JS, re.S).group(1).split()
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


def abbr(chars, rng):
    return from_list(list_for(ABBR, chars), ABBR_MIN, rng, lambda: word(chars, rng))


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


def mixed(chars, rng):
    r = rng()
    if r < MIX_WORDS / 2:
        return word(chars, rng)
    if r < MIX_WORDS:
        return long_word(chars, rng)
    if r < MIX_WORDS + MIX_ABBR:
        return abbr(chars, rng)
    return call(chars, rng)


GENERATORS = {'groups': group, 'pseudo': pseudo, 'words': word, 'abbr': abbr, 'calls': call,
              'long': long_word, 'mix': mixed}


def make_items(content, chars, n, rng):
    gen = GENERATORS.get(content, group)
    out = []
    for _ in range(n * 10):
        if len(out) >= n:
            break
        it = gen(chars, rng)
        if it and (not out or it != out[-1]):
            out.append(it)
    return out
