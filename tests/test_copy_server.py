# SPDX-License-Identifier: EUPL-1.2
"""Tests of the server coach for copy behind (M7, M8): ladder of steps, U3 → U4 → U5, separation of modes."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from server import coach as C

T0 = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
GOOD = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 500} for c in C.KOCH]


def at(h):
    return (T0 + timedelta(hours=h)).isoformat().replace("+00:00", "Z")


def Z(h, ttr=500, fwpm=20, acc=0.95, per=GOOD):
    return {"at": at(h), "mode": "znak", "level": 51, "dur_s": 300, "trials": 200, "acc": acc, "ttr": ttr,
            "wpm": 20, "fwpm": fwpm, "device": "pc", "detail": json.dumps({"perChar": per})}


def S(h, step=1, acc=0.92, n=80, drift=0, lag=0.6, wpm=20, fwpm=20, words=None):
    ok = round(acc * n)
    det = {"copy": {"step": step, "ok": ok, "sub": n - ok, "del": 0, "ins": 0, "n": n, "acc": acc,
                    "lagCh": lag, "lagMs": 400, "drift": drift}}
    if words is not None:
        det["copy"]["words"] = {"n": 20, "ok": round(words * 20)}
    return {"at": at(h), "mode": "skluz", "level": 51, "dur_s": 300, "trials": n, "acc": acc, "ttr": None,
            "wpm": wpm, "fwpm": fwpm, "device": "pc", "detail": json.dumps(det)}


U3 = [Z(0), Z(20), Z(40)]  # 2 sessions at 20/20 with a fast reaction → U3


class TestModes(unittest.TestCase):
    def test_u3_from_znak_only(self):
        self.assertEqual(C.computed_ulevel(U3, 51), 3)
        # copy-behind lessons spoil neither the character statistics nor U2 (they have no perChar or TTR)
        self.assertEqual(C.computed_ulevel(U3 + [S(41), S(60, acc=0.5)], 51), 3)
        self.assertEqual(C.u1_status(U3 + [S(41)] * 30, 51)["good"], 44)  # 0.9.6: main programme

    def test_speed_ignores_copy(self):
        ls = [Z(0, fwpm=15), Z(20, fwpm=15)]
        a = C.speed_advice(ls, 51, 2, {"wpm": 20, "fwpm": 15})
        self.assertEqual(a["change"]["kind"], "gaps")
        # sessions with copy behind only (same pace) do not count for the pace
        b = C.speed_advice([Z(0, fwpm=15), S(20, wpm=20, fwpm=15)], 51, 2, {"wpm": 20, "fwpm": 15})
        self.assertIsNone(b["change"])

    def test_mastered_chars(self):
        weak = [dict(x) for x in GOOD]
        weak[0]["acc"] = 0.5  # K
        m = C.mastered_chars([Z(0, per=weak)])
        self.assertNotIn("K", m)
        self.assertEqual(len(m), 50)
        self.assertEqual(m[0], "M")


class TestEarlyCopy(unittest.TestCase):
    """Z-16 (0.9.9): trial copy behind before U3 – from COPY_EARLY_MIN mastered characters, steps 1–2 only."""
    FEW = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 500} for c in C.KOCH[:12]]

    def base(self, chars):
        return [Z(0, per=self.FEW[:chars], fwpm=12)]

    def test_available_from_min_chars(self):
        self.assertFalse(C.copy_advice(self.base(C.COPY_EARLY_MIN - 1), 1)["available"])
        a = C.copy_advice(self.base(C.COPY_EARLY_MIN), 1)
        self.assertTrue(a["available"] and a["early"])
        self.assertEqual(a["chars"], list(C.KOCH[:C.COPY_EARLY_MIN]))
        self.assertEqual((a["step"], a["content"]), (1, "groups"))
        self.assertIn(str(C.COPY_EARLY_LAST), a["next"])

    def test_capped_at_step_2(self):
        ls = self.base(12)
        ls += [S(10, step=1), S(30, step=1)]
        self.assertEqual(C.copy_advice(ls, 1)["change"]["to"], 2)  # up 1 → 2 like in U3
        ls += [S(50, step=2), S(70, step=2)]
        a = C.copy_advice(ls, 1)
        self.assertEqual(a["step"], C.COPY_EARLY_LAST)
        self.assertIsNone(a["change"])  # no step 3 before U3
        ls += [S(90, step=2, acc=0.6), S(110, step=2, acc=0.6)]
        self.assertEqual(C.copy_advice(ls, 1)["change"]["kind"], "ease")

    def test_no_u4_from_trial(self):
        ls = self.base(12) + [S(h, step=2, acc=0.99) for h in (10, 30, 50, 70)]
        self.assertLess(C.computed_ulevel(ls, 12), 3)

    def test_u3_continues_from_trial_step(self):
        ls = U3 + [S(41, step=2), S(42, step=2, acc=0.8)]
        a = C.copy_advice(ls, 3)
        self.assertFalse(a["early"])
        self.assertEqual(a["step"], 2)


class TestLadder(unittest.TestCase):
    def test_start(self):
        a = C.copy_advice(U3, 3)
        self.assertTrue(a["available"])
        self.assertEqual((a["step"], a["content"], a["gapX"]), (1, "groups", 3.0))
        self.assertIsNone(a["change"])
        # Z-16 (0.9.9): below U3 only a trial from mastered characters (here the whole set is mastered)
        early = C.copy_advice(U3[:1], 2)
        self.assertTrue(early["available"] and early["early"])
        self.assertFalse(a["early"])

    def test_up_after_two_sessions(self):
        self.assertIsNone(C.copy_advice(U3 + [S(41)], 3)["change"])
        # two lessons in one session = one session
        self.assertIsNone(C.copy_advice(U3 + [S(41), S(41.1)], 3)["change"])
        a = C.copy_advice(U3 + [S(41), S(60)], 3)
        self.assertEqual(a["change"]["kind"], "up")
        self.assertEqual(a["step"], 2)
        self.assertEqual(a["gapX"], 2.0)

    def test_new_step_waits_for_new_data(self):
        a = C.copy_advice(U3 + [S(41), S(60), S(80, step=2)], 3)
        self.assertIsNone(a["change"])
        self.assertEqual(a["step"], 2)

    def test_short_session_skipped(self):
        a = C.copy_advice(U3 + [S(41), S(60, n=30)], 3)
        self.assertIsNone(a["change"])

    def test_ease(self):
        a = C.copy_advice(U3 + [S(41, step=3, acc=0.6), S(60, step=3, acc=0.7)], 3)
        self.assertEqual((a["change"]["kind"], a["step"]), ("ease", 2))
        self.assertIsNone(C.copy_advice(U3 + [S(41, acc=0.6), S(60, acc=0.7)], 3)["change"])  # step 1 is the lowest

    def test_mid_band_stays(self):
        self.assertIsNone(C.copy_advice(U3 + [S(41, acc=0.85), S(60, acc=0.95)], 3)["change"])

    def test_last_step_no_further(self):
        last = C.COPY_U3_LAST
        a = C.copy_advice(U3 + [S(41, step=last), S(60, step=last)], 3)
        self.assertIsNone(a["change"])
        self.assertEqual(a["gapX"], 1.0)

    def test_steps_one_change_at_a_time(self):
        # markLag is only the timing of feedback, not difficulty; wpm None = 20 WPM from the settings (U3)
        for a, b in zip(C.COPY_STEPS, C.COPY_STEPS[1:]):
            changed = (a["content"] != b["content"]) + (a["gapX"] != b["gapX"]) + ((a["wpm"] or 20) != (b["wpm"] or 20)) \
                + (a.get("band") != b.get("band"))  # M9: the band situation is a change too
            self.assertEqual(changed, 1, (a, b))
        self.assertEqual([s["step"] for s in C.COPY_STEPS], list(range(1, len(C.COPY_STEPS) + 1)))

    def test_simulated_path(self):
        # a student always at 92 % → a step up every 2 sessions → step 6 after 10 sessions, then U4
        ls = list(U3)
        h = 41
        for _ in range(14):
            a = C.copy_advice(ls, 3)
            ls.append(S(h, step=a["step"]))
            h += 20
        self.assertEqual(C.copy_advice(ls, 3)["step"], 6)
        self.assertEqual(C.computed_ulevel(ls, 51), 4)


class TestU4(unittest.TestCase):
    def test_criteria(self):
        last = C.COPY_U3_LAST
        ok = U3 + [S(41, step=last), S(60, step=last)]
        self.assertEqual(C.computed_ulevel(ok, 51), 4)
        self.assertEqual(C.level_info(ok, 51, 3)["ulevel"], 4)
        # one session is not enough
        self.assertEqual(C.computed_ulevel(U3 + [S(41, step=last)], 51), 3)
        # not with a lag that runs away
        self.assertEqual(C.computed_ulevel(U3 + [S(41, step=last), S(60, step=last, drift=2)], 51), 3)
        # not on a lower step
        self.assertEqual(C.computed_ulevel(U3 + [S(41, step=5), S(60, step=5)], 51), 3)
        # not at a slower pace
        self.assertEqual(C.computed_ulevel(U3 + [S(41, step=last, fwpm=18), S(60, step=last, fwpm=18)], 51), 3)
        # character-only sessions in between do not matter
        self.assertEqual(C.computed_ulevel(U3 + [S(41, step=last), Z(50), S(60, step=last)], 51), 4)

    def test_stored_u3_without_znak_data(self):
        last = C.COPY_U3_LAST
        self.assertEqual(C.computed_ulevel([S(41, step=last), S(60, step=last)], 51, stored=3), 4)
        self.assertEqual(C.computed_ulevel([S(41, step=last), S(60, step=last)], 51, stored=2), 1)

    def test_next_criteria_u3(self):
        nc = C.next_criteria(3, U3 + [S(41)], 51)
        self.assertEqual(nc["target"], 4)
        self.assertTrue(any("step 1" in x for x in nc["items"]))


class TestDashboardCopy(unittest.TestCase):
    def test_sessions_split(self):
        ls = U3 + [S(41, acc=0.8, lag=1.5), S(60, step=2, acc=0.9)]
        now = (T0 + timedelta(hours=61)).timestamp() * 1000
        d = C.dashboard(ls, 51, {}, now)
        ses = d["sessions"]
        self.assertEqual(len(ses), 5)
        self.assertIsNone(ses[-1]["acc"])  # a copy-only session has no character accuracy
        self.assertIsNone(ses[-1]["ttr"])
        self.assertEqual(ses[-1]["copy"]["step"], 2)
        self.assertEqual(ses[-2]["copy"]["lagCh"], 1.5)
        self.assertIsNone(ses[0]["copy"])
        self.assertAlmostEqual(ses[0]["acc"], 0.95)
        # minutes are counted from all lessons
        self.assertEqual(sum(x["min"] for x in d["days"]), 25)


class TestU4Ladder(unittest.TestCase):
    U4 = U3 + [S(41, step=6), S(60, step=6)]  # 2 sessions on step 6 → U4

    def test_gate_u3_to_u4(self):
        # at U3 with an unmet criterion (drift) there is no advance from step 6
        ls = U3 + [S(41, step=6, drift=2), S(60, step=6, drift=2)]
        self.assertEqual(C.computed_ulevel(ls, 51), 3)
        a = C.copy_advice(ls, 3)
        self.assertIsNone(a["change"])
        self.assertIn("U4 opens", a["next"])
        # s U4 krok 7
        self.assertEqual(C.computed_ulevel(self.U4, 51), 4)
        a = C.copy_advice(self.U4, 4)
        self.assertEqual((a["step"], a["content"], a["wpm"], a["ulevel"]), (7, "abbr", 20, 4))
        self.assertIn("20 WPM", a["change"]["text"])

    def test_u4_steps(self):
        st = {s["step"]: s for s in C.COPY_STEPS}
        self.assertEqual([st[k]["content"] for k in range(7, 14)], ["abbr", "calls", "long", "mix", "mix", "mix", "mix"])
        self.assertEqual([st[k]["wpm"] for k in range(10, 14)], [20, 21, 23, 25])
        self.assertTrue(all(st[k]["markLag"] == 2 for k in range(9, 14)))
        self.assertTrue(all(st[k]["markLag"] == 1 and st[k]["wpm"] is None for k in range(1, 7)))

    def test_simulated_u4_path(self):
        ls = list(self.U4)
        h = 80
        for _ in range(16):
            a = C.copy_advice(ls, 4)
            ls.append(S(h, step=a["step"], wpm=a["wpm"] or 20, fwpm=a["wpm"] or 20, drift=2, words=0.85))
            h += 20
        self.assertEqual(C.copy_advice(ls, 4)["step"], C.COPY_U4_LAST)
        self.assertLess(C.computed_ulevel(ls, 51, stored=4), 5)  # words only 85 % → no U5

    def test_u5_criteria(self):
        last = C.COPY_U4_LAST
        ok = self.U4 + [S(80, step=last, wpm=25, fwpm=25, words=0.92, drift=2),
                        S(100, step=last, wpm=25, fwpm=25, words=0.95, drift=3)]
        self.assertEqual(C.computed_ulevel(ok, 51, stored=4), 5)
        self.assertEqual(C.level_info(ok, 51, 4)["ulevel"], 5)
        a5 = C.copy_advice(ok, 5)  # M9: U5 → the ladder continues with QSOs
        self.assertEqual((a5["step"], a5["content"], a5["change"]["kind"]), (C.COPY_U4_LAST + 1, "qso", "up"))
        bad = [
            [S(80, step=last, wpm=25, fwpm=25, words=0.92)],                                   # one session
            [S(80, step=last, wpm=25, fwpm=25, words=0.8), S(100, step=last, wpm=25, fwpm=25, words=0.95)],
            [S(80, step=last, wpm=23, fwpm=23, words=0.95), S(100, step=last, wpm=23, fwpm=23, words=0.95)],
            [S(80, step=last, wpm=25, fwpm=25, words=0.95, drift=4), S(100, step=last, wpm=25, fwpm=25, words=0.95)],
            [S(80, step=last, wpm=25, fwpm=25, words=0.95, acc=0.85), S(100, step=last, wpm=25, fwpm=25, words=0.95)],
            [S(80, step=12, wpm=25, fwpm=25, words=0.95), S(100, step=12, wpm=25, fwpm=25, words=0.95)],
            [S(80, step=last, wpm=25, fwpm=25), S(100, step=last, wpm=25, fwpm=25)],      # bez slov (data M7)
        ]
        for b in bad:
            self.assertLess(C.computed_ulevel(self.U4 + b, 51, stored=4), 5, b)

    def test_next_criteria_u4(self):
        nc = C.next_criteria(4, self.U4 + [S(80, step=8, words=0.9)], 51)
        self.assertEqual(nc["target"], 5)
        self.assertTrue(any("25 WPM" in x for x in nc["items"]))
        self.assertTrue(any("words 90 %" in x for x in nc["items"]))
        self.assertIn("U5", C.next_criteria(5, self.U4, 51)["items"][0])

    def test_m7_data_compatible(self):
        # M7 lessons without the new fields (words, lagW) count as before
        sm = C.copy_summary([S(41, step=3)])
        self.assertEqual((sm["step"], sm["wpm"], sm["words"], sm["lagW"]), (3, 20, None, None))


class NavTest(unittest.TestCase):
    """0.10.10 (Martin): copy behind and vocabulary as own views from the top bar, Progress in the user menu."""

    def test_top_bar_and_views(self):
        import re
        from pathlib import Path
        web = Path(__file__).resolve().parent.parent / "web"
        html = (web / "index.html").read_text()
        main = (web / "js" / "main.js").read_text()
        nav = re.search(r'<nav class="tabs">(.*?)<div class="usermenu">', html, re.S).group(1)
        self.assertEqual(re.findall(r'data-go="(\w+)"', nav), ["login", "demo", "home", "copyhome", "vocab", "key", "cw"])  # 1.0.2: Sending (key page)
        menu = re.search(r'<div id="user-menu".*?</div>', html, re.S).group(0)
        self.assertIn('data-go="stats"', menu)
        home = re.search(r'<section id="view-home".*?</section>', html, re.S).group(0)
        self.assertNotIn("copy-card", home)
        self.assertNotIn('data-go="vocab"', home)
        copyhome = re.search(r'<section id="view-copyhome".*?</section>', html, re.S).group(0)
        for i in ("copy-card", "btn-copy", "copy-locked"):
            self.assertIn(f'id="{i}"', copyhome)
        self.assertIn("'copyhome'", re.search(r"const TRAINING_VIEWS = \[(.*?)\]", main).group(1))
        self.assertEqual(int(re.search(r"const COPY_EARLY_MIN = (\d+);", main).group(1)), C.COPY_EARLY_MIN)

if __name__ == "__main__":
    unittest.main()
