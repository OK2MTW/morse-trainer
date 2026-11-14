# SPDX-License-Identifier: EUPL-1.2
"""1.1 K1: simulated real operators ("protistanice") keying a HW keyer stream – the regression set for reading a
real hand (tools/key_eval.py, tests/test_key_eval.py).

A HW keyer makes the elements (dot 1, dash 3, gap inside 1 unit) – only the event times jitter a little (USB).
The hand makes the rest: personal gaps between characters and words (the 3/7 norm does not hold), a slow tempo
drift of those gaps during a session, sometimes a paddle released too late between elements (gap inside 1.3–1.9),
glued characters (gap between characters 1.0–1.8 → one wrong character), torn characters (gap inside 2.6–3.5 → two
characters) and paddle errors (a missing / extra dot → another character or '*').

Every over returns the truth: meant (the text the operator wanted), keyed (what the hand really keyed: characters
from the physical gaps inside / between characters, words from the intended word gaps) and the gap class of every
tone (0 inside, 1 between characters, 2 between words; None for the first tone)."""
import math
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARSET = (ROOT / 'web/js/charset.js').read_text(encoding='utf-8')
MORSE = dict(re.findall(r"""\[['"](.)['"], '([.-]+)'\]""", CHARSET))
BY_CODE = {}
for _ch, _code in MORSE.items():
    BY_CODE.setdefault(_code, _ch)
PROSIGN_CODES = {'KN': '-.--.', 'SK': '...-.-', 'AR': '.-.-.', 'BK': '-...-.-'}
PROSIGN_BY_CODE = {c: p for p, c in PROSIGN_CODES.items()}

# name, keyer wpm, personal gap between characters / words (in dots, log-normal spread), tempo drift of the gaps
# per character (random walk, kept 0.7–1.4), probabilities per gap / character: late paddle release, glued, torn,
# paddle error
STATIONS = [
    dict(name='norma', wpm=20, char=3.0, word=7.0, sd_char=0.10, sd_word=0.10, drift=0.0,
         release=0.0, glue=0.0, tear=0.0, paddle=0.0),
    dict(name='martin', wpm=20, char=4.0, word=12.0, sd_char=0.28, sd_word=0.20, drift=0.01,
         release=0.03, glue=0.0, tear=0.0, paddle=0.02),
    dict(name='tesny', wpm=25, char=2.4, word=5.0, sd_char=0.15, sd_word=0.15, drift=0.01,
         release=0.0, glue=0.0, tear=0.0, paddle=0.0),
    dict(name='rozvlacny', wpm=18, char=5.0, word=15.0, sd_char=0.25, sd_word=0.25, drift=0.01,
         release=0.02, glue=0.0, tear=0.0, paddle=0.0),
    dict(name='kolisavy', wpm=22, char=3.5, word=9.0, sd_char=0.22, sd_word=0.22, drift=0.04,
         release=0.02, glue=0.0, tear=0.0, paddle=0.0),
    dict(name='nedbaly', wpm=20, char=3.5, word=9.0, sd_char=0.35, sd_word=0.30, drift=0.02,
         release=0.05, glue=0.03, tear=0.03, paddle=0.03),
    dict(name='zacatecnik', wpm=15, char=4.5, word=9.0, sd_char=0.40, sd_word=0.35, drift=0.02,
         release=0.05, glue=0.0, tear=0.02, paddle=0.02),
    dict(name='rychly', wpm=28, char=3.0, word=6.5, sd_char=0.18, sd_word=0.18, drift=0.01,
         release=0.0, glue=0.0, tear=0.0, paddle=0.0),
]

ME, VO = 'OK2MTW', 'OK1ABC'
OVERS = [
    'CQ CQ CQ DE {me} {me} PSE K',
    '{vo} DE {me} GM DR OM TNX FER CALL UR RST 599 599 HR QTH LIBEREC LIBEREC NAME MARTIN MARTIN HW? {vo} DE {me} KN',
    '{vo} DE {me} R R TNX FER RPRT ES INFO RIG HR FT817 PWR 5W ANT DIPOLE WX SUNNY TEMP 12C {vo} DE {me} K',
    'QRS PSE QRS {vo} DE {me} K',
    '{vo} DE {me} OK FB QSL VIA BURO 73 ES GL TU',
    'R TNX FER NICE QSO 73 {vo} DE {me} SK',
]


def over_texts(me=ME, vo=VO):
    return [o.format(me=me, vo=vo) for o in OVERS]


def _word_codes(word):
    if word in PROSIGN_CODES:
        return [PROSIGN_CODES[word]]
    return [MORSE[c] for c in word]


def _paddle(code, rng):
    """A paddle error: the last element missing or an extra dot (the keyer repeats the dot paddle)."""
    if len(code) > 1 and rng.random() < 0.5:
        return code[:-1]
    return code + '.'


def _read(code):
    return PROSIGN_BY_CODE.get(code) if code in PROSIGN_BY_CODE else BY_CODE.get(code, '*')


class Operator:
    """One simulated operator keeping its tempo state across the overs of a session."""

    def __init__(self, st, seed=0):
        self.st = st
        self.rng = random.Random(f"{st['name']}/{seed}")
        self.scale = 1.0

    def _drift(self):
        if self.st['drift']:
            self.scale = min(1.4, max(0.7, self.scale * math.exp(self.rng.gauss(0, self.st['drift']))))

    def key(self, text):
        """Keys one over → {tones: [{start, end}], meant, keyed, truth: [class per tone]}."""
        st, rng = self.st, self.rng
        u = 1200 / st['wpm']
        jit = 6.0                                             # USB event jitter in ms (late events)
        t = 0.0
        tones, truth = [], []
        words = text.split()
        keyed_words = []
        kind = None
        for wi, word in enumerate(words):
            codes = _word_codes(word)
            keyed_codes = []                                   # codes by the physical gaps
            for ci, code in enumerate(codes):
                if st['paddle'] and rng.random() < st['paddle']:
                    code = _paddle(code, rng)
                self._drift()
                for ei, el in enumerate(code):
                    on = u * (3 if el == '-' else 1)
                    s = t + rng.uniform(0, jit)
                    e = t + on + rng.uniform(0, jit)
                    tones.append({'start': s, 'end': max(e, s + 0.5 * u)})
                    truth.append(kind)
                    if kind in (None, 1, 2):
                        keyed_codes.append(el)
                    else:
                        keyed_codes[-1] += el
                    t += on
                    if ei < len(code) - 1:                     # gap inside the character
                        r = rng.random()
                        if st['tear'] and r < st['tear'] / max(1, len(code) - 1):
                            t += u * rng.uniform(2.6, 3.5)
                            kind = 1
                        elif st['release'] and r < st['release'] + st['tear']:
                            t += u * rng.uniform(1.3, 1.9)
                            kind = 0
                        else:
                            t += u
                            kind = 0
                    elif ci < len(codes) - 1:                  # gap between characters
                        if st['glue'] and rng.random() < st['glue']:
                            t += u * rng.uniform(1.0, 1.8)
                            kind = 0
                        else:
                            t += u * max(2.2, st['char'] * self.scale * math.exp(rng.gauss(0, st['sd_char'])))
                            kind = 1
                    else:                                      # gap between words (intended)
                        t += u * max(2.6, st['word'] * self.scale * math.exp(rng.gauss(0, st['sd_word'])))
                        kind = 2
            keyed_words.append(''.join(_read(c) for c in keyed_codes) if word not in PROSIGN_CODES
                               or len(keyed_codes) != 1 else _read(keyed_codes[0]))
        return {'tones': tones, 'meant': ' '.join(words), 'keyed': ' '.join(keyed_words), 'truth': truth}


def session(st, seed=0, me=ME, vo=VO):
    """The overs of one session of an operator (the tempo state carries over)."""
    op = Operator(st, seed)
    return [op.key(t) for t in over_texts(me, vo)]
