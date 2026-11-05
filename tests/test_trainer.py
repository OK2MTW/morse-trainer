# SPDX-License-Identifier: EUPL-1.2
"""Testy logiky trenéra (Python port drill.js) – simulace Kochova postupu, váhy, rozlišování."""
import random
import unittest

from tests import trainer as T


class TestTables(unittest.TestCase):
    def test_charset(self):
        self.assertEqual(len(T.KOCH_ORDER), 51)
        self.assertEqual(len(set(T.KOCH_ORDER)), 51)
        self.assertEqual(set(T.MORSE), set(T.KOCH_ORDER))
        self.assertEqual(T.MORSE['K'], '-.-')
        self.assertEqual(T.MORSE["'"], '.----.')
        self.assertEqual(T.MORSE['"'], '.-..-.')
        self.assertEqual(len(set(T.MORSE.values())), 51)

    def test_constants(self):
        self.assertEqual(T.ADVANCE_WINDOW, 40)
        self.assertAlmostEqual(T.ADVANCE_ACCURACY, 0.9)
        self.assertEqual(T.NEW_MIN_N, 8)
        self.assertEqual(T.DISCRIM_TRIALS, 12)
        # všechny konstanty z JS jsou v portu použité
        for name in T.CONSTS:
            self.assertTrue(hasattr(T, name), name)

    def test_median(self):
        self.assertIsNone(T.median([]))
        self.assertEqual(T.median([3, 1, 2]), 2)
        self.assertEqual(T.median([1, 2]), 2)  # Math.round(1.5) = 2
        self.assertEqual(T.median([400, 500]), 450)


def simulate(level, p_ok, ttr_fn, rng, new_p_ok=None, n=60):
    chars = T.chars_for_level(level)
    new = chars[-1] if level > 2 else None
    d = T.Drill(chars, new, rng=rng.random)
    for _ in range(n):
        ch = d.next()
        p = new_p_ok if (new_p_ok is not None and ch == new) else p_ok
        ok = rng.random() < p
        d.record(ch, ch if ok else '?', ttr_fn(ch) if ok else None)
    return d


class TestAdvance(unittest.TestCase):
    def test_few(self):
        d = T.Drill(['K', 'M'])
        for _ in range(39):
            d.record('K', 'K', 500)
        self.assertEqual(d.advance_check()['reason'], 'few')

    def test_good_student_advances(self):
        rng = random.Random(1)
        d = simulate(5, 0.99, lambda c: 600, rng)
        self.assertTrue(d.advance_check()['ok'], d.advance_check())

    def test_poor_accuracy(self):
        rng = random.Random(2)
        d = simulate(5, 0.7, lambda c: 600, rng)
        self.assertEqual(d.advance_check()['reason'], 'acc')

    def test_new_char_weak(self):
        # celkově přes 90 %, ale nový znak jen ~60 %
        hits = 0
        for seed in range(20):
            d = simulate(8, 1.0, lambda c: 600, random.Random(seed), new_p_ok=0.6, n=80)
            r = d.advance_check()
            if r['reason'] in ('newAcc', 'acc'):
                hits += 1
        self.assertGreaterEqual(hits, 18)

    def test_new_char_slow(self):
        d = simulate(6, 1.0, lambda c: 1500 if c == 'S' else 600, random.Random(3), n=80)
        r = d.advance_check()
        self.assertEqual(r['reason'], 'newSlow', r)
        self.assertEqual(r['newTtr'], 1500)

    def test_new_char_frequent(self):
        # nový znak má zaznít častěji než průměrný znak
        counts = {}
        for seed in range(10):
            d = simulate(10, 0.95, lambda c: 600, random.Random(seed), n=100)
            for t in d.trials:
                counts[t['ch']] = counts.get(t['ch'], 0) + 1
        avg = sum(counts.values()) / len(counts)
        self.assertGreater(counts['T'], 1.3 * avg)

    def test_no_triple_repeat(self):
        d = simulate(2, 0.9, lambda c: 600, random.Random(4), n=300)
        seq = [t['ch'] for t in d.trials]
        for i in range(2, len(seq)):
            self.assertFalse(seq[i] == seq[i - 1] == seq[i - 2])


class TestPrior(unittest.TestCase):
    def test_prior_weights(self):
        prior = {'K': {'n': 50, 'acc': 0.98, 'ttr': 500},
                 'M': {'n': 50, 'acc': 0.6, 'ttr': 1200},
                 'U': {'n': 2, 'acc': 0.0, 'ttr': 3000}}  # málo dat → výchozí odhad
        d = T.Drill(['K', 'M', 'U'], prior=prior)
        self.assertAlmostEqual(d.prior_err('K'), 0.02)
        self.assertAlmostEqual(d.prior_err('U'), T.DEFAULT_ERR)
        self.assertGreater(d.weight('M'), d.weight('U'))
        self.assertGreater(d.weight('U'), d.weight('K'))

    def test_prior_fades(self):
        prior = {'K': {'n': 50, 'acc': 0.5, 'ttr': 600}, 'M': {'n': 50, 'acc': 0.5, 'ttr': 600}}
        d = T.Drill(['K', 'M'], prior=prior)
        w0 = d.weight('K')
        for _ in range(10):
            d.record('K', 'K', 600)
            d.record('M', 'M', 600)
        self.assertLess(d.weight('K'), w0)

    def test_empty_prior_same_as_old(self):
        d = T.Drill(['K', 'M'])
        self.assertAlmostEqual(d.weight('K'), 1 + 4 * T.DEFAULT_ERR)


class TestTrend(unittest.TestCase):
    def test_arrows(self):
        base = {'n': 40, 'acc': 0.8, 'ttr': 800}
        self.assertEqual(T.trend_arrow({'n': 10, 'acc': 0.95, 'ttr': 800}, base), 'up')
        self.assertEqual(T.trend_arrow({'n': 10, 'acc': 0.6, 'ttr': 800}, base), 'down')
        self.assertEqual(T.trend_arrow({'n': 10, 'acc': 0.82, 'ttr': 790}, base), 'flat')
        self.assertEqual(T.trend_arrow({'n': 10, 'acc': 0.8, 'ttr': 600}, base), 'up')
        self.assertEqual(T.trend_arrow({'n': 10, 'acc': 0.8, 'ttr': 1000}, base), 'down')
        self.assertIsNone(T.trend_arrow({'n': 3, 'acc': 1, 'ttr': 500}, base))
        self.assertIsNone(T.trend_arrow({'n': 10, 'acc': 1, 'ttr': 500}, {'n': 5, 'acc': 0.5, 'ttr': 900}))


class TestDiscrim(unittest.TestCase):
    def test_distance(self):
        self.assertEqual(T.code_distance('K', 'K'), 0)
        self.assertEqual(T.code_distance('K', 'R'), 2)
        self.assertEqual(T.code_distance('S', 'H'), 1)

    def test_contrasts_similar(self):
        known = T.chars_for_level(28)
        c = T.pick_contrasts('H', known)
        self.assertEqual(len(c), 2)
        self.assertEqual(c, ['5', 'V'])  # shoda vzdálenosti 1 (S, 5, V) → později naučené
        for x in c:
            self.assertLessEqual(T.code_distance('H', x), 1)

    def test_contrasts_confusions_first(self):
        known = T.chars_for_level(10)
        self.assertEqual(T.pick_contrasts('T', known, {'K': 3})[0], 'K')

    def test_contrasts_small_set(self):
        self.assertEqual(T.pick_contrasts('M', ['K', 'M']), ['K'])
        self.assertEqual(T.pick_contrasts('M', ['M']), [])

    def test_sequence(self):
        for seed in range(30):
            rng = random.Random(seed).random
            seq = T.discrim_sequence(['H'], ['S', '5'], rng=rng)
            self.assertEqual(len(seq), T.DISCRIM_TRIALS)
            self.assertEqual(seq.count('H'), 6)
            self.assertEqual(seq.count('S') + seq.count('5'), 6)
            self.assertEqual(seq.count('S'), 3)
            for i in range(2, len(seq)):
                self.assertFalse(seq[i] == seq[i - 1] == seq[i - 2], seq)

    def test_sequence_no_contrast(self):
        self.assertEqual(T.discrim_sequence(['K'], [], n=4), ['K'] * 4)


if __name__ == '__main__':
    unittest.main()


class TestM4Mix(unittest.TestCase):
    """Krok 1 M4: úprava M3 podle R1."""

    def test_min_wpm(self):
        self.assertEqual(T.MIN_WPM, 12)
        html = (T.ROOT / 'web/index.html').read_text(encoding='utf-8')
        self.assertIn('data-key="wpm" data-min="12"', html)

    def test_similar_pairs_late(self):
        # malá sada (< 1/3): S proti H/5/V ne, když je nezaměňuje
        known = ['K', 'M', 'U', 'R', 'E', 'S', 'N', 'A', 'P', 'T', 'L', 'W', 'I', 'H', 'V']
        c = T.pick_contrasts('H', known, set_size=len(known))
        for x in c:
            self.assertGreater(T.code_distance('H', x), 1, c)
        # skutečná záměna má přednost i v malé sadě
        self.assertEqual(T.pick_contrasts('H', known, {'S': 2}, set_size=len(known))[0], 'S')
        # od 1/3 sady nejpodobnější
        c = T.pick_contrasts('H', known, set_size=T.DISCRIM_SIMILAR_FROM)
        self.assertLessEqual(T.code_distance('H', c[0]), 1)

    def test_similar_fallback(self):
        # jen podobné znaky k dispozici → raději podobné než žádné
        self.assertEqual(T.pick_contrasts('H', ['S', 'H'], set_size=5), ['S'])

    def _mix_share(self, n_master, n_weak, seed=0):
        chars = T.chars_for_level(n_master + n_weak + 1)
        master = chars[:n_master]
        prior = {c: {'n': 60, 'acc': 0.98, 'ttr': 500} for c in master}
        prior.update({c: {'n': 30, 'acc': 0.7, 'ttr': 900} for c in chars[n_master:-1]})
        d = T.Drill(chars, chars[-1], rng=random.Random(seed).random, prior=prior)
        cnt = 0
        n = 3000
        for _ in range(n):
            ch = d.next()
            cnt += ch in master
            d.record(ch, ch, 600)
            d.trials = d.trials[-12:]  # stabilní okno (bez vlivu lekce)
        return cnt / n

    def test_maintain_share_capped(self):
        share = self._mix_share(20, 4)
        self.assertGreater(share, 0.13)
        self.assertLess(share, 0.22)

    def test_maintain_share_floor(self):
        share = self._mix_share(2, 20)
        self.assertGreater(share, 0.13)

    def test_mastered(self):
        prior = {'K': {'n': 30, 'acc': 0.95, 'ttr': 500}, 'M': {'n': 10, 'acc': 1, 'ttr': 500}}
        d = T.Drill(['K', 'M', 'U'], 'U', prior=prior)
        self.assertTrue(d.is_mastered('K'))
        self.assertFalse(d.is_mastered('M'))   # málo dat
        self.assertFalse(d.is_mastered('U'))   # nový znak
        d.record('K', 'M', None)
        d.record('K', 'M', None)
        self.assertFalse(d.is_mastered('K'))   # v lekci 2 chyby

    def test_new_char_scattered(self):
        for seed in range(10):
            rng = random.Random(seed)
            d = T.Drill(T.chars_for_level(6), 'S', rng=rng.random)
            prev = None
            for _ in range(200):
                ch = d.next()
                if ch == 'S':
                    self.assertNotEqual(prev, 'S')
                d.record(ch, ch if rng.random() < 0.8 else '?', 600)
                prev = ch


def run_student(skill, reg, seed, n=300):
    rng = random.Random(seed)
    chars = list(skill)
    prior = {c: {'n': 40, 'acc': skill[c], 'ttr': 600} for c in chars}
    d = T.Drill(chars, chars[-1], rng=rng.random, prior=prior)
    d.regulation = reg
    for _ in range(n):
        ch = d.next()
        ok = rng.random() < skill[ch]
        d.record(ch, ch if ok else '?', 600 if ok else None)
    w = d.trials[100:]
    return sum(t['ok'] for t in w) / len(w), d


class TestRegulation(unittest.TestCase):
    """Krok 2 M4: smyčka a – cíl ~85 %, pásmo 80–90 %."""

    def test_band_constants(self):
        self.assertAlmostEqual(T.BAND_LO, 0.8)
        self.assertAlmostEqual(T.BAND_HI, 0.9)

    def test_easier_when_struggling(self):
        chars = T.chars_for_level(12)
        skill = {c: 0.85 for c in chars}
        skill.update({c: 0.55 for c in chars[-5:]})
        off = sum(run_student(skill, False, s)[0] for s in range(15)) / 15
        on = [run_student(skill, True, s) for s in range(15)]
        acc_on = sum(a for a, _ in on) / 15
        self.assertGreater(acc_on, off + 0.015)
        self.assertLess(sum(d.diff for _, d in on) / 15, 1)

    def test_harder_when_too_easy(self):
        d = T.Drill(T.chars_for_level(6), 'S', rng=random.Random(3).random)
        for _ in range(60):
            ch = d.next()
            d.record(ch, ch, 500)
        self.assertGreater(d.diff, 1)
        self.assertLessEqual(d.diff, T.DIFF_MAX)
        self.assertTrue(d.diff_log)

    def test_floor(self):
        d = T.Drill(T.chars_for_level(6), 'S', rng=random.Random(4).random)
        for _ in range(200):
            ch = d.next()
            d.record(ch, '?', None)
        self.assertAlmostEqual(d.diff, T.DIFF_MIN)

    def test_steps_spaced(self):
        d = T.Drill(T.chars_for_level(6), 'S', rng=random.Random(5).random)
        for _ in range(100):
            ch = d.next()
            d.record(ch, ch, 500)
        steps = [a for a, _ in d.diff_log]
        self.assertTrue(all(b - a >= T.DIFF_EVERY for a, b in zip(steps, steps[1:])))


class TestTtrStable(unittest.TestCase):
    def test_unstable_blocks(self):
        d = T.Drill(['K', 'M', 'U'], 'U')
        for i in range(40):
            ch = 'KMU'[i % 3]
            d.record(ch, ch, 500 if i < 20 else 800)
        self.assertEqual(d.advance_check()['reason'], 'ttrUnstable')

    def test_stable_ok(self):
        d = T.Drill(['K', 'M', 'U'], 'U')
        for i in range(40):
            ch = 'KMU'[i % 3]
            d.record(ch, ch, 500 if i < 20 else 560)
        self.assertTrue(d.advance_check()['ok'], d.advance_check())


class TestExclude(unittest.TestCase):
    def test_warmup_exclude(self):
        d = T.Drill(T.chars_for_level(5), 'R', rng=random.Random(1).random)
        d.set_exclude(['R'])
        for _ in range(50):
            ch = d.next()
            self.assertNotEqual(ch, 'R')
            d.record(ch, ch, 500)
        d.set_exclude([])
        self.assertGreater(d.weight('R'), 0)

    def test_exclude_keeps_two(self):
        d = T.Drill(['K', 'M'], 'M')
        d.set_exclude(['M'])
        self.assertEqual(d.exclude, set())


class TestGapEase(unittest.TestCase):
    """M6: prodloužení mezer v lekci až po vyčerpání ulehčení mixem."""

    def test_struggling_gets_longer_gaps_then_floor(self):
        d = T.Drill(T.chars_for_level(6), 'S', rng=random.Random(7).random)
        for _ in range(120):
            ch = d.next()
            d.record(ch, '?', None)
        self.assertEqual(d.gap_ease, T.GAP_EASE_MAX)
        self.assertEqual(d.lesson_fwpm(15), 15 - T.GAP_EASE_STEP * T.GAP_EASE_MAX)
        self.assertEqual(d.lesson_fwpm(6), T.FW_MIN)
        # krok mezer až po dosažení DIFF_MIN
        first_gap = d.gap_log[0][0]
        first_min = next(n for n, v in d.diff_log if v <= T.DIFF_MIN + 1e-9)
        self.assertGreaterEqual(first_gap, first_min)
        steps = [a for a, _ in d.gap_log]
        self.assertTrue(all(b - a >= T.GAP_EVERY for a, b in zip(steps, steps[1:])))

    def test_recovers(self):
        d = T.Drill(T.chars_for_level(6), 'S', rng=random.Random(8).random)
        for _ in range(120):
            ch = d.next()
            d.record(ch, '?', None)
        for _ in range(80):
            ch = d.next()
            d.record(ch, ch, 500)
        self.assertEqual(d.gap_ease, 0)
        self.assertEqual(d.lesson_fwpm(15), 15)

    def test_good_student_never(self):
        d = T.Drill(T.chars_for_level(10), 'A', rng=random.Random(9).random)
        rng = random.Random(10)
        for _ in range(200):
            ch = d.next()
            d.record(ch, ch if rng.random() < 0.85 else '?', 600)
        self.assertEqual(d.gap_ease, 0)

    def test_fw_min_matches_server(self):
        from server import coach as C
        self.assertEqual(T.FW_MIN, C.FW_MIN)


class TestMix085(unittest.TestCase):
    """0.8.4 (validace #4, #5): strop nového znaku, záměny zvyšují četnost, srovnání bez nového znaku."""

    def prior(self, conf=None):
        chars = T.chars_for_level(17)
        p = {c: {'n': 60, 'acc': 0.98, 'ttr': 1100} for c in chars[:-1]}
        for c, lst in (conf or {}).items():
            p[c]['conf'] = lst
        return chars, p

    def shares(self, prior, chars, seeds=30, n=175):
        cnt = {}
        for seed in range(seeds):
            rng = random.Random(seed)
            d = T.Drill(chars, chars[-1], rng=rng.random, prior=prior)
            for _ in range(n):
                ch = d.next()
                ttr = 650 if ch == chars[-1] else int(rng.gauss(1100, 150))
                d.record(ch, ch if rng.random() < 0.98 else '?', ttr)
                cnt[ch] = cnt.get(ch, 0) + 1
        tot = sum(cnt.values())
        return {c: cnt.get(c, 0) / tot for c in chars}

    def test_new_char_share_capped(self):
        chars, p = self.prior()
        sh = self.shares(p, chars)
        self.assertLess(sh[chars[-1]], T.NEW_SHARE_MAX + 0.02)
        self.assertGreater(sh[chars[-1]], 0.15)  # pořád nejčastější znak
        self.assertEqual(max(sh, key=sh.get), chars[-1])

    def test_confusions_raise_both_chars(self):
        chars, p = self.prior({'W': [{'ans': 'J', 'n': 10}], 'P': [{'ans': 'L', 'n': 2}]})
        base = self.shares(self.prior()[1], chars)
        sh = self.shares(p, chars)
        for c in 'WJ':
            self.assertGreater(sh[c], base[c] * 1.3, c)
        calm = sorted(sh[c] for c in chars[:-1] if c not in 'WJLP')
        for c in 'LP':
            self.assertGreater(sh[c], calm[len(calm) // 2], c)

    def test_new_char_enough_for_advance(self):
        chars, p = self.prior()
        rng = random.Random(2)
        d = T.Drill(chars, chars[-1], rng=rng.random, prior=p)
        for _ in range(175):
            ch = d.next()
            d.record(ch, ch, 650 if ch == chars[-1] else 1100)
        self.assertGreaterEqual(d.stats[chars[-1]]['n'], 2 * T.NEW_MIN_N)

    def test_stable_ttr_ignores_mix(self):
        # 1. polovina okna: hodně rychlého nového znaku, 2. polovina: staré znaky → prosté TTR „nestabilní“
        chars, p = self.prior()
        d = T.Drill(chars, chars[-1], prior=p)
        old = chars[:-1]
        win1 = [{'ch': chars[-1] if i % 2 else old[i % 16], 'ok': True, 'ttr': 650 if i % 2 else 1100} for i in range(20)]
        win2 = [{'ch': old[i % 16], 'ok': True, 'ttr': 1150} for i in range(20)]
        t1, t2 = d.stable_ttrs(win1, win2)
        self.assertLess(t2 / t1, T.TTR_STABLE_RATIO)
        d2 = T.Drill(chars, chars[-1])  # bez dlouhodobé statistiky → prosté TTR
        t1, t2 = d2.stable_ttrs(win1, win2)
        self.assertGreater(t2 / t1, T.TTR_STABLE_RATIO)
