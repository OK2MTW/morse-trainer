# SPDX-License-Identifier: EUPL-1.2
"""0.17.0 D4 sending lessons: the step ladder (2 lessons in a row ≥ 90 % on the current step), the API (coaches and
students with the key page only), idempotent saving, export and the training reset."""
import re
import unittest
from pathlib import Path

from test_api import Client, make_invite  # noqa: E402 – sets MORSE_DB to a temporary database first

from server import sending as S

SENDEVAL_JS = (Path(__file__).resolve().parent.parent / "web/js/sendeval.js").read_text(encoding="utf-8")


def lesson(i, step, acc, **kw):
    return {"id": f"lesson-{i:04d}", "at": f"2026-11-14T01:{i:02d}:00Z", "step": step, "tasks": 10, "acc": acc,
            "wpm": 18.5, "detail": {"focus": "charGap", "habits": ["wordShort"], "secret": "dropped"}, **kw}


class StepStateTest(unittest.TestCase):
    def test_steps_match_the_client(self):
        m = re.search(r"export const SEND_STEPS = \[([^\]]*)\]", SENDEVAL_JS)
        self.assertEqual(tuple(re.findall(r"'(\w+)'", m.group(1))), S.SEND_STEPS)
        self.assertIn(f"export const SEND_PASS_ACC = {S.SEND_PASS_ACC};", SENDEVAL_JS)
        self.assertIn(f"export const SEND_PASS_N = {S.SEND_PASS_N};", SENDEVAL_JS)

    def test_two_in_a_row(self):
        st = S.step_state([("char", 0.95), ("char", 0.8), ("char", 0.92)])
        self.assertEqual((st["step"], st["streak"]), ("char", 1))
        st = S.step_state([("char", 0.95), ("char", 0.9)])
        self.assertEqual((st["step"], st["streak"]), ("group", 0))

    def test_other_steps_neither_count_nor_break(self):
        st = S.step_state([("char", 0.95), ("word", 0.5), ("char", 0.95), ("group", 1.0)])
        self.assertEqual((st["step"], st["streak"]), ("group", 1))

    def test_last_step_stays(self):
        seq = [(s, 1.0) for s in S.SEND_STEPS for _ in range(2)] + [("qso", 1.0)] * 4
        self.assertEqual(S.step_state(seq)["step"], "qso")
        self.assertEqual(S.step_state([])["step"], "char")


class SendApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coach = Client()
        assert cls.coach.register(make_invite("trener"), "SendTrener").status_code == 201
        cls.student = Client()
        assert cls.student.register(make_invite("zak"), "SendZak").status_code == 201

    def test_student_without_key_page_refused(self):
        self.assertEqual(self.student.req("GET", "/api/send").status_code, 403)
        self.assertEqual(self.student.req("POST", "/api/send", json={"lessons": []}).status_code, 403)
        self.assertEqual(Client().req("GET", "/api/send").status_code, 403)

    def test_save_progress_export_reset(self):
        c = self.coach
        r = c.req("GET", "/api/send").get_json()
        self.assertEqual((r["state"]["step"], r["count"]), ("char", 0))
        r = c.req("POST", "/api/send", json={"lessons": [lesson(1, "char", 0.95), lesson(2, "char", 0.91),
                                                         lesson(3, "bogus", 1.0), lesson(4, "group", 1.5)]})
        self.assertEqual(r.status_code, 200)
        r = r.get_json()
        self.assertEqual(r["saved"], ["lesson-0001", "lesson-0002"])
        self.assertEqual(r["state"]["step"], "group")
        self.assertNotIn("secret", r["lessons"][0]["detail"])
        self.assertEqual(r["lessons"][0]["id"], "lesson-0002")      # newest first
        again = c.req("POST", "/api/send", json={"lessons": [lesson(1, "char", 0.95)]}).get_json()
        self.assertEqual(again["count"], 2)                           # sent twice = stored once
        self.assertEqual(c.req("POST", "/api/send", json={"lessons": "x"}).status_code, 400)
        exp = c.req("GET", "/api/export").get_json()
        self.assertEqual(exp["send"]["count"], 2)
        db_rows = get_db_rows("SendTrener")
        self.assertEqual({r[0] for r in db_rows}, {S.MODE_SEND})


def get_db_rows(nick):
    import sqlite3
    import os
    con = sqlite3.connect(os.environ["MORSE_DB"])
    try:
        return con.execute("SELECT s.mode FROM send_lessons s JOIN users u ON u.id = s.user_id WHERE u.nick = ?",
                           (nick,)).fetchall()
    finally:
        con.close()


if __name__ == "__main__":
    unittest.main()
