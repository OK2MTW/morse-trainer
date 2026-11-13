# SPDX-License-Identifier: EUPL-1.2
"""Z-20 (0.17.1): /api/data sends only the lessons stored after the client's last sync (server sequence), and
/api/coach keeps its result until an input changes – the same answer, but no recomputation of the whole history."""
import time
import unittest
from pathlib import Path

from test_api import Client, make_invite  # noqa: E402 – sets MORSE_DB to a temporary database first

from server import api

STORAGE_JS = (Path(__file__).resolve().parent.parent / "web/js/storage.js").read_text(encoding="utf-8")


def les(i, at=None):
    return {"id": f"z20-lesson-{i:05d}", "at": at or f"2026-10-{1 + i // 40:02d}T{(i % 20):02d}:{i % 60:02d}:00Z",
            "device": "pc", "level": 4, "durS": 300, "trials": 50, "correct": 46, "acc": 0.92, "ttr": 640, "wpm": 20,
            "fwpm": 15, "detail": {"perChar": [{"ch": "K", "n": 10, "acc": 0.9, "ttr": 600}]}}


class SyncDeltaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Client()
        assert cls.c.register(make_invite("trener"), "ZetDvacet").status_code == 201

    def test_partial_data_by_server_sequence(self):
        c = self.c
        c.req("POST", "/api/lessons", {"lessons": [les(i) for i in range(5)]})
        full = c.req("GET", "/api/data").get_json()
        self.assertNotIn("partial", full)
        self.assertGreater(full["seq"], 0)
        none = c.req("GET", f"/api/data?after={full['seq']}").get_json()
        self.assertEqual((none["partial"], none["lessons"], none["seq"]), (True, [], full["seq"]))
        # a lesson uploaded late from another device with an OLD time still arrives (sequence, not client time)
        c.req("POST", "/api/lessons", {"lessons": [les(99, "2026-01-01T00:00:00Z")]})
        d = c.req("GET", f"/api/data?after={full['seq']}").get_json()
        self.assertEqual([x["id"] for x in d["lessons"]], ["z20-lesson-00099"])
        self.assertEqual(c.req("GET", "/api/data?after=x").get_json().get("partial"), None)  # garbage → full

    def test_client_merges_and_resets(self):
        for frag in ("const inc = !legacy && Number.isInteger(sync.seq) && sync.epoch !== null;",
                     "if (d.partial && d.epoch !== sync.epoch) d = await api('GET', '/data');",
                     "progress.history = mergeHistory(d.lessons, d.partial ? progress.history : [], pending);",
                     "  sync.seq = null;\n}"):
            self.assertIn(frag, STORAGE_JS)


class CoachCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Client()
        assert cls.c.register(make_invite("trener"), "ZetCache").status_code == 201
        cls.c.req("POST", "/api/lessons", {"lessons": [les(i) for i in range(900)]})

    def test_same_answer_and_invalidation(self):
        c = self.c
        a = c.req("GET", "/api/coach").get_json()
        t0 = time.perf_counter()
        b = c.req("GET", "/api/coach").get_json()
        hit = time.perf_counter() - t0
        self.assertEqual(a, b)
        self.assertLess(hit, 0.3)                    # 900 lessons: a cache hit does not walk the history
        c.req("POST", "/api/lessons", {"lessons": [les(950, "2026-11-13T20:00:00Z")]})
        d = c.req("GET", "/api/coach").get_json()
        self.assertNotEqual(d, a)                    # a new lesson → computed again
        self.assertLessEqual(len(api._COACH_CACHE), api.COACH_CACHE_MAX)

    def test_signature_changes_with_inputs(self):
        import os
        import sqlite3
        con = sqlite3.connect(os.environ["MORSE_DB"])
        uid = con.execute("SELECT id FROM users WHERE nick = 'ZetCache'").fetchone()[0]
        con.close()
        c = self.c
        c.req("GET", "/api/coach")
        key1 = api._COACH_CACHE[uid][0]
        c.req("PUT", "/api/settings", {"settings": {"freq": 700}})
        c.req("GET", "/api/coach")
        self.assertNotEqual(api._COACH_CACHE[uid][0], key1)


if __name__ == "__main__":
    unittest.main()
