# SPDX-License-Identifier: EUPL-1.2
"""VK D3 adaptive decoder (tests/decoder.py = port of web/js/decoder.js): exact timing, tempo independence, the
operator's hand simulated with random spread of lengths (how much the decoder copes with), bug dashes, error sign."""
import json
import math
import random
import re
import unittest
from pathlib import Path

from tests import decoder as D

ROOT = Path(__file__).resolve().parent.parent
CHARSET = (ROOT / 'web/js/charset.js').read_text(encoding='utf-8')
MORSE = dict(re.findall(r"""\[['"](.)['"], '([.-]+)'\]""", CHARSET))
CHARS = [c for c in MORSE if c.isalnum()]


def hand(words, wpm, sigma=0.0, ratio=3.0, gapk=1.0, drift=0.0, rng=None, known=False, inner=1.0, dot=1.0):
    """Tones of an operator: every element and gap × lognormal(sigma), dash = ratio units, gaps between characters
    and words × gapk, tempo as a slow random walk (drift per element). known = elements of an automatic keyer.
    inner = gap inside a character in units, dot = dot length in units (a short tap on a touch screen)."""
    rng = rng or random.Random(0)
    u = 1200 / wpm
    t, scale, out = 0.0, 1.0, []

    def j():
        return math.exp(rng.gauss(0, sigma))
    for wi, word in enumerate(words):
        for ci, ch in enumerate(word):
            code = MORSE[ch]
            for ei, e in enumerate(code):
                scale = min(1.6, max(0.6, scale * math.exp(rng.gauss(0, drift))))
                on = u * scale * (ratio if e == '-' else dot) * j()
                tone = {'start': t, 'end': t + on}
                if known:
                    tone['el'] = e
                out.append(tone)
                t += on
                if ei < len(code) - 1:
                    t += inner * u * scale * j()
                elif ci < len(word) - 1:
                    t += 3 * u * scale * gapk * j()
                else:
                    t += 7 * u * scale * gapk * j()
    return out


def char_accuracy(sent, got):
    a, b = sent.replace(' ', ''), got.replace(' ', '')
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        p, d[0] = d[0], i
        for k in range(1, len(b) + 1):
            p, d[k] = d[k], min(d[k] + 1, d[k - 1] + 1, p + (a[i - 1] != b[k - 1]))
    return 1 - d[len(b)] / len(a)


def text_accuracy(sent, got):
    """1 − edit distance / length, spaces included (word gaps count)."""
    d = list(range(len(got) + 1))
    for i in range(1, len(sent) + 1):
        p, d[0] = d[0], i
        for k in range(1, len(got) + 1):
            p, d[k] = d[k], min(d[k] + 1, d[k - 1] + 1, p + (sent[i - 1] != got[k - 1]))
    return 1 - d[len(got)] / len(sent)


def simulate(n=60, seed=1, keyed=18, cfg=18, **kw):
    """Average character accuracy over n lines of 4 random 5-character groups."""
    rng = random.Random(seed)
    total = 0
    for _ in range(n):
        words = [''.join(rng.choice(CHARS) for _ in range(5)) for _ in range(4)]
        tones = hand(words, keyed, rng=rng, **kw)
        total += char_accuracy(' '.join(words), D.decode_tones(tones, cfg, MORSE)['text'])
    return total / n


class DecoderTest(unittest.TestCase):
    def test_constants_and_functions(self):
        c = D.CONSTS
        self.assertEqual((c['DEC_ALPHA'], c['DEC_RATIO_LO'], c['DEC_RATIO_HI']), (0.25, 2, 4.5))
        self.assertEqual((c['DEC_GAP_IN_LO'], c['DEC_GAP_IN_HI'], c['DEC_CHAR_GAP_LO'], c['DEC_CHAR_GAP_HI']),
                         (0.6, 1.6, 1.8, 4.5))
        self.assertAlmostEqual(c['DEC_WORD_GAP'], math.sqrt(7 / 3), places=2)
        self.assertEqual((c['DEC_FIX_DOTS'], c['DEC_INIT_N'], c['DEC_SPLIT']), (7, 24, 1.8))
        self.assertEqual((c['DEC_WIN'], c['DEC_GAP_SPLIT'], c['DEC_WORD_SPLIT'], c['DEC_IN_MAX'], c['DEC_WORD_MID'],
                          c['DEC_IN_ONE']), (16, 1.3, 1.4, 1.6, 4, 1.3))
        for frag in ('export function initialDot(', 'export function decodeTones(', 'class DecoderState',
                     'if (!el) el = ms < Math.sqrt(this.dot * this.dash) ? DOT : DASH;',
                     'kind = ms < Math.sqrt(this.g1 * this.g3) ? 0 : (ms < this.g3 * DEC_WORD_GAP ? 1 : 2);',
                     'export function markThreshold(lens) {', 'export function gapThresholds(gaps, mid) {',
                     'return hi >= ratio * lo ? [lo, hi] : null;',
                     'const t1 = md < DEC_IN_ONE * mid ? md * DEC_GAP_SPLIT : md / DEC_GAP_SPLIT;',
                     'return [t1, Math.max(DEC_WORD_MID * mid, t1 * DEC_WORD_GAP)];',
                     'if (a >= DEC_IN_MAX * mid) return [a / DEC_GAP_SPLIT, Math.sqrt(a * b)];',
                     'const mb = apart(split(grp[1]), DEC_WORD_SPLIT);',
                     'if (mb) return [Math.sqrt(a * mb[0]), Math.sqrt(mb[0] * mb[1])];',
                     'const ma = apart(split(grp[0]), DEC_WORD_SPLIT);',
                     'if (ma && b >= DEC_WORD_MID * mid && b >= DEC_WORD_SPLIT * ma[1]) {',
                     'return [Math.sqrt(ma[0] * ma[1]), Math.sqrt(ma[1] * b)];',
                     'return [Math.sqrt(a * b), Math.max(b * DEC_WORD_GAP, DEC_WORD_MID * mid)];',
                     'const g0 = Math.min(Math.max(0, i - 1 - DEC_WIN), Math.max(0, gms.length - 2 * DEC_WIN - 1));',
                     'const thr = gapThresholds(gms.slice(g0, g0 + 2 * DEC_WIN + 1), st.mid());',
                     'const m0 = Math.min(Math.max(0, i - DEC_WIN), Math.max(0, lens.length - 2 * DEC_WIN - 1));',
                     'const thr = markThreshold(lens.slice(m0, m0 + 2 * DEC_WIN + 1));',
                     'alpha(n) { return Math.max(DEC_ALPHA, 1 / (n + 2)); }',
                     'this.g3 = Math.min(DEC_CHAR_GAP_HI * this.dot, Math.max(DEC_CHAR_GAP_LO * this.g1, this.g3));',
                     'return m < 2 * g ? m : m / 3;',
                     'if (at !== null && median(lens.slice(at)) >= DEC_SPLIT * median(lens.slice(0, at))) {',
                     "if (kind === 2 && chars.length && chars.at(-1).ch !== ' ')"):
            self.assertIn(frag, D.DECODER_JS)

    def test_exact_timing_every_character(self):
        words = [''.join(CHARS[i:i + 5]) for i in range(0, len(CHARS), 5)]
        for wpm in (5, 12, 18, 25, 40):
            r = D.decode_tones(hand(words, wpm), wpm, MORSE)
            self.assertEqual(r['text'], ' '.join(words), wpm)
            self.assertEqual(r['fixes'], 0)
            self.assertAlmostEqual(r['wpm'], wpm, delta=0.01 * wpm)

    def test_set_speed_does_not_matter(self):
        words = ['PARIS', 'CQ', 'TEST', 'OK2MTW']
        for keyed in (6, 12, 25, 40):
            r = D.decode_tones(hand(words, keyed), 18, MORSE)
            self.assertEqual(r['text'], 'PARIS CQ TEST OK2MTW', keyed)
            self.assertAlmostEqual(r['wpm'], keyed, delta=0.05 * keyed)

    def test_single_characters(self):
        # one group of lengths only: the gaps inside the character decide (dots vs dashes); one tone: the set speed
        for ch in ('5', 'H', 'S', '0', 'O', 'M', 'A', 'N', '6', '1'):
            for keyed in (10, 30):
                self.assertEqual(D.decode_tones(hand([ch], keyed), 18, MORSE)['text'], ch, (ch, keyed))
        self.assertEqual(D.decode_tones(hand(['E'], 18), 18, MORSE)['text'], 'E')
        self.assertEqual(D.decode_tones(hand(['T'], 18), 18, MORSE)['text'], 'T')
        self.assertEqual(D.decode_tones([], 18, MORSE)['text'], '')

    def test_hand_spread(self):
        # limits of the operator's hand (scratch simulation 2026-11-07: σ 10 % 100 %, 15 % 99.6 %, 20 % 95 %)
        self.assertEqual(simulate(sigma=0.10), 1.0)
        self.assertGreaterEqual(simulate(sigma=0.15), 0.98)
        self.assertGreaterEqual(simulate(sigma=0.20), 0.92)

    def test_hand_habits(self):
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=8), 0.97)     # much slower than set
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=30), 0.97)    # much faster than set
        self.assertGreaterEqual(simulate(sigma=0.15, gapk=0.75), 0.93)   # short gaps between characters
        self.assertGreaterEqual(simulate(sigma=0.15, ratio=2.2), 0.95)   # short dashes
        self.assertGreaterEqual(simulate(sigma=0.15, ratio=4.0), 0.97)   # long dashes
        self.assertGreaterEqual(simulate(sigma=0.15, drift=0.03), 0.97)  # wandering tempo

    def test_hand_rhythm(self):
        # validation #31 (0.12.2): a real hand keeps longer gaps inside characters and long gaps between them
        # (the old self-locking estimate read these as T/E only: 0–16 %); the threshold comes from the neighbourhood
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=12, inner=2, gapk=4 / 3), 0.9)    # 2 / 4 / 9.3 units
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=12, inner=2, gapk=5 / 3), 0.95)   # Farnsworth-like hand
        # 2.5 units inside a character is close to the gap between characters of an even E T text (≈ 1.73 × the
        # dot/dash threshold); DEC_IN_MAX 1.6 favours reading E T correctly (0.12.4)
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=12, inner=2.5, gapk=5 / 3), 0.75)
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=12, inner=2, gapk=4 / 3, dot=0.8), 0.88)   # short taps
        self.assertGreaterEqual(simulate(sigma=0.15, keyed=12, inner=1.5), 0.88)
        self.assertEqual(D.decode_tones(hand(['CQ', 'TEST'], 12, inner=2, gapk=4 / 3), 18, MORSE)['text'], 'CQ TEST')
        # an even E T text: no gaps inside characters, the anchor from the tone lengths decides
        self.assertEqual(D.decode_tones(hand(['TEE', 'TEE', 'ET'], 15), 18, MORSE)['text'], 'TEE TEE ET')

    def test_real_recordings(self):
        # validation #31: Martin's hand on a phone (straight key, 2026-11-08) – long gaps between characters against
        # the tones, word gaps only ~1.3× longer; 0.12.2 read 45 %, 0.12.4 77 % (the rest: dashes as short as dots
        # after a dot, overlapping gaps between characters and words – the hand, see validation #31)
        data = json.loads((ROOT / 'tests/data/key_recordings.json').read_text(encoding='utf-8'))['recordings']
        accs = []
        for r in data:
            tones = [{'start': s, 'end': e} for s, e in r['tones']]
            text = D.decode_tones(tones, 14, MORSE)['text']
            accs.append(text_accuracy(r['meant'], text))
            self.assertGreaterEqual(accs[-1], 0.6, (r['meant'], text))
        self.assertGreaterEqual(sum(accs) / len(accs), 0.76)

    def test_automatic_elements_known(self):
        # iambic: the elements are exact and known, only the gaps between characters come from the hand
        rng = random.Random(3)
        tones = hand(['CQ', 'DE', 'OK2MTW'], 20, sigma=0.2, rng=rng, known=True)
        r = D.decode_tones(tones, 20, MORSE)
        self.assertEqual(r['marks'], [t['el'] for t in tones])

    def test_bug_dash_read_by_sound(self):
        # bug: automatic dots (known), dashes by hand; a dash held only 1.2 units reads as a dot (as heard)
        u = 60
        tones, t = [], 0.0
        seq = [(None, 3 * u), ('.', u), (None, 3 * u), ('.', u)]   # C  -.-.
        seq += [(None, 3 * u), ('.', u), (None, 1.2 * u)]           # K meant, the last dash too short → -.. = D
        for k, (el, length) in enumerate(seq):
            tone = {'start': t, 'end': t + length}
            if el:
                tone['el'] = el
            tones.append(tone)
            t += length + (3 * u if k == 3 else u)
        self.assertEqual(D.decode_tones(tones, 20, MORSE)['text'], 'CD')

    def test_error_sign(self):
        u = 60
        tones = hand(['CQ', 'TEST'], 20)
        t = tones[-1]['end'] + 3 * u
        for _ in range(8):   # HH right after TEST (character gap) drops the word in progress
            tones.append({'start': t, 'end': t + u})
            t += 2 * u
        t += 6 * u
        for tone in hand(['DE'], 20):
            tones.append({'start': tone['start'] + t, 'end': tone['end'] + t})
        r = D.decode_tones(tones, 20, MORSE)
        self.assertEqual(r['text'], 'CQ DE')
        self.assertEqual(r['fixes'], 1)
        # after a word gap the error sign drops the previous word
        tones = hand(['CQ', 'TEST'], 20)
        t = tones[-1]['end'] + 7 * u
        for _ in range(8):
            tones.append({'start': t, 'end': t + u})
            t += 2 * u
        r = D.decode_tones(tones, 20, MORSE)
        self.assertEqual((r['text'], r['fixes']), ('CQ', 1))

    def test_char_spans(self):
        r = D.decode_tones(hand(['AB', 'C'], 20), 20, MORSE)
        self.assertEqual([(c['ch'], c['i0'], c['i1']) for c in r['chars']],
                         [('A', 0, 1), ('B', 2, 5), (' ', 6, 5), ('C', 6, 9)])
        self.assertEqual(r['gaps'][:3], [None, 0, 1])


if __name__ == '__main__':
    unittest.main()
