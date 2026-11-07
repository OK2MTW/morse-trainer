# SPDX-License-Identifier: EUPL-1.2
"""Tests of the coach over lessons (Python port of coach.js, M4)."""
import unittest
from pathlib import Path

from tests import coach as C

H = 3600000


def iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')


class TestConfig(unittest.TestCase):
    def test_constants_used(self):
        for name in C.CONSTS:
            self.assertTrue(hasattr(C, name), name)


class TestTraceOrder(unittest.TestCase):
    """0.10.11: lesson-end debug events must be written before traceEnd (after it tr() is a no-op)."""

    def test_pace_events_before_trace_end(self):
        src = (Path(__file__).resolve().parent.parent / 'web/js/main.js').read_text(encoding='utf-8')
        end = src.index('traceEnd(saved.id')
        for ev in ("tr('pace'", "tr('pwEnd'"):
            self.assertLess(src.index(ev), end, ev)


class TestLessonPace(unittest.TestCase):
    """0.9.8 (validation #17): slow day = the whole lesson against the long-term reaction to the same characters."""
    REF = {'K': 800, 'M': 1000}

    def trials(self, factor, n=40):
        return [{'ch': 'KM'[i % 2], 'ok': True, 'ttr': round(self.REF['KM'[i % 2]] * factor)} for i in range(n)]

    def test_pace(self):
        self.assertAlmostEqual(C.lesson_pace(self.trials(1.3), self.REF), 1.3, places=2)
        self.assertGreaterEqual(C.lesson_pace(self.trials(1.3), self.REF), C.SLOW_DAY)
        self.assertLess(C.lesson_pace(self.trials(1.05), self.REF), C.SLOW_DAY)

    def test_not_enough(self):
        self.assertIsNone(C.lesson_pace(self.trials(1.3, n=C.SLOW_DAY_MIN_N - 1), self.REF))
        self.assertIsNone(C.lesson_pace(self.trials(1.3), None))
        wrong = [dict(t, ok=False) for t in self.trials(1.3)]
        self.assertIsNone(C.lesson_pace(wrong, self.REF))

    def test_unknown_and_new_char_skipped(self):
        ts = self.trials(1.0) + [{'ch': 'X', 'ok': True, 'ttr': 9000}] * 50
        self.assertAlmostEqual(C.lesson_pace(ts, self.REF), 1.0, places=2)
        self.assertAlmostEqual(C.lesson_pace(self.trials(1.0, n=80), self.REF, new_char='K'), 1.0, places=2)


class TestConfirm(unittest.TestCase):
    NOW = 1_800_000_000_000

    def test_early_levels_free(self):
        self.assertTrue(C.confirm_gate([], 3, self.NOW)['ok'])

    def test_same_session_blocked(self):
        hist = [{'at': iso(self.NOW - H), 'level': 8}, {'at': iso(self.NOW), 'level': 8}]
        g = C.confirm_gate(hist, 8, self.NOW)
        self.assertFalse(g['ok'])
        self.assertEqual(g['reason'], 'confirm')
        self.assertAlmostEqual(g['waitH'], 2.0)

    def test_next_session_ok(self):
        hist = [{'at': iso(self.NOW - 20 * H), 'level': 8}, {'at': iso(self.NOW - 19 * H), 'level': 7},
                {'at': iso(self.NOW), 'level': 8}]
        self.assertTrue(C.confirm_gate(hist, 8, self.NOW)['ok'])

    def test_first_lesson_of_level(self):
        hist = [{'at': iso(self.NOW - 30 * H), 'level': 7}, {'at': iso(self.NOW), 'level': 8}]
        self.assertFalse(C.confirm_gate(hist, 8, self.NOW)['ok'])


M = 60000


class TestLoad(unittest.TestCase):
    NOW = 1_800_000_000_000
    DAY = NOW - 10 * H  # local midnight

    def les(self, end_min_ago, dur_min):
        return {'at': iso(self.NOW - end_min_ago * M), 'durS': dur_min * 60}

    def test_empty(self):
        r = C.session_load([], self.NOW, self.DAY)
        self.assertEqual(r['sessionMin'], 0)
        self.assertTrue(r['newSession'])
        self.assertIsNone(r['gapH'])

    def test_session_chain(self):
        # 3 blocks of 10 min with short breaks → 30 min → suggest stopping
        hist = [self.les(25, 10), self.les(13, 10), self.les(1, 10)]
        r = C.session_load(hist, self.NOW, self.DAY)
        self.assertEqual(r['sessionMin'], 30)
        self.assertTrue(r['suggestEnd'])
        self.assertFalse(r['newSession'])

    def test_break_splits(self):
        hist = [self.les(120, 10), self.les(60, 10), self.les(2, 5)]
        r = C.session_load(hist, self.NOW, self.DAY)
        self.assertEqual(r['sessionMin'], 5)
        self.assertEqual(r['dayMin'], 25)
        self.assertFalse(r['suggestEnd'])

    def test_new_session_after_break(self):
        r = C.session_load([self.les(30, 10)], self.NOW, self.DAY)
        self.assertTrue(r['newSession'])
        self.assertEqual(r['gapH'], 0.5)

    def test_day_warn(self):
        hist = [self.les(m, 10) for m in (500, 400, 300, 200, 100, 50, 30)]
        r = C.session_load(hist, self.NOW, self.DAY)
        self.assertEqual(r['dayMin'], 70)
        self.assertTrue(r['dayWarn'])
        # yesterday's lessons do not count
        r = C.session_load([self.les(11 * 60, 10)], self.NOW, self.DAY)
        self.assertEqual(r['dayMin'], 0)

    def test_warmup(self):
        tr = [{'ok': True, 'ttr': 500}, {'ok': False, 'ttr': None}, {'ok': True, 'ttr': 700}, {'ok': True, 'ttr': 600}]
        self.assertEqual(C.warmup_stats(tr, 18.25), {'n': 4, 'acc': 0.75, 'ttr': 600, 'gapH': 18.3})
        self.assertIsNone(C.warmup_stats([], 1))

    def test_fatigue(self):
        self.assertTrue(C.fatigue_signal({'acc': 0.9, 'ttr': 600}, {'acc': 0.9, 'ttr': 760})['tired'])
        self.assertTrue(C.fatigue_signal({'acc': 0.9, 'ttr': 600}, {'acc': 0.8, 'ttr': 600})['tired'])
        self.assertFalse(C.fatigue_signal({'acc': 0.9, 'ttr': 600}, {'acc': 0.85, 'ttr': 700})['tired'])
        self.assertFalse(C.fatigue_signal(None, {'acc': 0.5, 'ttr': 1})['tired'])


class TestPaceWatch(unittest.TestCase):
    """0.10.5 (Z-17, shadow): fatigue against the long-term reaction during a lesson (validation #17)."""
    REF = {'K': 800, 'M': 900, 'R': 1000}

    def feed(self, ratios, ok=None, dt=2.3, ref=REF, count=True):
        w = C.PaceWatch(ref)
        chars = list(self.REF)
        props = []
        for i, r in enumerate(ratios):
            ch = chars[i % 3]
            res = w.add({'ch': ch, 'ok': True if ok is None else ok[i], 'ttr': round(self.REF[ch] * r)}, i * dt, count)
            if res['propose']:
                props.append(i * dt)
        return w, props

    def test_usual_pace_is_silent(self):
        w, props = self.feed([1.0, 1.1, 0.95, 1.17] * 60)  # a normal morning (max window 1.17 in the backtest)
        self.assertEqual(props, [])
        self.assertLess(w.max['med'], C.PACE_ON)

    def test_tired_from_the_start(self):
        """The session-start baseline cannot see this; the long-term reference can."""
        w, props = self.feed([1.35] * 200)
        self.assertTrue(props)
        # signal from PACE_MIN_REL trials on, proposal after PACE_HOLD_S
        self.assertLessEqual(props[0], (C.PACE_MIN_REL + 1) * 2.3 + C.PACE_HOLD_S + 2.3)
        self.assertGreaterEqual(props[0], C.PACE_HOLD_S)

    def test_hysteresis_keeps_the_signal(self):
        """Once on, a window between PACE_OFF and PACE_ON does not interrupt it (the old detector restarted the hold)."""
        seq = [1.4] * 40 + [1.2] * 60
        _, props = self.feed(seq)
        self.assertTrue(props)
        _, props = self.feed([1.0] * 40 + [1.2] * 60)  # never above PACE_ON → nothing
        self.assertEqual(props, [])

    def test_lapses(self):
        """Microsleeps: 6 of 20 reactions ≥ 2× the usual one switch the signal on even with a normal median."""
        seq = ([1.0] * 7 + [2.5] * 3) * 30   # 6 lapses per 20, median 1.0
        _, props = self.feed(seq)
        self.assertTrue(props)
        _, props = self.feed(([1.0] * 9 + [2.5]) * 30)  # 2 per 20 → nothing
        self.assertEqual(props, [])
        ok = ([True] * 7 + [False] * 3) * 30  # wrong answers count as lapses too
        _, props = self.feed([1.0] * 300, ok=ok)
        self.assertTrue(props)

    def test_no_reference_or_warmup(self):
        self.assertEqual(self.feed([2.0] * 200, ref=None)[1], [])
        self.assertEqual(self.feed([2.0] * 200, count=False)[1], [])

    def test_reset_after_proposal_and_pause(self):
        w, props = self.feed([1.4] * 300)
        self.assertGreaterEqual(len(props), 2)
        self.assertGreater(props[1] - props[0], C.PACE_HOLD_S)  # measured anew after each would-be proposal
        self.assertEqual(len(w.events), len(props))
        w.reset()
        self.assertEqual(w.win, [])

    def test_js_wired_in_shadow_mode(self):
        """Owner 2026-11-07: shadow only – the lesson writes 'pw' to the trace and never proposes a pause from it."""
        main = (Path(__file__).resolve().parent.parent / 'web/js/main.js').read_text()
        self.assertIn("L.paceWatch.add(", main)
        self.assertIn("tr('pw'", main)
        self.assertNotRegex(main, r"pw\.propose[^\n]*fatPending")


class TestFatigueMonitor(unittest.TestCase):
    """Lesson simulation: a trial every 2 s, TTR and accuracy by scenario."""

    def run_sim(self, phases, base=None, snooze_at=None):
        import random
        rng = random.Random(7)
        m = C.FatigueMonitor(base)
        t, first = 0, None
        for dur_s, acc, ttr in phases:
            end = t + dur_s
            while t < end:
                ok = rng.random() < acc
                r = m.add({'ok': ok, 'ttr': int(rng.gauss(ttr, ttr * 0.15)) if ok else None}, t)
                if r['propose'] and first is None:
                    first = (t, r['kind'])
                    if snooze_at is not None:
                        m.snooze(t)
                t += 2
        return first, m

    def test_steady_no_proposal(self):
        first, _ = self.run_sim([(600, 0.9, 500)])
        self.assertIsNone(first)

    def test_slowing_ttr_proposes_after_hold(self):
        first, _ = self.run_sim([(120, 0.9, 500), (300, 0.9, 700)])
        self.assertIsNotNone(first)
        self.assertEqual(first[1], 'ttr')
        self.assertGreater(first[0], 120 + C.FATIGUE_HOLD_S)

    def test_short_blip_ignored(self):
        first, _ = self.run_sim([(120, 0.9, 500), (30, 0.9, 750), (300, 0.9, 500)])
        self.assertIsNone(first)

    def test_acc_drop_within_band_ignored(self):
        # difficulty control may move accuracy to 82 % – that is not fatigue
        first, _ = self.run_sim([(120, 0.95, 500), (400, 0.83, 500)])
        self.assertIsNone(first)

    def test_acc_below_band_proposes(self):
        first, _ = self.run_sim([(120, 0.92, 500), (400, 0.65, 500)])
        self.assertIsNotNone(first)
        self.assertEqual(first[1], 'acc')

    def test_base_from_earlier_lesson(self):
        base = {'acc': 0.9, 'ttr': 500, 'n': 30}
        first, m = self.run_sim([(300, 0.9, 700)], base=base)
        self.assertIs(m.base, base)
        self.assertIsNotNone(first)
        self.assertLess(first[0], 150)  # without collecting a baseline: a window of 20 trials (40 s) + 60 s

    def test_warmup_not_counted(self):
        m = C.FatigueMonitor()
        for i in range(50):
            m.add({'ok': False, 'ttr': None}, i, count=False)
        self.assertIsNone(m.base)

    def test_snooze(self):
        import random
        rng = random.Random(3)
        m = C.FatigueMonitor({'acc': 0.9, 'ttr': 500, 'n': 30})
        props = []
        for t in range(0, 600, 2):
            ok = rng.random() < 0.9
            r = m.add({'ok': ok, 'ttr': 750 if ok else None}, t)
            if r['propose']:
                props.append(t)
                m.snooze(t)
        self.assertGreaterEqual(len(props), 2)
        self.assertGreaterEqual(props[1] - props[0], C.FATIGUE_SNOOZE_S)


class TestFatigueRelative(unittest.TestCase):
    """0.8.4 (validation #1): fatigue against the reaction to the same character, the new character does not count."""
    OLD = list('KMURESNAPTLWIJZ.')
    REF = {c: 1100 for c in OLD}

    def sim(self, phases, ref, seed=5):
        import random
        rng = random.Random(seed)
        m = C.FatigueMonitor(None, ref=ref, new_char='=')
        t, first = 0, None
        for dur_s, new_share, slow in phases:
            end = t + dur_s
            while t < end:
                if rng.random() < new_share:
                    tr = {'ch': '=', 'ok': True, 'ttr': int(rng.gauss(650, 80))}
                else:
                    tr = {'ch': rng.choice(self.OLD), 'ok': True, 'ttr': int(rng.gauss(1100 * slow, 150))}
                r = m.add(tr, t)
                if r['propose'] and first is None:
                    first = t
                t += 2
        return first, m

    def test_mix_shift_is_not_fatigue(self):
        # start: new character 45 % (fast), later 15 % → plain TTR grows, the reaction per character does not
        self.assertIsNotNone(self.sim([(80, 0.45, 1), (340, 0.15, 1)], None)[0])
        first, m = self.sim([(80, 0.45, 1), (340, 0.15, 1)], self.REF)
        self.assertIsNone(first)
        self.assertTrue(m.base['rel'])

    def test_real_slowdown_detected(self):
        first, _ = self.sim([(100, 0.3, 1), (320, 0.3, 1.4)], self.REF)
        self.assertIsNotNone(first)

    def test_new_char_slowdown_ignored(self):
        import random
        rng = random.Random(1)
        m = C.FatigueMonitor(None, ref=self.REF, new_char='=')
        props = []
        for t in range(0, 420, 2):
            new = rng.random() < 0.3
            ttr = (2500 if t > 100 else 650) if new else int(rng.gauss(1100, 150))
            if m.add({'ch': '=' if new else 'K', 'ok': True, 'ttr': ttr}, t)['propose']:
                props.append(t)
        self.assertEqual(props, [])

    def test_base_mode_must_match(self):
        raw = {'acc': 0.9, 'ttr': 1100, 'n': 30}
        self.assertIsNone(C.FatigueMonitor(raw, ref=self.REF).base)
        rel = {'acc': 0.9, 'ttr': 1000, 'n': 30, 'rel': True}
        self.assertIs(C.FatigueMonitor(rel, ref=self.REF).base, rel)
        self.assertIsNone(C.FatigueMonitor(rel).base)

    def test_ref_from_prior(self):
        self.assertIsNone(C.fatigue_ref({}))
        self.assertEqual(C.fatigue_ref({'K': {'n': 10, 'ttr': 800}, 'M': {'n': 2, 'ttr': 900}}), {'K': 800})

    def test_held_flag(self):
        m = C.FatigueMonitor({'acc': 1, 'ttr': 1000, 'n': 30, 'rel': True}, ref=self.REF, new_char='=')
        for t in range(0, 50, 2):
            m.add({'ch': 'K', 'ok': True, 'ttr': 1600}, t)
        self.assertTrue(m.last['tired'])
        self.assertFalse(m.last['held'])
        for t in range(50, 140, 2):
            m.add({'ch': 'K', 'ok': True, 'ttr': 1600}, t)
        self.assertTrue(m.last['held'])
