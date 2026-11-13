# SPDX-License-Identifier: EUPL-1.2
"""0.14.5 visit counter (server/visits.py): different visitors per day and entry, never logged in, no IP stored,
monthly salt, retention, administrator only."""
import unittest
from datetime import datetime, timezone
from unittest import mock

from test_api import HOST, Client, make_invite  # noqa: E402 – sets MORSE_DB to a temporary database first

from server import visits
from server.db import connect


def visit(ip, public=False, client=None):
    c = client or Client()
    headers = {"Host": HOST}
    if public:
        headers["X-Morse-Entry"] = "public"
    return c.c.open("/api/me", headers=headers, base_url=f"https://{HOST}", environ_base={"REMOTE_ADDR": ip})


class VisitsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = Client()
        assert cls.admin.register(make_invite("admin"), "VisSpravce").status_code == 201
        cls.coach = Client()
        assert cls.coach.register(make_invite("trener"), "VisTrener").status_code == 201

    def setUp(self):
        con = connect()
        con.execute("DELETE FROM visits")
        con.execute("DELETE FROM visit_salts")
        con.close()
        visits._seen.update(day=None, keys=set())
        visits._public.update(at=None, data=None)

    def rows(self):
        con = connect()
        r = [dict(x) for x in con.execute("SELECT * FROM visits ORDER BY entry, who")]
        con.close()
        return r

    def test_counts_per_entry_and_anonymous(self):
        visit("203.0.113.7")
        visit("203.0.113.7")                        # the same visitor again
        visit("2001:db8:1:2::5", public=True)
        visit("2001:db8:1:2::99", public=True)      # the same /64 = the same phone
        visit("198.51.100.1", public=True)
        self.assertEqual(visit("192.0.2.10", client=self.coach).status_code, 200)   # logged in, home network
        s = self.admin.req("GET", "/api/visits?days=7").get_json()
        today = s["days"][0]
        self.assertEqual((today["lan"], today["public"]), ([2, 1], [2, 2]))
        self.assertEqual(s["total"], {"lan": [2, 1], "public": [2, 2]})

    def test_no_address_stored(self):
        visit("203.0.113.7", public=True)
        con = connect()
        dump = "\n".join(con.iterdump())
        con.close()
        self.assertNotIn("203.0.113.7", dump)
        self.assertEqual(len(self.rows()[0]["who"]), 16)

    def test_later_login_marks_the_visitor(self):
        c = Client()
        visit("192.0.2.44", client=c)
        assert c.register(make_invite(), "VisZak").status_code == 201
        visit("192.0.2.44", client=c)
        self.assertEqual([(r["entry"], r["logged"]) for r in self.rows()], [("lan", 1)])

    def test_salt_per_month_and_retention(self):
        jan = datetime(2027, 1, 31, 12, tzinfo=timezone.utc)
        with mock.patch.object(visits, "now", return_value=jan):
            visit("203.0.113.7")
        old = self.rows()[0]["who"]
        later = datetime(2027, 5, 2, 12, tzinfo=timezone.utc)
        with mock.patch.object(visits, "now", return_value=later):
            visit("203.0.113.7")
        r = sorted(self.rows(), key=lambda x: x["day"])
        self.assertEqual([x["day"] for x in r], ["2027-01-31", "2027-05-02"])   # 0.14.6: kept permanently
        self.assertNotEqual(r[1]["who"], old)                          # a new month = a new salt
        con = connect()
        self.assertEqual([x[0] for x in con.execute("SELECT month FROM visit_salts")], ["2027-05"])
        con.close()

    def test_public_summary(self):
        d1 = datetime(2027, 3, 1, 12, tzinfo=timezone.utc)
        d2 = datetime(2027, 3, 2, 12, tzinfo=timezone.utc)
        with mock.patch.object(visits, "now", return_value=d1):
            visit("203.0.113.7")
            visit("203.0.113.8")
        with mock.patch.object(visits, "now", return_value=d2):
            visit("203.0.113.7")
            visits._public.update(at=None)
            r = Client().req("GET", "/api/visits/public")         # no login needed
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json(), {"today": 1, "total": 3, "since": "2027-03-01"})
            visit("203.0.113.9")
            self.assertEqual(Client().req("GET", "/api/visits/public").get_json()["today"], 1)   # cached a minute
        later = d2.replace(minute=2)
        with mock.patch.object(visits, "now", return_value=later):
            self.assertEqual(Client().req("GET", "/api/visits/public").get_json()["today"], 2)
        self.assertNotIn("who", str(Client().req("GET", "/api/visits/public").get_json()))

    def test_administrator_only(self):
        self.assertEqual(self.coach.req("GET", "/api/visits").status_code, 403)
        self.assertEqual(Client().req("GET", "/api/visits").status_code, 403)
        self.assertEqual(self.admin.req("GET", "/api/visits?days=abc").status_code, 200)


if __name__ == "__main__":
    unittest.main()
