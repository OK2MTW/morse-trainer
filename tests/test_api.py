# SPDX-License-Identifier: EUPL-1.2
"""API tests (unittest, no pytest). Run: .venv/bin/python -m unittest discover -s tests"""
import json
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp(prefix="morse-test-")
os.environ["MORSE_DB"] = os.path.join(_tmp, "test.db")
os.environ["MORSE_ARGON2_MEMORY"] = "1024"  # fast tests; production uses 19 MiB
os.environ["MORSE_SITE_ENV"] = os.path.join(_tmp, "site.env")  # does not exist → only the values below
os.environ["MORSE_HOME_URL"] = "https://192.0.2.10/"
os.environ["MORSE_PUBLIC_URL"] = "https://venku.example.org"

from server.app import app  # noqa: E402
from server.admin import main as admin_main  # noqa: E402
from server.db import connect  # noqa: E402
from server.auth import sha256, iso, now  # noqa: E402

HOST = "localhost"


def make_invite(role="zak"):
    import secrets
    from datetime import timedelta
    tok = secrets.token_urlsafe(24)
    con = connect()
    t = now()
    con.execute("INSERT INTO invites (token_hash, role, created_at, expires_at) VALUES (?,?,?,?)",
                (sha256(tok), role, iso(t), iso(t + timedelta(days=1))))
    con.close()
    return tok


class Client:
    def __init__(self):
        self.c = app.test_client()
        self.csrf = ""

    def req(self, method, path, json=None, csrf=True, origin=f"https://{HOST}"):
        headers = {"Host": HOST}
        if origin:
            headers["Origin"] = origin
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        r = self.c.open(path, method=method, json=json, headers=headers, base_url=f"https://{HOST}")
        return r

    def register(self, tok, nick, pw="Tajne-heslo1", **kw):
        r = self.req("POST", "/api/register", {"token": tok, "nick": nick, "password": pw, **kw})
        if r.status_code == 201:
            self.csrf = r.get_json()["csrf"]
        return r

    def login(self, nick, pw="Tajne-heslo1"):
        r = self.req("POST", "/api/login", {"nick": nick, "password": pw})
        if r.status_code == 200:
            self.csrf = r.get_json()["csrf"]
        return r


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = Client()
        r = cls.admin.register(make_invite("admin"), "Spravce")
        assert r.status_code == 201, r.get_json()

    def test_health_and_me(self):
        c = Client()
        self.assertEqual(c.req("GET", "/api/health").get_json()["version"], "0.9.2")
        r = c.req("GET", "/api/me")
        self.assertEqual(r.status_code, 403)  # 0.8.1: ne 401 (Basic auth Pinggy v Chromu)
        self.assertTrue(r.get_json()["auth"])
        me = self.admin.req("GET", "/api/me").get_json()
        self.assertEqual(me["user"]["role"], "admin")

    def test_cookie_flags(self):
        c = Client()
        r = c.register(make_invite(), "Kuki")
        cookie = r.headers.get("Set-Cookie")
        for flag in ("__Host-sid=", "Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_invite_single_use_and_validation(self):
        tok = make_invite()
        c = Client()
        self.assertEqual(c.req("POST", "/api/invite/check", {"token": tok}).status_code, 200)
        self.assertEqual(c.register(tok, "x").status_code, 400)            # short nickname
        self.assertEqual(c.register(tok, "Pepa", pw="kratke").status_code, 400)
        self.assertEqual(c.register(tok, "spravce").status_code, 400)       # obsazeno (bez ohledu na velikost)
        self.assertEqual(c.register(tok, "Dítě", age_group="do15").status_code, 400)  # without parental consent
        self.assertEqual(c.register(tok, "Pepa").status_code, 201)
        self.assertEqual(Client().register(tok, "Pepa2").status_code, 404)  # not a second time
        self.assertEqual(Client().register("neplatny" * 4, "Pepa3").status_code, 404)

    def test_login_logout_and_rate_limit(self):
        Client().register(make_invite(), "Jana")
        c = Client()
        self.assertEqual(c.login("Jana", "spatneheslo").status_code, 403)
        self.assertEqual(c.login("jana").status_code, 200)
        self.assertEqual(c.req("GET", "/api/data").status_code, 200)
        self.assertEqual(c.req("POST", "/api/logout").status_code, 200)
        self.assertEqual(c.req("GET", "/api/data").status_code, 403)
        bad = Client()
        codes = [bad.login("Jana", "spatne-heslo").status_code for _ in range(9)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(bad.login("Jana").status_code, 429)  # even the right password after a block
        from server import auth
        auth._fails.clear()

    def test_csrf_and_origin(self):
        c = Client()
        c.register(make_invite(), "Csrf")
        body = {"settings": {"wpm": 22}}
        self.assertEqual(c.req("PUT", "/api/settings", body, csrf=False).status_code, 403)
        self.assertEqual(c.req("PUT", "/api/settings", body, origin="https://evil.example").status_code, 403)
        self.assertEqual(c.req("PUT", "/api/settings", body).status_code, 200)

    def test_data_sync_between_devices(self):
        tok = make_invite()
        mob = Client()
        mob.register(tok, "Sync", device="mobil")
        pc = Client()
        pc.login("Sync")
        r = mob.req("PUT", "/api/settings", {"settings": {"wpm": 25, "fwpm": 30, "freq": 650, "volume": 0.2,
                                                          "evil": "x"}})
        self.assertEqual(r.get_json()["settings"], {"wpm": 25, "fwpm": 25, "freq": 650})
        mob.req("PUT", "/api/progress", {"level": 4, "introduced": ["K", "M", "U", "Č"]})
        pc.req("PUT", "/api/progress", {"level": 4, "introduced": ["R"]})  # union only
        les = {"id": "abcdef12-0001", "at": "2026-11-03T10:00:00Z", "device": "mobil", "level": 4, "durS": 300,
               "trials": 50, "correct": 46, "acc": 0.92, "ttr": 640, "wpm": 25, "fwpm": 25,
               "detail": {"perChar": [{"ch": "K", "n": 10, "acc": 0.9, "ttr": 600}, {"ch": "<b>", "n": 1}],
                          "confusions": [{"pair": "K→R", "n": 2}]}}
        self.assertEqual(mob.req("POST", "/api/lessons", {"lessons": [les, les]}).get_json()["saved"],
                         ["abcdef12-0001", "abcdef12-0001"])
        mob.req("POST", "/api/lessons", {"lessons": [les]})  # sending again
        d = pc.req("GET", "/api/data").get_json()
        self.assertEqual(d["settings"]["wpm"], 25)
        self.assertEqual(d["progress"]["level"], 4)
        self.assertEqual(d["progress"]["introduced"], ["K", "M", "U", "R"])
        self.assertEqual(len(d["lessons"]), 1)
        self.assertNotIn("detail", d["lessons"][0])
        ex = pc.req("GET", "/api/export").get_json()
        self.assertEqual(ex["lessons"][0]["detail"]["perChar"], [{"ch": "K", "n": 10, "acc": 0.9, "ttr": 600}])
        self.assertEqual(pc.req("PUT", "/api/progress", {"level": 99}).status_code, 400)

    def test_export_and_delete(self):
        c = Client()
        c.register(make_invite(), "Smazat", age_group="60+")
        c.req("PUT", "/api/progress", {"level": 3, "introduced": ["K"]})
        r = c.req("GET", "/api/export")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        ex = r.get_json()
        self.assertEqual(ex["account"]["nick"], "Smazat")
        self.assertNotIn("pw_hash", ex["account"])
        self.assertEqual(c.req("POST", "/api/account/delete", {"password": "spatne"}).status_code, 403)
        self.assertEqual(c.req("POST", "/api/account/delete", {"password": "Tajne-heslo1"}).status_code, 200)
        con = connect()
        self.assertIsNone(con.execute("SELECT 1 FROM users WHERE nick='Smazat'").fetchone())
        self.assertEqual(con.execute("SELECT COUNT(*) FROM progress p LEFT JOIN users u ON u.id=p.user_id "
                                     "WHERE u.id IS NULL").fetchone()[0], 0)
        self.assertEqual(Client().login("Smazat").status_code, 403)

    def test_roles_and_invites(self):
        r = self.admin.req("POST", "/api/invites", {"role": "trener", "note": "Petr"})
        self.assertEqual(r.status_code, 201)
        tr = Client()
        tr.register(r.get_json()["token"], "Trenér Petr")
        self.assertEqual(tr.req("POST", "/api/invites", {"role": "admin"}).status_code, 403)
        r2 = tr.req("POST", "/api/invites", {"role": "zak"})
        self.assertEqual(r2.status_code, 201)
        Client().register(r2.get_json()["token"], "Žák Pavel")
        nicks = [u["nick"] for u in tr.req("GET", "/api/users").get_json()["users"]]
        self.assertEqual(nicks, ["Žák Pavel"])
        self.assertGreater(len(self.admin.req("GET", "/api/users").get_json()["users"]), 2)
        # the administrator only manages, does not train
        self.assertEqual(self.admin.req("PUT", "/api/progress", {"level": 3}).status_code, 403)
        self.assertEqual(self.admin.req("POST", "/api/lessons", {"lessons": []}).status_code, 403)
        self.assertEqual(self.admin.req("GET", "/api/data").status_code, 200)
        student = Client()
        student.login("Žák Pavel")
        self.assertEqual(student.req("GET", "/api/users").status_code, 403)
        self.assertEqual(student.req("POST", "/api/invites", {}).status_code, 403)
        # the only admin must not demote or delete themselves
        me = self.admin.req("GET", "/api/me").get_json()["user"]["id"]
        self.assertEqual(self.admin.req("PATCH", f"/api/users/{me}", {"role": "zak"}).status_code, 400)
        self.assertEqual(self.admin.req("POST", "/api/account/delete", {"password": "Tajne-heslo1"}).status_code, 400)

    def test_password_change_logs_out_others(self):
        a = Client()
        a.register(make_invite(), "Zmena")
        b = Client()
        b.login("Zmena")
        self.assertEqual(a.req("POST", "/api/password", {"old": "Tajne-heslo1", "new": "Nove-heslo2"}).status_code, 200)
        self.assertEqual(b.req("GET", "/api/data").status_code, 403)
        self.assertEqual(a.req("GET", "/api/data").status_code, 200)
        self.assertEqual(Client().login("Zmena", "Nove-heslo2").status_code, 200)

    def test_training_reset(self):
        a = Client()
        a.register(make_invite(), "Reset")
        b = Client()
        b.login("Reset")
        ep = a.req("GET", "/api/data").get_json()["epoch"]
        les = {"id": "reset-0001", "at": "2026-11-03T10:00:00Z", "level": 5, "trials": 40, "correct": 39}
        a.req("POST", "/api/lessons", {"lessons": [les], "epoch": ep})
        a.req("PUT", "/api/progress", {"level": 5, "introduced": ["K"], "epoch": ep})
        self.assertEqual(a.req("POST", "/api/training/reset", {"password": "spatne"}).status_code, 403)
        new = a.req("POST", "/api/training/reset", {"password": "Tajne-heslo1"}).get_json()["epoch"]
        self.assertEqual(new, ep + 1)
        d = a.req("GET", "/api/data").get_json()
        self.assertEqual((d["progress"], d["lessons"]), (None, []))
        # a second device with an old epoch must not upload old progress or lessons
        les2 = {**les, "id": "reset-0002"}
        self.assertEqual(b.req("POST", "/api/lessons", {"lessons": [les2], "epoch": ep}).status_code, 409)
        self.assertEqual(b.req("PUT", "/api/progress", {"level": 5, "epoch": ep}).status_code, 409)
        self.assertEqual(b.req("PUT", "/api/progress", {"level": 2, "epoch": new}).status_code, 200)
        # the administrator resets someone else; the administrator has no training
        uid = a.req("GET", "/api/me").get_json()["user"]["id"]
        self.assertEqual(self.admin.req("POST", f"/api/users/{uid}/reset-training").get_json()["epoch"], new + 1)
        me = self.admin.req("GET", "/api/me").get_json()["user"]["id"]
        self.assertEqual(self.admin.req("POST", f"/api/users/{me}/reset-training").status_code, 400)
        self.assertEqual(self.admin.req("POST", "/api/training/reset", {"password": "Tajne-heslo1"}).status_code, 403)

    def test_stats(self):
        c = Client()
        c.register(make_invite(), "Stat")
        self.assertEqual(c.req("GET", "/api/stats").get_json(), {"lessons": 0, "chars": {}})
        les = []
        for i in range(8):  # 3 older lessons with a worse K, 5 recent ones with a better one
            good = i >= 3
            les.append({"id": f"stat-{i:04d}", "at": f"2026-11-0{i + 1}T10:00:00Z", "level": 3, "trials": 30,
                        "correct": 27, "detail": {"perChar": [
                            {"ch": "K", "n": 10, "acc": 1.0 if good else 0.6, "ttr": 500 if good else 900},
                            {"ch": "M", "n": 4, "acc": 0.75, "ttr": 700}, {"ch": "U", "n": 0}],
                            "confusions": [{"pair": "K→R", "n": 0 if good else 4}, {"pair": "M→K", "n": 1}]}})
        les.append({"id": "stat-0099", "at": "2026-10-01T10:00:00Z", "level": 3, "trials": 1, "correct": 1})
        c.req("POST", "/api/lessons", {"lessons": les})
        d = c.req("GET", "/api/stats").get_json()
        self.assertEqual(d["lessons"], 9)
        self.assertEqual(set(d["chars"]), {"K", "M"})
        k = d["chars"]["K"]
        self.assertEqual(k["n"], 80)
        self.assertAlmostEqual(k["acc"], (3 * 0.6 + 5 * 1.0) / 8)
        self.assertEqual(k["ttr"], 500)  # weighted by correct answers: 50 × 500 vs. 18 × 900
        self.assertEqual(k["recent"], {"n": 50, "acc": 1.0, "ttr": 500})
        self.assertEqual(k["before"], {"n": 30, "acc": 0.6, "ttr": 900})
        self.assertEqual(len(k["hist"]), 8)
        self.assertEqual(k["hist"][0], {"at": "2026-11-01T10:00:00Z", "n": 10, "acc": 0.6, "ttr": 900})
        self.assertEqual(k["conf"], [{"ans": "R", "n": 12}])
        self.assertEqual(d["chars"]["M"]["conf"], [{"ans": "K", "n": 8}])
        # the administrator does not train
        self.assertEqual(self.admin.req("GET", "/api/stats").status_code, 403)

    def test_cli_invite(self):
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin_main(["pozvanka", "zak", "test"])
        lines = [ln for ln in out.getvalue().splitlines() if "#pozvanka=" in ln]
        self.assertEqual([ln.split()[0] for ln in lines], ["home:", "outside:"])
        tok = lines[0].split("#pozvanka=")[1].strip()
        self.assertEqual(Client().register(tok, "Z CLI").status_code, 201)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin_main(["invite", "zak"])  # English command (the Czech one above is an alias)
        self.assertEqual(len([ln for ln in out.getvalue().splitlines() if "#pozvanka=" in ln]), 2)


class CoachApiTest(unittest.TestCase):
    def test_questionnaire_flow(self):
        c = Client()
        c.register(make_invite(), "Dotaznik")
        q = c.req("GET", "/api/coach/questions").get_json()["questions"]
        self.assertGreaterEqual(len(q), 12)
        self.assertIsNone(c.req("GET", "/api/coach").get_json()["archetype"])
        self.assertEqual(c.req("POST", "/api/coach/profile", {"answers": "x"}).status_code, 400)
        r = c.req("POST", "/api/coach/profile", {"answers": {"age": "senior", "hearing": "hard", "reading": "hard"}})
        d = r.get_json()
        self.assertEqual(d["archetype"], "Z08")
        self.assertEqual(d["modifiers"], ["M18", "M15"])
        self.assertTrue(d["archetypeName"].startswith("Senior"))
        # answers are not stored – neither in the DB nor in the export
        con = connect()
        row = dict(con.execute("SELECT * FROM coach c JOIN users u ON u.id = c.user_id WHERE u.nick = 'Dotaznik'")
                   .fetchone())
        con.close()
        self.assertNotIn("hard", json_dumps(row))
        ex = c.req("GET", "/api/export").get_json()
        self.assertEqual(ex["coach"]["archetype"], "Z08")
        self.assertNotIn("answers", ex["coach"])
        # a training reset resets the level, the questionnaire stays
        con = connect()
        con.execute("UPDATE coach SET ulevel = 2 WHERE user_id = (SELECT id FROM users WHERE nick = 'Dotaznik')")
        con.close()
        c.req("POST", "/api/training/reset", {"password": "Tajne-heslo1"})
        d = c.req("GET", "/api/coach").get_json()
        self.assertEqual(d["ulevel"], 1)
        self.assertEqual(d["archetype"], "Z08")

    def test_plan_level_plateau(self):
        c = Client()
        c.register(make_invite(), "Planovac")
        c.req("PUT", "/api/progress", {"level": 6, "introduced": ["K", "M", "U", "R", "E", "S"]})
        les = []
        for i, (lv, h) in enumerate([(2, 0), (3, 1), (4, 2), (5, 3), (6, 30), (6, 50), (6, 70)]):
            les.append({"id": f"plan-{i:04d}", "at": f"2026-11-0{1 + h // 24}T{h % 24:02d}:00:00Z", "device": "pc",
                        "level": lv, "durS": 600, "trials": 60, "correct": 54, "acc": 0.9, "ttr": 700 - i * 20,
                        "wpm": 20, "fwpm": 15, "detail": {"perChar": [{"ch": "K", "n": 10, "acc": 0.9, "ttr": 600}]}})
        c.req("POST", "/api/lessons", {"lessons": les})
        d = c.req("GET", "/api/coach").get_json()
        self.assertEqual(d["level"], 6)
        self.assertEqual(d["plan"]["source"], "data")
        self.assertEqual(d["plan"]["added"], 4)
        self.assertEqual(d["plan"]["rate"], 10)
        self.assertEqual(d["levelInfo"]["ulevel"], 1)
        self.assertEqual(d["plateau"]["sessions"], 3)
        self.assertIn("reaction", d["plateau"]["process"])

    def test_speed_applied_to_settings(self):
        """M6: two sessions ≥ 90 % in U2 → the coach shortens the gaps and writes them to the settings; autoSpeed=0 only suggests."""
        def run(nick, auto):
            c = Client()
            c.register(make_invite(), nick)
            c.req("PUT", "/api/settings", {"settings": {"wpm": 20, "fwpm": 15, "autoSpeed": auto}})
            c.req("PUT", "/api/progress", {"level": 51, "introduced": []})
            con = connect()
            con.execute("INSERT INTO coach (user_id, ulevel, updated_at) SELECT id, 2, 'x' FROM users WHERE nick = ?",
                        (nick,))
            con.close()
            les = [{"id": f"sp-{nick}-{i}", "at": f"2026-11-0{1 + i}T10:00:00Z", "device": "pc", "level": 51,
                    "durS": 600, "trials": 80, "correct": 74, "acc": 0.93, "ttr": 550, "wpm": 20, "fwpm": 15,
                    "detail": {"perChar": [], "gapLog": [[20, 1], [40, 0]],
                               "fluency": {"n": 30, "acc": 0.9, "ttr": 500, "wpm": 20, "fwpm": 18}}} for i in range(2)]
            c.req("POST", "/api/lessons", {"lessons": les})
            return c, c.req("GET", "/api/coach").get_json()["speed"]
        c, sp = run("Tempo1", 1)
        self.assertEqual(sp["change"]["kind"], "gaps")
        self.assertTrue(sp["change"]["applied"])
        self.assertEqual(c.req("GET", "/api/data").get_json()["settings"]["fwpm"], 16)
        self.assertIsNone(c.req("GET", "/api/coach").get_json()["speed"]["change"])  # idempotent
        ex = c.req("GET", "/api/export").get_json()
        det = json.loads(ex["lessons"][0]["detail"]) if isinstance(ex["lessons"][0]["detail"], str) else ex["lessons"][0]["detail"]
        self.assertEqual(det["gapLog"], [[20, 1], [40, 0]])
        self.assertEqual(det["fluency"]["fwpm"], 18)
        c, sp = run("Tempo0", 0)
        self.assertFalse(sp["change"]["applied"])
        self.assertEqual((sp["fwpm"], c.req("GET", "/api/data").get_json()["settings"]["fwpm"]), (15, 15))

    def test_admin_no_coach(self):
        self.assertEqual(ApiTest.admin.req("GET", "/api/coach").status_code, 403)


def json_dumps(x):
    import json
    return json.dumps(x)


class DetailM4Test(unittest.TestCase):
    def test_clean_detail_m4(self):
        from server.api import clean_detail
        d = clean_detail({"perChar": [], "confusions": [], "diff": 1.3, "diffLog": [[20, 1.15], ["x", 1], [25, 9]],
                          "warmup": {"n": 12, "acc": 0.83, "ttr": 640, "gapH": 18.5, "evil": 1},
                          "adv": "confirm", "evil": "<b>"})
        self.assertEqual(d["diff"], 1.3)
        self.assertEqual(d["diffLog"], [[20, 1.15]])
        self.assertEqual(d["warmup"], {"n": 12, "acc": 0.83, "ttr": 640, "gapH": 18.5})
        self.assertEqual(d["adv"], "confirm")
        self.assertNotIn("evil", d)
        self.assertNotIn("adv", clean_detail({"adv": "nesmysl"}))
        self.assertNotIn("warmup", clean_detail({"warmup": {"n": 0}}))


class DetailM5Test(unittest.TestCase):
    def test_clean_detail_m5(self):
        from server.api import clean_detail
        d = clean_detail({"fatigue": {"base": {"acc": 0.9, "ttr": 520, "n": 30, "x": 1},
                                      "events": [{"t": 300, "kind": "ttr", "ttrUp": 1.31, "accDrop": 0.02,
                                                  "action": "pause"}, {"t": 5, "kind": "evil"},
                                                 {"t": 400, "kind": "acc", "action": "<b>"}]},
                          "pauses": [[300, 240], ["a", 1], [10, 999999]]})
        self.assertEqual(d["fatigue"]["base"], {"acc": 0.9, "ttr": 520, "n": 30})
        self.assertEqual(len(d["fatigue"]["events"]), 2)
        self.assertEqual(d["fatigue"]["events"][0]["action"], "pause")
        self.assertIsNone(d["fatigue"]["events"][1]["action"])
        self.assertEqual(d["pauses"], [[300, 240]])
        self.assertNotIn("fatigue", clean_detail({"fatigue": "x"}))




class CopyApiTest(unittest.TestCase):
    """M7: copy-behind lessons (mode), copy-behind detail, test-history → U3."""

    def test_copy_lesson_and_test_history(self):
        c = Client()
        self.assertEqual(c.register(make_invite(), "Skluzak").status_code, 201)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            admin_main(["test-historie", "Skluzak", "--skluz-krok", "2"])
        co = c.req("GET", "/api/coach").get_json()
        self.assertEqual(co["ulevel"], 3)
        self.assertTrue(co["copy"]["available"])
        self.assertEqual(co["copy"]["step"], 2)
        self.assertEqual(len(co["copy"]["chars"]), 51)
        det = {"copy": {"step": 2, "content": "groups", "gapX": 2, "ok": 70, "sub": 5, "del": 5, "ins": 2, "n": 80,
                        "acc": 0.85, "lagMs": 420, "lagP90": 1100, "lagCh": 0.5, "lagChP90": 1, "lagChMax": 3,
                        "drift": 0.5, "words": {"n": 24, "ok": 18}, "rounds": 4,
                        "confusions": [{"pair": "S→H", "n": 2}], "perChar": [{"ch": "K", "n": 5, "acc": 0}]},
               "evil": "x"}
        les = {"id": "copy-lesson-0001", "at": "2026-11-04T10:00:00Z", "mode": "skluz", "level": 51, "durS": 300,
               "trials": 80, "correct": 70, "acc": 0.85, "ttr": 500, "wpm": 20, "fwpm": 20, "detail": det}
        bad = {**les, "id": "copy-lesson-0002", "mode": "hlava"}
        r = c.req("POST", "/api/lessons", {"lessons": [les, bad]}).get_json()
        self.assertEqual(r["saved"], ["copy-lesson-0001"])
        data = c.req("GET", "/api/data").get_json()
        mine = [x for x in data["lessons"] if x["id"] == "copy-lesson-0001"][0]
        self.assertEqual(mine["mode"], "skluz")
        self.assertIsNone(mine["ttr"])  # copy behind has no TTR
        self.assertTrue(all(x["mode"] == "znak" for x in data["lessons"] if x["id"].startswith("test-znak")))
        ex = json.loads(c.req("GET", "/api/export").data)
        d = [x for x in ex["lessons"] if x["id"] == "copy-lesson-0001"][0]["detail"]
        self.assertEqual(set(d), {"copy"})
        self.assertNotIn("perChar", d["copy"])
        self.assertEqual(d["copy"]["lagChMax"], 3)
        self.assertEqual(d["copy"]["confusions"], [{"pair": "S→H", "n": 2}])
        # character statistics only from character lessons
        st = c.req("GET", "/api/stats").get_json()
        self.assertEqual(st["lessons"], 2)
        # test-history refuses an account with its own lessons
        with self.assertRaises(SystemExit):
            admin_main(["test-historie", "Skluzak"])

    def test_u4_test_history_and_m8_detail(self):
        """M8: test-history --level 4 → U4 and step 7; copy-behind detail with the new fields and fatigue."""
        import contextlib
        import io
        c = Client()
        self.assertEqual(c.register(make_invite(), "Uctyrka").status_code, 201)
        with contextlib.redirect_stdout(io.StringIO()):
            admin_main(["test-historie", "Uctyrka", "--uroven", "4"])
        co = c.req("GET", "/api/coach").get_json()
        self.assertEqual(co["ulevel"], 4)
        self.assertEqual((co["copy"]["step"], co["copy"]["content"], co["copy"]["wpm"]), (7, "abbr", 20))
        self.assertEqual(co["levelInfo"]["next"]["target"], 5)
        det = {"copy": {"step": 11, "content": "mix", "gapX": 1, "wpm": 21, "markLag": 2, "ok": 70, "sub": 5,
                        "del": 5, "ins": 0, "n": 80, "acc": 0.875, "lagW": 0.5, "lagWP90": 1, "lagCh": 2,
                        "words": {"n": 24, "ok": 20}, "rounds": 4, "confusions": []},
               "fatigue": {"base": {"acc": 0.95, "miss": 0.01, "n": 60},
                           "events": [{"t": 200, "kind": "miss", "accDrop": 0.05, "missUp": 0.12, "action": "continue"},
                                      {"t": 250, "kind": "ttr", "action": "pause"}]}}
        les = {"id": "copy-u4-0001", "at": "2026-11-04T10:00:00Z", "mode": "skluz", "level": 51, "durS": 300,
               "trials": 80, "correct": 70, "acc": 0.875, "wpm": 21, "fwpm": 21, "detail": det}
        self.assertEqual(c.req("POST", "/api/lessons", {"lessons": [les]}).get_json()["saved"], ["copy-u4-0001"])
        ex = json.loads(c.req("GET", "/api/export").data)
        d = [x for x in ex["lessons"] if x["id"] == "copy-u4-0001"][0]["detail"]
        self.assertEqual((d["copy"]["content"], d["copy"]["wpm"], d["copy"]["markLag"], d["copy"]["lagW"]),
                         ("mix", 21, 2, 0.5))
        self.assertEqual([e["kind"] for e in d["fatigue"]["events"]], ["miss"])  # no 'ttr' in copy behind
        self.assertEqual(d["fatigue"]["base"]["miss"], 0.01)
        # step 13 → U4 automatically; an invalid option → error
        c2 = Client()
        self.assertEqual(c2.register(make_invite(), "Uctyrka2").status_code, 201)
        with contextlib.redirect_stdout(io.StringIO()):
            admin_main(["test-historie", "Uctyrka2", "--skluz-krok", "13"])
        co2 = c2.req("GET", "/api/coach").get_json()
        self.assertEqual((co2["ulevel"], co2["copy"]["step"], co2["copy"]["wpm"]), (4, 13, 25))
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            admin_main(["test-historie", "Uctyrka2", "--uroven", "5"])


class LanguageTest(unittest.TestCase):
    """I18N (0.9.0): server texts in the language from X-Lang, the lang cookie, the account setting, Accept-Language."""

    def test_error_language(self):
        c = app.test_client()
        bad = {"nick": "nobody", "password": "x"}
        def login(**headers):
            return c.post("/api/login", json=bad, headers={"Host": HOST, **headers}, base_url=f"https://{HOST}").get_json()["error"]
        self.assertEqual(login(), "Wrong nickname or password.")
        self.assertEqual(login(**{"X-Lang": "cs"}), "Špatná přezdívka nebo heslo.")
        self.assertEqual(login(**{"Accept-Language": "cs-CZ,en;q=0.5"}), "Špatná přezdívka nebo heslo.")
        self.assertEqual(login(**{"Accept-Language": "cs", "X-Lang": "en"}), "Wrong nickname or password.")
        self.assertEqual(login(**{"X-Lang": "xx"}), "Wrong nickname or password.")  # unsupported → fallback

    def test_account_language_setting(self):
        c = Client()
        c.register(make_invite(), "Lingua")
        r = c.req("PUT", "/api/settings", {"settings": {"lang": "cs", "wpm": 20}})
        self.assertEqual(r.get_json()["settings"]["lang"], "cs")
        self.assertNotIn("lang", c.req("PUT", "/api/settings", {"settings": {"lang": "xx", "wpm": 21}}).get_json()["settings"].keys() - {"lang"})
        self.assertEqual(c.req("GET", "/api/data").get_json()["settings"]["lang"], "cs")
        # without X-Lang / cookie / Accept-Language the stored setting decides
        q = c.req("GET", "/api/coach/questions").get_json()["questions"]
        self.assertEqual(q[0]["text"], "Kolik ti je let?")
        r = c.c.open("/api/coach/questions", headers={"Host": HOST, "X-Lang": "en"}, base_url=f"https://{HOST}")
        self.assertEqual(r.get_json()["questions"][0]["text"], "How old are you?")

    def test_invite_state_codes(self):
        coach = Client()
        coach.register(make_invite("trener"), "CoachLang")
        self.assertEqual(coach.req("POST", "/api/invites", {"role": "zak"}).status_code, 201)
        states = {i["state"] for i in coach.req("GET", "/api/invites").get_json()["invites"]}
        self.assertEqual(states, {"valid"})  # a code, translated by the client


class SiteTest(unittest.TestCase):
    """0.8.2: the outside address = a separate app "Morse outside"; E3: addresses from the configuration, not from code."""

    def test_manifest_by_host(self):
        c = app.test_client()
        home = c.get("/manifest.webmanifest", headers={"Host": "192.0.2.10"}).get_json(force=True)
        pub = c.get("/manifest.webmanifest", headers={"Host": "venku.example.org"}).get_json(force=True)
        hdr = c.get("/manifest.webmanifest", headers={"Host": "127.0.0.1:8090", "X-Morse-Entry": "public"}).get_json(force=True)
        self.assertEqual(home["name"], "Morse trainer")
        self.assertEqual(pub["name"], "Morse outside")
        self.assertEqual(hdr["name"], "Morse outside")
        # I18N: the manifest follows the lang cookie, then Accept-Language
        cs = c.get("/manifest.webmanifest", headers={"Host": "192.0.2.10", "Accept-Language": "cs-CZ,cs;q=0.9"}).get_json(force=True)
        self.assertEqual((cs["name"], cs["lang"]), ("Morse trenažer", "cs"))
        c.set_cookie("venku.example.org", "lang", "cs")  # werkzeug 2.2 API (server_name, key, value)
        pub_cs = c.get("/manifest.webmanifest", headers={"Host": "venku.example.org"}).get_json(force=True)
        self.assertEqual(pub_cs["name"], "Morse venku")
        self.assertTrue(all(i["src"].startswith("/icons/venku-") for i in pub["icons"]))
        for i in pub["icons"]:
            self.assertEqual(c.get(i["src"]).status_code, 200)

    def test_site_config(self):
        r = app.test_client().get("/site-config.js")
        self.assertEqual(r.mimetype, "text/javascript")
        js = r.get_data(as_text=True)
        self.assertIn('export const HOME_URL = "https://192.0.2.10/";', js)
        self.assertIn('export const PUBLIC_URL = "https://venku.example.org/";', js)

    def test_no_install_specific_addresses_in_code(self):
        from pathlib import Path
        import re
        root = Path(__file__).resolve().parent.parent
        for d in ("server", "web", "deploy"):
            for f in (root / d).rglob("*"):
                if f.is_file() and f.suffix in (".py", ".js", ".html", ".conf", ".sh", ".service", ".webmanifest"):
                    t = f.read_text(encoding="utf-8")
                    self.assertNotRegex(t, r"[a-z0-9-]+\.a\.pinggy\.link", f.name)
                    self.assertNotRegex(t, r"\b192\.168\.[1-9]\d*\.\d+", f.name)


class PublicEntryTest(unittest.TestCase):
    """E3: login from outside is protected by the app only – administrator only from the home network, IP blocking."""

    def test_admin_only_from_home(self):
        a = Client()
        self.assertEqual(a.register(make_invite("admin"), "Spravce2").status_code, 201)
        pub = {"X-Morse-Entry": "public"}
        r = a.c.open("/api/me", headers={"Host": HOST, **pub}, base_url=f"https://{HOST}")
        self.assertEqual(r.status_code, 403)  # an administrator session is not valid from outside
        r = a.c.open("/api/login", method="POST", json={"nick": "Spravce2", "password": "Tajne-heslo1"},
                     headers={"Host": HOST, "Origin": f"https://{HOST}", **pub}, base_url=f"https://{HOST}")
        self.assertEqual(r.status_code, 403)
        self.assertIn("home network", r.get_json()["error"])
        self.assertEqual(a.login("Spravce2").status_code, 200)  # doma ano
        z = Client()
        self.assertEqual(z.register(make_invite(), "Venkovni").status_code, 201)
        r = z.c.open("/api/login", method="POST", json={"nick": "Venkovni", "password": "Tajne-heslo1"},
                     headers={"Host": HOST, "Origin": f"https://{HOST}", **pub}, base_url=f"https://{HOST}")
        self.assertEqual(r.status_code, 200)  # a student from outside is

    def test_ip_ban(self):
        from server import auth
        ip = "ip:203.0.113.9"
        for n in range(auth.FAIL_LIMITS["ip"]):
            auth.note_fail(ip, f"nick:x{n}")
        self.assertTrue(auth.too_many(ip, "nick:nekdo"))
        auth.clear_fails(ip)                      # the 15 min window expires …
        self.assertTrue(auth.too_many(ip))        # … the 24 h block lasts
        self.assertTrue(auth.too_many("inv:203.0.113.9"))
        auth._bans.clear()
        self.assertFalse(auth.too_many(ip))

    def test_password_rules(self):
        from server.auth import password_rules
        self.assertEqual(password_rules("Tajne-heslo1"), [])
        self.assertEqual(password_rules("Žluť-kůň7ř"), [])          # diacritics count as letters
        self.assertEqual(len(password_rules("")), 5)
        self.assertIn("lower", password_rules("TAJNE-HESLO1"))
        self.assertIn("upper", password_rules("tajne-heslo1"))
        self.assertIn("digit", password_rules("Tajne-heslo"))
        self.assertIn("special", password_rules("Tajneheslo1"))
        self.assertIn("length", password_rules("Ta-1" + "x" * 29))   # 33 characters
        self.assertEqual(password_rules("Ta-1" + "x" * 28), [])      # 32 characters
        self.assertIn("length", password_rules("Tajne-1"))           # 7 characters
        self.assertIn("nick", password_rules("Xpepa-Veselý1", "Pepa"))
        c = Client()
        r = c.register(make_invite(), "Kratky", pw="desetznaku")
        self.assertEqual(r.status_code, 400)
        self.assertIn("uppercase", r.get_json()["error"])
        self.assertEqual(c.register(make_invite(), "Kratky", pw="Deset-zn4k").status_code, 201)


class PasswordPolicyTest(unittest.TestCase):
    """E3: forced password change for existing accounts and a new-password link (the training stays)."""

    def test_forced_change(self):
        c = Client()
        self.assertEqual(c.register(make_invite(), "Stary").status_code, 201)
        con = connect()
        con.execute("UPDATE users SET pw_change = 1 WHERE nick = 'Stary'")   # as after migration 5
        con.close()
        me = c.req("GET", "/api/me").get_json()
        self.assertTrue(me["user"]["pw_change"])
        r = c.req("GET", "/api/coach")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.get_json()["pw_change"])
        self.assertTrue(c.login("Stary").get_json()["user"]["pw_change"])
        self.assertEqual(c.req("POST", "/api/password", {"old": "Tajne-heslo1", "new": "Tajne-heslo1"}).status_code, 400)
        self.assertEqual(c.req("POST", "/api/password", {"old": "Tajne-heslo1", "new": "slabe"}).status_code, 400)
        self.assertEqual(c.req("POST", "/api/password", {"old": "Tajne-heslo1", "new": "Nove-heslo2"}).status_code, 200)
        self.assertFalse(c.req("GET", "/api/me").get_json()["user"]["pw_change"])
        self.assertEqual(c.req("GET", "/api/coach").status_code, 200)

    def test_reset_link(self):
        coach, student, other = Client(), Client(), Client()
        self.assertEqual(coach.register(make_invite("trener"), "TrenerR").status_code, 201)
        tok = coach.req("POST", "/api/invites", {"role": "zak"}).get_json()["token"]
        self.assertEqual(student.register(tok, "ZakR").status_code, 201)
        self.assertEqual(other.register(make_invite(), "CiziR").status_code, 201)
        uid = student.req("GET", "/api/me").get_json()["user"]["id"]
        cid = other.req("GET", "/api/me").get_json()["user"]["id"]
        self.assertEqual(coach.req("POST", f"/api/users/{cid}/password-link").status_code, 404)  # someone else's student
        self.assertEqual(student.req("POST", f"/api/users/{uid}/password-link").status_code, 403)     # a student must not
        old = coach.req("POST", f"/api/users/{uid}/password-link").get_json()["token"]
        link = coach.req("POST", f"/api/users/{uid}/password-link").get_json()["token"]
        anon = Client()
        self.assertEqual(anon.req("POST", "/api/invite/check", {"token": old}).status_code, 404)  # the older one revoked
        self.assertEqual(anon.req("POST", "/api/invite/check", {"token": link}).get_json()["reset"], "ZakR")
        self.assertEqual(anon.register(link, "Zneuziti").status_code, 404)  # a link is not an invitation
        self.assertEqual(anon.req("POST", "/api/password/reset", {"token": tok, "password": "Nove-heslo2"}).status_code, 404)
        self.assertEqual(anon.req("POST", "/api/password/reset", {"token": link, "password": "slabe"}).status_code, 400)
        r = anon.req("POST", "/api/password/reset", {"token": link, "password": "Nove-heslo2"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user"]["nick"], "ZakR")
        self.assertEqual(student.req("GET", "/api/me").status_code, 403)          # the old login revoked
        self.assertEqual(Client().login("ZakR").status_code, 403)              # the old password is invalid
        self.assertEqual(Client().login("ZakR", "Nove-heslo2").status_code, 200)
        self.assertEqual(anon.req("POST", "/api/password/reset", {"token": link, "password": "Dalsi-heslo3"}).status_code, 404)

    def test_cli_reset_link(self):
        import io
        import contextlib
        c = Client()
        self.assertEqual(c.register(make_invite(), "CliReset").status_code, 201)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            admin_main(["obnova", "CliReset"])
        tok = [ln for ln in out.getvalue().splitlines() if "#heslo=" in ln][0].split("#heslo=")[1].strip()
        r = Client().req("POST", "/api/password/reset", {"token": tok, "password": "Nove-heslo2"})
        self.assertEqual(r.status_code, 200)


class DebugTraceTest(unittest.TestCase):
    """V1: debug trace of the training only for accounts with tracing on, deletion after 180 days."""

    def test_trace_only_when_enabled(self):
        import io
        import contextlib
        c = Client()
        self.assertEqual(c.register(make_invite(), "Ladeni").status_code, 201)
        tr = {"lesson_id": "abcdefgh-1", "kind": "znak", "at": "2026-11-05T10:00:00Z",
              "data": {"meta": {"level": 3}, "ev": [[0, "p", ["K", 20, 15, 300, 1, ""]], [900, "a", ["K", 600, 1]]]}}
        self.assertFalse(c.req("GET", "/api/me").get_json()["user"]["debug"])
        self.assertEqual(c.req("POST", "/api/trace", tr).get_json()["debug"], False)  # vypnuto → zahodit
        with contextlib.redirect_stdout(io.StringIO()):
            admin_main(["ladeni", "Ladeni", "zap"])
        self.assertTrue(c.req("GET", "/api/me").get_json()["user"]["debug"])
        self.assertTrue(c.req("POST", "/api/trace", tr).get_json()["ok"])
        self.assertEqual(c.req("POST", "/api/trace", {**tr, "kind": "x"}).status_code, 400)
        big = {**tr, "data": {"ev": ["x" * 1000] * 210}}
        self.assertEqual(c.req("POST", "/api/trace", big).status_code, 413)
        r = c.req("POST", "/api/client-errors", {"errors": [{"msg": "TypeError: x", "stack": "s" * 5000}] * 30})
        self.assertTrue(r.get_json()["ok"])
        con = connect()
        uid = con.execute("SELECT id FROM users WHERE nick = 'Ladeni'").fetchone()[0]
        self.assertEqual(con.execute("SELECT COUNT(*) FROM traces WHERE user_id = ?", (uid,)).fetchone()[0], 1)
        n, ln = con.execute("SELECT COUNT(*), MAX(LENGTH(data)) FROM client_errors WHERE user_id = ?", (uid,)).fetchone()
        self.assertEqual(n, 20)
        self.assertLess(ln, 3000)
        # the export contains the debug data
        exp = json.loads(c.req("GET", "/api/export").get_data(as_text=True))
        self.assertEqual(exp["debug"]["traces"][0]["data"]["meta"]["level"], 3)
        # older than 180 days is deleted on the next write
        con.execute("UPDATE traces SET received = '2020-01-01T00:00:00Z' WHERE user_id = ?", (uid,))
        self.assertTrue(c.req("POST", "/api/trace", tr).get_json()["ok"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM traces WHERE user_id = ?", (uid,)).fetchone()[0], 1)
        # a training reset also deletes the lesson traces
        c.req("POST", "/api/training/reset", {"password": "Tajne-heslo1"})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM traces WHERE user_id = ?", (uid,)).fetchone()[0], 0)
        with contextlib.redirect_stdout(io.StringIO()):
            admin_main(["ladeni-smazat", "Ladeni"])
            admin_main(["ladeni", "Ladeni", "vyp"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM client_errors WHERE user_id = ?", (uid,)).fetchone()[0], 0)
        con.close()


if __name__ == "__main__":
    unittest.main()
