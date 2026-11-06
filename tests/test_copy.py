# SPDX-License-Identifier: EUPL-1.2
"""Tests of copy behind (Python port of copy.js, M7 + M8): alignment, lag, word results, fatigue."""
import random
import re
import unittest

from tests import copy as C


def ops_str(ops):
    return ''.join({'ok': '=', 'sub': 'x', 'del': '-', 'ins': '+'}[o['op']] for o in ops)


class TestAlign(unittest.TestCase):
    def test_constants_in_js(self):
        self.assertEqual(C.ROUND_ITEMS, 6)
        self.assertEqual(C.COPY_MIN_CHARS, 60)
        from server import coach
        self.assertEqual(coach.COPY_MIN_CHARS, C.COPY_MIN_CHARS)

    def test_exact(self):
        ops = C.align(list('KMURE'), list('KMURE'))
        self.assertEqual(ops_str(ops), '=====')
        sc = C.score(ops, list('KMURE'), list('KMURE'))
        self.assertEqual(sc['acc'], 1)

    def test_missing_char_does_not_shift(self):
        # a missed character must not spoil the scoring of all the following ones
        sent, typed = list('THEDOGRUNS'), list('THEDGRUNS')
        ops = C.align(sent, typed)
        self.assertEqual(ops_str(ops), '====-=====')
        sc = C.score(ops, sent, typed)
        self.assertEqual((sc['ok'], sc['del'], sc['sub'], sc['ins']), (9, 1, 0, 0))
        self.assertAlmostEqual(sc['acc'], 0.9)

    def test_extra_and_sub(self):
        sent, typed = list('ABCD'), list('ABXCE')
        ops = C.align(sent, typed)
        sc = C.score(ops, sent, typed)
        self.assertEqual((sc['ok'], sc['sub'], sc['del'], sc['ins']), (3, 1, 0, 1))
        self.assertEqual(sc['conf'], {'D→E': 1})
        self.assertAlmostEqual(sc['acc'], 3 / 5)

    def test_tie_prefers_sub(self):
        ops = C.align(list('S'), list('H'))
        self.assertEqual(ops_str(ops), 'x')

    def test_empty(self):
        sc = C.score(C.align(list('ABC'), []), list('ABC'), [])
        self.assertEqual((sc['del'], sc['acc']), (3, 0))
        self.assertIsNone(C.score([], [], [])['acc'])

    def test_random_counts_consistent(self):
        rng = random.Random(7)
        for _ in range(200):
            sent = [rng.choice('ABCDE') for _ in range(rng.randint(0, 12))]
            typed = [rng.choice('ABCDE') for _ in range(rng.randint(0, 12))]
            ops = C.align(sent, typed)
            sc = C.score(ops, sent, typed)
            self.assertEqual(sc['ok'] + sc['sub'] + sc['del'], len(sent))
            self.assertEqual(sc['ok'] + sc['sub'] + sc['ins'], len(typed))
            # indexy rostou
            s_idx = [o['s'] for o in ops if o['s'] is not None]
            self.assertEqual(s_idx, list(range(len(sent))))


class TestWords(unittest.TestCase):
    def test_word_results(self):
        words = ['THE', 'DOG', 'RUNS']
        typed = list('THEDGRUNS')
        ops = C.align(list('THEDOGRUNS'), typed)
        self.assertEqual(C.word_results(words, ops), [True, False, True])

    def test_extra_inside_word(self):
        words = ['AB', 'CD']
        ops = C.align(list('ABCD'), list('AXBCD'))
        self.assertEqual(C.word_results(words, ops), [False, True])

    def test_extra_at_boundary_counts_nowhere(self):
        words = ['AB', 'CD']
        ops = C.align(list('ABCD'), list('ABXCD'))
        self.assertEqual(ops_str(ops), '==+==')
        self.assertEqual(C.word_results(words, ops), [True, True])


class TestLag(unittest.TestCase):
    def test_lag_chars(self):
        words = ['ABC', 'DE']
        chars = C.stream(words, char_ms=400, gap_ms=200, word_ms=1000)
        ends = [c['end'] for c in chars]  # 400, 1000, 1600, 3200, 3800
        self.assertEqual(ends, [400, 1000, 1600, 3200, 3800])
        # a typist 1 character behind: types character i 100 ms after the end of character i+1
        typed = [{'ch': c['ch'], 't': (ends[i + 1] if i + 1 < len(ends) else ends[i] + 600) + 100}
                 for i, c in enumerate(chars)]
        ev = C.evaluate(words, chars, typed)
        self.assertEqual([x['ch'] for x in ev['lags']], [1, 1, 1, 1, 0])
        self.assertEqual(ev['lags'][0]['ms'], 700)
        self.assertEqual(ev['words'], [True, True])
        s = C.lag_summary(ev['lags'])
        self.assertEqual(s['lagCh'], 1)
        self.assertEqual(s['lagChMax'], 1)
        self.assertIsNone(s['drift'])  # few samples

    def test_drift(self):
        samples = [{'s': i, 'ms': 0, 'ch': 0 if i < 10 else 2} for i in range(30)]
        self.assertEqual(C.lag_summary(samples)['drift'], 2)

    def test_lesson_summary(self):
        words = ['AB', 'CD']
        chars = C.stream(words)
        typed = [{'ch': ch, 't': chars[i]['end'] + 300} for i, ch in enumerate('ABCE')]
        ev = C.evaluate(words, chars, typed)
        s = C.lesson_summary([{'ev': ev}, {'ev': ev}])
        self.assertEqual((s['n'], s['ok'], s['sub']), (8, 6, 2))
        self.assertEqual(s['words'], {'n': 4, 'ok': 2})
        self.assertEqual(s['confusions'], [{'pair': 'D→E', 'n': 2}])
        self.assertEqual(s['lagMs'], 300)


class TestWordLag(unittest.TestCase):
    def test_lag_words(self):
        words = ['ABC', 'DE', 'FG']
        chars = C.stream(words, char_ms=400, gap_ms=200, word_ms=1000)
        ends = [c['end'] for c in chars]  # ABC: 400,1000,1600; DE: 3200,3800; FG: 5400,6000
        # types word k as a whole only after word k+1 has finished (whole-word lag)
        wend = {0: 1600, 1: 3800, 2: 6000}
        typed = [{'ch': c['ch'], 't': wend.get(c['w'] + 1, 6600) + 50 + i} for i, c in enumerate(chars)]
        ev = C.evaluate(words, chars, typed)
        self.assertEqual([x['wd'] for x in ev['lags']], [1, 1, 1, 1, 1, 0, 0])
        s = C.lag_summary(ev['lags'])
        self.assertEqual((s['lagW'], s['lagWP90']), (1, 1))
        self.assertEqual(ev['words'], [True, True, True])

    def test_without_words_null(self):
        s = C.lag_summary([{'s': 0, 'ms': 10, 'ch': 0}])
        self.assertIsNone(s['lagW'])


def sc(ok, n=20, ins=0, d=0):
    return {'ok': ok, 'n': n, 'ins': ins, 'del': d}


class TestCopyFatigue(unittest.TestCase):
    def feed(self, f, seq, dur=25):
        out, t = [], 0
        for x in seq:
            out.append(f.add(x, t, t + dur))
            t += dur
        return out

    def test_steady_no_proposal(self):
        f = C.CopyFatigue()
        self.assertFalse(any(r['propose'] for r in self.feed(f, [sc(19)] * 20)))

    def test_acc_drop_after_minute(self):
        f = C.CopyFatigue()
        r = self.feed(f, [sc(19)] * 3 + [sc(14, d=2)] * 4)
        # baseline 95 %, window 70 % → signal; > 60 s only on the 3rd line of the window (2 × 25 s = 50 s is not enough)
        self.assertEqual([x['propose'] for x in r], [False] * 5 + [True, True])
        self.assertEqual(r[-1]['kind'], 'acc')

    def test_acc_in_band_not_tired(self):
        f = C.CopyFatigue()
        r = self.feed(f, [sc(20)] * 3 + [sc(17)] * 6)  # 100 % → 85 %: pokles, ale nad 80 %
        self.assertFalse(any(x['propose'] for x in r))

    def test_miss_up(self):
        f = C.CopyFatigue()
        r = self.feed(f, [sc(18, d=0)] * 3 + [sc(17, d=3)] * 5)  # missing 0 % → 15 %
        self.assertTrue(r[-1]['propose'])
        self.assertEqual(r[-1]['kind'], 'miss')

    def test_snooze_and_reset(self):
        f = C.CopyFatigue()
        self.feed(f, [sc(19)] * 3)
        f.snooze(75)
        r = [f.add(sc(10), 75 + 25 * k, 100 + 25 * k) for k in range(8)]
        first = next(k for k, x in enumerate(r) if x['propose'])
        self.assertGreaterEqual(100 + 25 * first, 75 + C.FAT_SNOOZE_S)
        f.reset()
        self.assertFalse(f.add(sc(10), 400, 425)['propose'])  # a new window after a pause


class TestJsShape(unittest.TestCase):
    def test_exports(self):
        names = set(re.findall(r'export function (\w+)', C.COPY_JS))
        for n in ('align', 'score', 'lagSamples', 'lagSummary', 'wordResults', 'evaluate', 'lessonSummary'):
            self.assertIn(n, names)
        self.assertIn('export class CopyFatigue', C.COPY_JS)


if __name__ == '__main__':
    unittest.main()
