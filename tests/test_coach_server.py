# SPDX-License-Identifier: EUPL-1.2
"""Tests of the server coach (server/coach.py): questionnaire → archetype, modifiers, preferences."""
import unittest

from server import coach as C
from server import i18n

BASE = {"age": "adult", "exp": "none", "time": "10to20", "rhythm": "daily", "pace": "normal", "music": "no",
        "reading": "easy", "typing": "easy", "focus": "mid", "hearing": "ok", "errors": "fine", "numbers": "basic"}


def prof(**kw):
    return C.profile_from_answers({**BASE, **kw})


class TestQuestionnaire(unittest.TestCase):
    def test_shape(self):
        self.assertGreaterEqual(len(C.QUESTIONS), 12)
        self.assertLessEqual(len(C.QUESTIONS), 14)
        ids = [q["id"] for q in C.QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for q in C.QUESTIONS:
            self.assertGreaterEqual(len(q["options"]), 2)
            if q.get("when"):
                self.assertIn(q["when"][0], ids[:ids.index(q["id"])])  # a condition only on an earlier question
        self.assertEqual(len(C.ARCHETYPES), 14)
        self.assertEqual(sorted(C.MODIFIERS), [f"M{i}" for i in range(15, 21)])

    def test_no_diagnosis_words(self):
        # no diagnoses may be in the stored results
        import json
        txt = json.dumps(prof(reading="hard", typing="hard", focus="short", hearing="hard"), ensure_ascii=False).lower()
        for w in ("dyslex", "adhd", "diagn", "nedoslý", "porucha"):
            self.assertNotIn(w, txt)
        for lang in i18n.LANGS:
            with i18n.use_lang(lang):
                names = [C.modifier_name(m) for m in C.MODIFIERS]
            for m in names:
                for w in ("dyslex", "adhd", "diagn"):
                    self.assertNotIn(w, m.lower())

    def test_clean(self):
        a = C.clean_answers({**BASE, "speed": "fast", "evil": "x", "age": "999"})
        self.assertNotIn("speed", a)  # a conditional question does not apply to a beginner
        self.assertNotIn("evil", a)
        self.assertNotIn("age", a)
        self.assertEqual(C.clean_answers("x"), {})
        self.assertEqual(C.profile_from_answers({})["archetype"], "Z01")

    def test_questions_json(self):
        j = C.questions_json()
        self.assertEqual(j[2]["when"]["q"], "exp")
        self.assertEqual(j[0]["options"][0], {"value": "child", "label": "8–12"})


class TestArchetypes(unittest.TestCase):
    def test_all_reachable(self):
        cases = {
            "Z01": {}, "Z02": {"music": "yes"}, "Z03": {"pace": "slow"}, "Z04": {"time": "lt10"},
            "Z05": {"pace": "fast", "time": "gt40"}, "Z06": {"age": "child"}, "Z07": {"age": "teen"},
            "Z08": {"age": "senior"}, "Z09": {"exp": "ear", "gaps": "few"}, "Z10": {"exp": "table"},
            "Z11": {"exp": "ear", "gaps": "numpunct"}, "Z12": {"exp": "active", "speed": "mid"},
            "Z13": {"exp": "active", "speed": "fast"}, "Z14": {"rhythm": "weekend"},
        }
        for z, kw in cases.items():
            self.assertEqual(prof(**kw)["archetype"], z, kw)

    def test_priority(self):
        self.assertEqual(prof(age="senior", exp="active", speed="fast")["archetype"], "Z13")  # experience wins
        self.assertEqual(prof(age="child", rhythm="weekend")["archetype"], "Z06")
        self.assertEqual(prof(exp="table", gaps="numpunct")["archetype"], "Z10")  # the method is the bigger problem

    def test_modifiers(self):
        self.assertEqual(prof()["modifiers"], [])
        p = prof(hearing="some", typing="hard", reading="hard", focus="short", errors="upset", numbers="yes")
        self.assertEqual(p["modifiers"], ["M18", "M16"])  # max. 2 podle priority
        self.assertEqual(prof(errors="upset", numbers="yes")["modifiers"], ["M19", "M20"])
        self.assertEqual(prof(typing="slow", reading="slow")["modifiers"], [])


class TestPrefs(unittest.TestCase):
    def test_defaults(self):
        p = prof()["prefs"]
        self.assertEqual(p["settings"], {"lessonMin": 5, "wpm": 20, "fwpm": 15})
        self.assertEqual(p["dayMin"], 15)
        self.assertEqual(p["feedback"], "std")
        self.assertFalse(p["entryTest"])

    def test_limits(self):
        # all combinations: block ≤ 10 min, character speed ≥ 12 WPM, fwpm ≤ wpm, daily goal ≤ 60
        import itertools
        keys = ["age", "exp", "time", "pace", "focus", "typing"]
        opts = [[o[0] for o in C.QMAP[k]["options"]] for k in keys]
        for combo in itertools.product(*opts):
            p = prof(**dict(zip(keys, combo)))["prefs"]
            s = p["settings"]
            self.assertTrue(1 <= s["lessonMin"] <= 10)
            self.assertTrue(12 <= s["wpm"] <= 40)
            self.assertLessEqual(s["fwpm"], s["wpm"])
            self.assertLessEqual(p["dayMin"], 60)

    def test_specific(self):
        self.assertEqual(prof(exp="active", speed="fast")["prefs"]["settings"]["wpm"], 25)
        self.assertEqual(prof(focus="short")["prefs"]["settings"]["lessonMin"], 4)
        self.assertEqual(prof(typing="hard")["prefs"]["keyboard"], "tiles")
        self.assertEqual(prof(errors="upset")["prefs"]["feedback"], "gentle")
        self.assertTrue(prof(exp="ear")["prefs"]["entryTest"])
        self.assertEqual(prof(age="senior")["prefs"]["settings"]["fwpm"], 10)


def les(level, minutes):
    return {"at": "2026-11-01T10:00:00Z", "level": level, "dur_s": minutes * 60}


class TestCalibration(unittest.TestCase):
    def test_additions(self):
        lessons = [les(2, 5), les(2, 5), les(3, 5), les(4, 10), les(10, 5)]  # 4 → 10 manual jump
        adds, mins = C.additions(lessons, 10)
        self.assertEqual(adds, [(2, 10), (3, 5)])
        self.assertEqual(mins[10], 5)
        # the last lesson advanced (progress is 1 higher)
        adds, _ = C.additions([les(2, 5), les(3, 7)], 4)
        self.assertEqual(adds, [(2, 5), (3, 7)])

    def test_prior_before_calibration(self):
        e = C.plan_estimate([les(2, 5)], 2, "Z08", {"dayMin": 30})
        self.assertEqual(e["source"], "prior")
        self.assertFalse(e["calibrated"])
        self.assertEqual(e["minPerChar"], list(C.ARCHETYPES["Z08"][1]))
        self.assertEqual(e["remainingChars"], 42)  # 0.9.6: main programme of 44
        self.assertEqual(e["dayMin"], 30)

    def test_data_wins(self):
        # a fast student: 2 characters after 6 min each, although the archetype expects slow progress
        e = C.plan_estimate([les(2, 6), les(3, 6), les(4, 2)], 4, "Z08", {})
        self.assertEqual(e["source"], "data")
        self.assertEqual(e["rate"], 6)
        lo, hi = e["minPerChar"]
        self.assertLess(lo, 6)
        self.assertGreater(hi, 6)
        self.assertLess(hi, C.ARCHETYPES["Z08"][1][0])
        self.assertLessEqual(e["remainingMin"][0], e["remainingMin"][1])
        self.assertEqual(e["dayMin"], C.DEFAULT_DAY_MIN)

    def test_range_narrows(self):
        few = C.plan_estimate([les(2, 10), les(3, 10), les(4, 1)], 4, "Z01", {})
        lessons = [les(lv, 10) for lv in range(2, 22)] + [les(22, 1)]
        many = C.plan_estimate(lessons, 22, "Z01", {})
        r = lambda e: e["minPerChar"][1] / e["minPerChar"][0]
        self.assertLess(r(many), r(few))

    def test_slow_after_three_lessons(self):
        e = C.plan_estimate([les(2, 10), les(2, 10), les(2, 10)], 2, "Z13", {})
        self.assertEqual(e["source"], "data")
        self.assertEqual(e["rate"], 30)

    def test_full_set(self):
        e = C.plan_estimate([les(50, 10), les(51, 10)], 51, "Z01", {})
        self.assertEqual(e["remainingChars"], 0)
        self.assertEqual(e["remainingMin"], [0, 0])

    def test_no_lessons(self):
        e = C.plan_estimate([], 2, None, None)
        self.assertEqual(e["source"], "prior")
        self.assertEqual(e["minPerChar"], list(C.ARCHETYPES["Z01"][1]))


import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

T0 = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
ALL = [*"KMURESNAPTLWI.JZ=FOY,VG5/Q92H38B?47C1D60X", "'", "-", ":", "(", ")", '"', "@", "+", "&", "!"]


def L(hours, level=10, dur_min=5, acc=0.9, ttr=600, wpm=20, fwpm=15, device="pc", per=None, trials=60):
    at = (T0 + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    det = {"perChar": per or []}
    return {"at": at, "level": level, "dur_s": dur_min * 60, "trials": trials, "acc": acc, "ttr": ttr,
            "wpm": wpm, "fwpm": fwpm, "device": device, "detail": json.dumps(det)}


import json  # noqa: E402

GOOD = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 500} for c in ALL]


class TestSessions(unittest.TestCase):
    def test_constant_matches_js(self):
        js = (Path(__file__).resolve().parent.parent / "web/js/coach.js").read_text(encoding="utf-8")
        self.assertEqual(int(re.search(r"SESSION_BREAK_MIN = (\d+);", js).group(1)), C.SESSION_BREAK_MIN)

    def test_grouping(self):
        ls = [L(0), L(0.1), L(0.2), L(3), L(3.1), L(24)]
        self.assertEqual([len(s) for s in C.sessions_of(ls)], [3, 2, 1])
        self.assertEqual(C.sessions_of([]), [])

    def test_alphabet(self):
        self.assertEqual(len(ALL), 51)


class TestULevel(unittest.TestCase):
    def test_u1_default(self):
        info = C.level_info([L(0, level=5)], 5, None)
        self.assertEqual(info["ulevel"], 1)
        self.assertEqual(info["next"]["target"], 2)
        self.assertEqual(len(info["levels"]), 6)

    def test_u2_needs_two_sessions(self):
        one = [L(0, level=51, per=GOOD)]
        self.assertEqual(C.computed_ulevel(one, 51), 1)
        two = [L(0, level=51, per=GOOD), L(20, level=51, per=GOOD)]
        self.assertEqual(C.computed_ulevel(two, 51), 2)
        # not without the full main programme
        self.assertEqual(C.computed_ulevel([L(0, level=43, per=GOOD), L(20, level=43, per=GOOD)], 43), 1)
        # 0.9.6: the main programme (44) is enough – the optional extension never blocks a level
        core = [x for x in GOOD if x["ch"] in C.KOCH[:C.CORE_SIZE]]
        self.assertEqual(C.computed_ulevel([L(0, level=44, per=core), L(20, level=44, per=core)], 44), 2)
        weak_extra = [dict(x, acc=0.5) if x["ch"] in C.KOCH[C.CORE_SIZE:] else x for x in GOOD]
        self.assertEqual(C.computed_ulevel([L(0, level=51, per=weak_extra), L(20, level=51, per=weak_extra)], 51), 2)

    def test_u2_weak_char(self):
        weak = [dict(x) for x in GOOD]
        weak[3]["acc"] = 0.7
        ls = [L(0, level=51, per=GOOD), L(20, level=51, per=weak), L(40, level=51, per=weak)]
        self.assertEqual(C.computed_ulevel(ls, 51), 1)
        self.assertEqual(C.u1_status(ls, 51)["good"], 43)
        self.assertEqual(C.u1_status(ls, 51)["of"], 44)

    def test_extension_order(self):
        """0.9.6: the same Koch order on the server (coach, api) and in web/js/charset.js; the extension at the end."""
        import re
        from pathlib import Path
        from server.api import KOCH_ORDER
        js = Path(__file__).resolve().parent.parent.joinpath("web/js/charset.js").read_text(encoding="utf-8")
        body = re.search(r"KOCH_ORDER = \[(.*?)\];", js, re.S).group(1)
        body = re.sub(r"//.*", "", body)  # drop comments
        order = "".join(a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", body))
        self.assertEqual(order, C.KOCH)
        self.assertEqual("".join(KOCH_ORDER), C.KOCH)
        self.assertEqual(int(re.search(r"CORE_SIZE = (\d+)", js).group(1)), C.CORE_SIZE)
        self.assertEqual(set(C.KOCH[C.CORE_SIZE:]), set(",':)\"@!"))
        for prosign in "=+(&":  # BT AR KN AS stay in the main programme
            self.assertLess(C.KOCH.index(prosign), C.CORE_SIZE)

    def test_u3(self):
        ls = [L(0, level=51, per=GOOD), L(20, level=51, per=GOOD, fwpm=20, ttr=550),
              L(40, level=51, per=GOOD, fwpm=20, ttr=580)]
        self.assertEqual(C.computed_ulevel(ls, 51), 3)
        # a phone has a higher reaction threshold
        ls2 = [L(0, level=51, per=GOOD), L(20, level=51, per=GOOD, fwpm=20, ttr=750, device="mobil"),
               L(40, level=51, per=GOOD, fwpm=20, ttr=780, device="mobil")]
        self.assertEqual(C.computed_ulevel(ls2, 51), 3)
        ls3 = [L(0, level=51, per=GOOD), L(20, level=51, per=GOOD, fwpm=20, ttr=750),
               L(40, level=51, per=GOOD, fwpm=20, ttr=780)]
        self.assertEqual(C.computed_ulevel(ls3, 51), 2)

    def test_stored_never_drops(self):
        self.assertEqual(C.level_info([L(0, level=5)], 5, 2)["ulevel"], 2)
        self.assertLessEqual(C.MAX_COMPUTED_ULEVEL, 6)  # 0.10.14: U6 from head copy


class TestPlateau(unittest.TestCase):
    def test_no_plateau_with_progress(self):
        ls = [L(0, level=5), L(20, level=6), L(40, level=7), L(60, level=8)]
        self.assertIsNone(C.plateau(ls, 8))

    def test_plateau_three_sessions(self):
        ls = [L(0, level=5), L(20, level=6, ttr=800), L(40, level=6, ttr=760), L(60, level=6, ttr=700)]
        p = C.plateau(ls, 6)
        self.assertEqual(p["sessions"], 3)
        self.assertFalse(p["change"])
        self.assertIn("800", p["process"])
        self.assertIn("normal", p["text"])

    def test_plateau_change_after_five(self):
        ls = [L(h * 20, level=6) for h in range(6)]
        p = C.plateau(ls, 6)
        self.assertEqual(p["sessions"], 6)
        self.assertTrue(p["change"])
        self.assertIsNone(p["process"])

    def test_fwpm_counts_as_progress(self):
        ls = [L(0, level=51, fwpm=15), L(20, level=51, fwpm=15), L(40, level=51, fwpm=16), L(60, level=51, fwpm=16)]
        self.assertIsNone(C.plateau(ls, 51))

    def test_last_lesson_advanced(self):
        ls = [L(0, level=6), L(20, level=6), L(40, level=6)]
        self.assertIsNone(C.plateau(ls, 7))

    def test_feedback_about_task(self):
        for lang in i18n.LANGS:
            with i18n.use_lang(lang):
                p = C.plateau([L(h * 20, level=6) for h in range(6)], 6)
            txt = (p["text"] + p["advice"]).lower()
            for w in ("šikov", "talent", "špatn", "neschop", "lepší než ostatní", "clever", "bad at", "better than others"):
                self.assertNotIn(w, txt)


class TestDashboard(unittest.TestCase):
    from datetime import datetime as _dt, timezone as _tz
    NOW = _dt(2026, 11, 4, 18, 0, tzinfo=_tz.utc).timestamp() * 1000

    def lesson(self, days_ago, hour=17, level=5, acc=0.9, ttr=600, dur=600, warm=None, fatigue=False):
        from datetime import datetime, timezone, timedelta
        at = datetime(2026, 11, 4, tzinfo=timezone.utc) + timedelta(hours=hour) - timedelta(days=days_ago)
        det = {}
        if warm is not None:
            det["warmup"] = {"n": 20, "acc": warm, "ttr": 700, "gapH": 20}
        if fatigue:
            det["fatigue"] = {"base": {}, "events": [{"t": 300, "kind": "ttr"}]}
        return {"at": at.isoformat().replace("+00:00", "Z"), "level": level, "dur_s": dur, "trials": 200,
                "acc": acc, "ttr": ttr, "wpm": 20, "fwpm": 10, "device": "pc", "detail": det}

    def test_empty(self):
        d = C.dashboard([], 2, {}, self.NOW)
        self.assertEqual(len(d["days"]), C.DASH_DAYS)
        self.assertEqual(d["days"][-1]["d"], "2026-11-04")
        self.assertEqual(d["regularity"]["streak"], 0)
        self.assertEqual(d["sessions"], [])
        self.assertIsNone(d["retention"])
        self.assertEqual(len(d["weeks"]), C.DASH_WEEKS)

    def test_regularity_and_progress(self):
        ls = []
        lv = 2
        # 10 days in a row (yesterday … 10 days ago), 2 lessons in one session each day, a new character every other day
        for i in range(10, 0, -1):
            ls.append(self.lesson(i, 16, lv, warm=0.85 if ls else None))
            ls.append(self.lesson(i, 16.25, lv, fatigue=(i == 3)))
            if i % 2 == 0:
                lv += 1
        d = C.dashboard(ls, lv, {"dayMin": 20}, self.NOW)
        r = d["regularity"]
        self.assertEqual(r["streak"], 10)  # nothing today yet, the streak lasts
        self.assertEqual(r["days14"], 10)
        self.assertEqual(r["goal14"], 10)  # 2× 10 min ≥ 80 % z 20
        self.assertEqual(sum(w["added"] for w in d["weeks"]), 5)
        self.assertEqual(len(d["sessions"]), 10)
        self.assertEqual(d["sessions"][-1]["chars"], lv)
        self.assertEqual(d["fatigue14"], 1)
        self.assertEqual(d["retention"]["n"], 5)
        self.assertAlmostEqual(d["retention"]["warm"], 0.85)
        self.assertTrue(any("break" in t for t in d["insight"]))

    def test_streak_broken(self):
        ls = [self.lesson(5), self.lesson(1), self.lesson(0, 8)]
        d = C.dashboard(ls, 5, {}, self.NOW)
        self.assertEqual(d["regularity"]["streak"], 2)
        self.assertEqual(d["days"][-1]["n"], 1)

    def test_local_day_boundary(self):
        # 23:30 UTC = 0:30 local time the next day (CET +1)
        from datetime import datetime, timezone
        at = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        r = {**self.lesson(0), "at": at}
        d = C.dashboard([r], 5, {}, self.NOW)
        self.assertEqual(d["days"][-1]["n"], 1)

    def test_insight_regular_vs_irregular(self):
        ls = []
        lv = 2
        for i in range(20, 13, -1):  # a regular week, 3 new characters
            ls.append(self.lesson(i, 17, lv))
            if i % 2 == 0:
                lv += 1
        ls.append(self.lesson(9, 17, lv))  # an irregular week, nothing
        d = C.dashboard(ls, lv, {}, self.NOW)
        self.assertTrue(any(t.startswith("In weeks") for t in d["insight"]), d["insight"])

    def test_frequency_advice_needs_history(self):
        new = C.dashboard([self.lesson(1), self.lesson(0, 8)], 5, {}, self.NOW)
        self.assertFalse(any("more often" in t for t in new["insight"]))
        old = C.dashboard([self.lesson(10), self.lesson(0, 8)], 5, {}, self.NOW)
        self.assertTrue(any("more often" in t for t in old["insight"]))


class TestSpeed(unittest.TestCase):
    """M6: pace (Farnsworth / character speed) between sessions."""
    def adv(self, ls, level=51, ulevel=2, cur=None, plat=None):
        return C.speed_advice(ls, level, ulevel, cur or {"wpm": 20, "fwpm": 15}, plat)

    def test_needs_two_sessions_on_current_tempo(self):
        self.assertIsNone(self.adv([L(0, level=51, acc=0.95)])["change"])
        # two sessions, but at a different pace → nothing (after a change new data are awaited)
        ls = [L(0, level=51, acc=0.95, fwpm=14), L(20, level=51, acc=0.95, fwpm=14)]
        self.assertIsNone(self.adv(ls)["change"])
        # a session with < 40 trials is skipped
        ls = [L(0, level=51, acc=0.95), L(20, level=51, acc=0.95, trials=20)]
        self.assertIsNone(self.adv(ls)["change"])

    def test_u2_shortens_gaps(self):
        ls = [L(0, level=51, acc=0.92), L(20, level=51, acc=0.93)]
        a = self.adv(ls)
        self.assertEqual(a["change"]["kind"], "gaps")
        self.assertEqual(a["change"]["to"], {"wpm": 20, "fwpm": 16})
        # far from the character → a step of 2
        ls = [L(0, level=51, acc=0.92, fwpm=10), L(20, level=51, acc=0.93, fwpm=10)]
        self.assertEqual(self.adv(ls, cur={"wpm": 20, "fwpm": 10})["change"]["to"]["fwpm"], 12)
        # unstable reaction → nothing
        ls = [L(0, level=51, acc=0.92, ttr=500), L(20, level=51, acc=0.93, ttr=700)]
        self.assertIsNone(self.adv(ls)["change"])
        # pod 90 % → nic
        ls = [L(0, level=51, acc=0.92), L(20, level=51, acc=0.88)]
        self.assertIsNone(self.adv(ls)["change"])

    def test_u2_then_char_speed_to_20(self):
        ls = [L(0, level=51, acc=0.95, wpm=18, fwpm=18), L(20, level=51, acc=0.95, wpm=18, fwpm=18)]
        a = self.adv(ls, cur={"wpm": 18, "fwpm": 18})
        self.assertEqual((a["change"]["kind"], a["change"]["to"]), ("chars", {"wpm": 19, "fwpm": 18}))
        ls = [L(0, level=51, acc=0.95, fwpm=20), L(20, level=51, acc=0.95, fwpm=20)]
        a = self.adv(ls, cur={"wpm": 20, "fwpm": 20})
        self.assertIsNone(a["change"])  # 20/20 = the U2 goal, then copy behind (M7)
        self.assertIn("copy behind", a["next"])

    def test_u1_never_speeds_up(self):
        ls = [L(0, level=20, acc=0.97), L(20, level=20, acc=0.97)]
        self.assertIsNone(self.adv(ls, level=20, ulevel=1)["change"])
        self.assertEqual(self.adv(ls, level=20, ulevel=1)["fluencyS"], 0)

    def test_ease_any_level(self):
        ls = [L(0, level=20, acc=0.7), L(20, level=20, acc=0.72)]
        a = self.adv(ls, level=20, ulevel=1)
        self.assertEqual((a["change"]["kind"], a["change"]["to"]["fwpm"]), ("ease", 14))
        cur = {"wpm": 20, "fwpm": C.FW_MIN}
        ls = [L(0, level=20, acc=0.7, fwpm=C.FW_MIN), L(20, level=20, acc=0.72, fwpm=C.FW_MIN)]
        self.assertIsNone(self.adv(ls, level=20, ulevel=1, cur=cur)["change"])

    def test_u1_plateau_changes_plan_once_per_5_sessions(self):
        ls = [L(20 * i, level=20, acc=0.85) for i in range(6)]
        plat = C.plateau(ls, 20)
        self.assertTrue(plat and plat["change"])
        a = self.adv(ls, level=20, ulevel=1, plat=plat)
        self.assertEqual((a["change"]["kind"], a["change"]["to"]["fwpm"]), ("plateau", 13))
        # after a change 5 sessions at the new pace are awaited
        ls2 = ls + [L(200 + 20 * i, level=20, acc=0.85, fwpm=13) for i in range(4)]
        self.assertIsNone(self.adv(ls2, level=20, ulevel=1, cur={"wpm": 20, "fwpm": 13}, plat=C.plateau(ls2, 20))["change"])
        # at most down to FW_PLATEAU_MIN
        ls3 = [L(20 * i, level=20, acc=0.85, fwpm=C.FW_PLATEAU_MIN) for i in range(6)]
        cur = {"wpm": 20, "fwpm": C.FW_PLATEAU_MIN}
        self.assertIsNone(self.adv(ls3, level=20, ulevel=1, cur=cur, plat=C.plateau(ls3, 20))["change"])

    def test_fluency_longer_on_u2_plateau(self):
        self.assertEqual(self.adv([])["fluencyS"], C.FLUENCY_S)
        self.assertEqual(self.adv([], plat={"change": True, "sessions": 5})["fluencyS"], C.FLUENCY_PLATEAU_S)

    def test_simulated_path_reaches_20_20(self):
        """A student with the full set, 15 WPM spacing, every session 92 % → how many sessions to 20/20."""
        cur, ls, h = {"wpm": 20, "fwpm": 15}, [], 0
        for _ in range(40):
            ls.append(L(h, level=51, acc=0.92, wpm=cur["wpm"], fwpm=cur["fwpm"]))
            h += 20
            a = self.adv(ls, cur=cur)
            if a["change"]:
                cur = a["change"]["to"]
            if cur == {"wpm": 20, "fwpm": 20}:
                break
        self.assertEqual(cur, {"wpm": 20, "fwpm": 20})
        self.assertLessEqual(len(ls), 10)  # 5 steps × 2 sessions
