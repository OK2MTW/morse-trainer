# SPDX-License-Identifier: EUPL-1.2
"""1.1 K2: the gap model of the hand (tests/decoder.py GapModel, model_gaps) – a log-normal mixture of human gaps
between characters / words with the 3/7 prior, learned over the over and carried to the next one."""
import math
import random
import unittest

from tests import decoder as D


def gaps(char, word, n_words=20, chars=4, sd=0.15, seed=1):
    """Human gaps (dots) of a hand: per word (chars − 1) gaps between characters, then one word gap; truth 1/2."""
    rng = random.Random(seed)
    xs, truth = [], []
    for _ in range(n_words):
        for _ in range(chars - 1):
            xs.append(max(2.2, char * math.exp(rng.gauss(0, sd))))   # as the simulator
            truth.append(1)
        xs.append(max(2.6, word * math.exp(rng.gauss(0, sd))))
        truth.append(2)
    return xs, truth


def classify(xs, prior=None):
    units = [None]
    for x in xs:                      # each human gap after one inside a character (1 dot)
        units += [1.0, x]
    kinds, conf, gm = D.model_gaps(units, prior)
    return [k for k, x in zip(kinds, units) if x is not None and x >= D.MACH_SPLIT], conf, gm


class GapModelTest(unittest.TestCase):
    def test_norm_hand(self):
        xs, truth = gaps(3, 7)
        kinds, _, gm = classify(xs)
        self.assertEqual(kinds, truth)
        self.assertAlmostEqual(math.exp(gm.m[0]), 3, delta=0.3)
        self.assertAlmostEqual(math.exp(gm.m[1]), 7, delta=0.7)

    def test_tight_hand_cold(self):
        # gaps between characters 2.4, words 5 (below the old fixed minimum of 5 dots) – read right in the first over
        xs, truth = gaps(2.4, 5, n_words=8)
        kinds, _, _ = classify(xs)
        self.assertEqual(kinds, truth)

    def test_slow_hand(self):
        # characters 5, words 15: the EM starts from a split of the data, not from 3/7 (a local optimum)
        xs, truth = gaps(5, 15)
        kinds, _, gm = classify(xs)
        self.assertEqual(kinds, truth)
        self.assertGreater(math.exp(gm.m[1]), 10)

    def test_word_share_prior(self):
        # overlapping classes: the word class must not grow to a half
        xs, _ = gaps(4.5, 9, sd=0.35, n_words=20)      # true share 0.25
        _, _, gm = classify(xs)
        self.assertLess(gm.w[1], 0.45)

    def test_tempo_drift(self):
        # the hand slows down during the over (×1.6): globally the classes overlap, locally not
        xs, truth = [], []
        for i in range(40):
            f = 1 + 0.6 * i / 39
            for _ in range(3):
                xs.append(3 * f)
                truth.append(1)
            xs.append(6 * f)
            truth.append(2)
        kinds, _, _ = classify(xs)
        self.assertEqual(kinds, truth)

    def test_confidence(self):
        xs, _ = gaps(3, 7)
        units = [None, 1.0] + sum(([x, 1.0] for x in xs), [])
        kinds, conf, _ = D.model_gaps(units)
        self.assertTrue(all(c == 1.0 for k, c in zip(kinds[1:], conf[1:]) if k == 0))
        self.assertTrue(all(0.5 <= c <= 1.0 for c in conf[1:]))

    def test_learned_carried_in_proportion(self):
        xs, _ = gaps(4, 12, n_words=40)
        _, _, gm = classify(xs)
        prior = gm.learned()
        self.assertLessEqual(sum(prior['n']), D.GM_KEEP + 1e-9)
        self.assertGreater(prior['n'][0], 2 * prior['n'][1])      # the weights not equalised
        # the next over starts from the learned hand: one ambiguous gap by the learned means, not by the norm 3/7
        kinds, _, _ = classify([4.0, 4.2, 11.0], prior)
        self.assertEqual(kinds, [1, 1, 2])

    def test_pauses_outside_the_model(self):
        # 1.1.4 (Martin's Sending page): pauses between attempts (seconds) dragged the word class up and real word gaps
        # of ~8 dots read as gaps between characters (CQCQCQDE) – pauses are word gaps for sure and stay out of the fit
        xs, truth = gaps(3.4, 8.5, n_words=12)
        for i in (len(xs) // 3, 2 * len(xs) // 3):
            xs[i] = 300.0
            truth[i] = 2
        kinds, conf, gm = classify(xs)
        self.assertEqual(kinds, truth)
        self.assertLess(math.exp(gm.m[1]), D.GM_PAUSE)
        self.assertEqual(D.GM_PAUSE, 20)

    def test_empty(self):
        kinds, conf, gm = D.model_gaps([None])
        self.assertEqual(kinds, [None])
        self.assertTrue(gm.learned()['m'])


if __name__ == '__main__':
    unittest.main()


class TestGapModelJs(unittest.TestCase):
    """1.1 K2 part 2: the model lives in web/js/decoder.js (no JS engine on the Pi – the port is checked by its shape
    and the constants, which tests/decoder.py reads from decoder.js)."""

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        self.dec = D.DECODER_JS
        self.voui = (root / 'web/js/voui.js').read_text(encoding='utf-8')

    def test_constants_from_js(self):
        for name in ('CHAR', 'WORD', 'SD', 'SD_MIN', 'NPRIOR', 'KEEP', 'SEP', 'ITER', 'W_WORD', 'W_N', 'WIN', 'SHRINK', 'MIN', 'PAUSE'):
            self.assertIn(f'DEC_GM_{name}', D.CONSTS)
        self.assertEqual(D.GM_NORM, (3.0, 7.0))
        self.assertEqual(D.GM_ITER, 15)

    def test_js_shape(self):
        for s in ('export class GapModel', 'export function modelGaps(units, prior = null)',
                  'export function machineUnits(tones)', 'wordProbs()', 'learned()', 'start(hs)', 'fit(xs)',
                  'opts.model', 'opts.gapPrior', 'gm.kinds[i]', 'conf: gm ? gm.conf : null'):
            self.assertIn(s, self.dec)

    def test_vo_reads_with_model(self):
        # the end of the over and its detection read with the model of the hand carried between overs …
        self.assertIn('const own = decodeOwn(true);', self.voui)
        self.assertIn('const dec = decodeOwn(true);', self.voui)
        self.assertIn('V.gm = dec.gm.learned()', self.voui)
        self.assertIn('gapPrior: V.gm', self.voui)
        self.assertIn('V.gm = null;', self.voui)          # a new QSO = a new hand
        # … the live line keeps the 1.0 reading
        self.assertIn('${overText(decodeOwn().chars)}…', self.voui)
