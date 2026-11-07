# SPDX-License-Identifier: EUPL-1.2
"""Tests of the server coach for head copy (U6, 0.10.14): availability, ladder, U5 → U6."""
import json
import unittest

from server import coach as C
from server import i18n
from tests.test_copy_server import S, U3, at


def H(h, step=1, q=15, ok=14, wpm=None):
    wpm = wpm or C.HEAD_STEPS[step - 1]["wpm"]
    return {"at": at(h), "mode": "hlava", "level": 51, "dur_s": 300, "trials": q, "correct": ok, "acc": ok / q,
            "ttr": None, "wpm": wpm, "fwpm": wpm, "device": "pc", "detail": json.dumps({"head": {"step": step, "q": q, "ok": ok}})}


class TestHeadAdvice(unittest.TestCase):
    def test_locked_below_u4(self):
        self.assertFalse(C.head_advice([], 3)["available"])

    def test_u4_trial_step_1_only(self):
        a = C.head_advice([H(1), H(30)], 4)
        self.assertTrue(a["available"] and a["early"])
        self.assertEqual((a["step"], a["wpm"], a["change"]), (1, 25, None))  # no step up from the trial

    def test_u5_up_and_ease(self):
        a = C.head_advice([H(1), H(30)], 5)
        self.assertEqual((a["change"]["kind"], a["step"], a["wpm"]), ("up", 2, 30))
        a = C.head_advice([H(1, step=3, ok=8), H(30, step=3, ok=9)], 5)
        self.assertEqual((a["change"]["kind"], a["step"]), ("ease", 2))
        a = C.head_advice([H(1, step=3, ok=12), H(30, step=3, ok=13)], 5)  # 80–87 % stays
        self.assertIsNone(a["change"])
        self.assertEqual(a["band"], "u5noise")

    def test_short_session_skipped(self):
        a = C.head_advice([H(1, q=9, ok=9), H(30, q=9, ok=9)], 5)
        self.assertIsNone(a["change"])

    def test_steps_after_u6_locked_for_u5(self):
        a = C.head_advice([H(1, step=6), H(30, step=6)], 5)
        self.assertIsNone(a["change"])  # step 7 needs U6
        a = C.head_advice([H(1, step=6), H(30, step=6)], 6)
        self.assertEqual(a["step"], 7)

    def test_texts(self):
        for lang in i18n.LANGS:
            with i18n.use_lang(lang):
                for ul in (4, 5, 6):
                    for st in range(1, len(C.HEAD_STEPS) + 1):
                        a = C.head_advice([H(1, step=st)], ul)
                        self.assertTrue(a["name"] and a["next"])
                self.assertTrue(C.next_criteria(5, [H(1)], 51)["items"])
                self.assertTrue(C.next_criteria(6, [], 51)["items"])


class TestU6(unittest.TestCase):
    def test_u6_from_head_copy(self):
        self.assertEqual(C.computed_ulevel(U3 + [H(41, step=6), H(60, step=6)], 51, stored=5), 6)
        # below 90 % or a lower step: no U6 (computed stays from the data, the stored U5 is kept by level_info)
        self.assertLess(C.computed_ulevel(U3 + [H(41, step=6), H(60, step=6, ok=12)], 51, stored=5), 6)
        self.assertLess(C.computed_ulevel(U3 + [H(41, step=5), H(60, step=5)], 51, stored=5), 6)
        self.assertEqual(C.level_info(U3 + [H(41, step=5), H(60, step=5)], 51, 5)["ulevel"], 5)
        # without U5 (stored or from data) head copy does not give U6
        self.assertLess(C.computed_ulevel(U3 + [H(41, step=6), H(60, step=6)], 51, stored=3), 6)
        self.assertEqual(C.level_info(U3 + [H(41, step=6), H(60, step=6)], 51, 5)["ulevel"], 6)

    def test_modes_separate(self):
        # head lessons do not count as copy behind or as character lessons
        ls = U3 + [H(41), H(60)]
        self.assertEqual(C.copy_sessions(ls), [])
        self.assertEqual(len(C.char_lessons(ls)), 3)
        self.assertEqual(len(C.head_sessions(ls + [S(80)])), 2)
