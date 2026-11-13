# SPDX-License-Identifier: EUPL-1.2
"""CW room 1:1 (0.13.0): visibility rules (adults, trainers, children in groups), presence, Knock Knock, connections,
the shared half-duplex channel – unit tests with a fake clock and directory, and API tests incl. trainer groups."""
import threading
import unittest

from test_api import Client, make_invite  # noqa: E402 – sets MORSE_DB to a temporary database first

from server import cwroom as R
from server.cw import room as live_room


def user(uid, nick, role="zak", age="18-59", inviter=None, group=None, off=0, kids=0, disabled=0):
    return {"id": uid, "nick": nick, "role": role, "age_group": age, "invited_by": inviter, "group_id": group,
            "cw_off": off, "cw_kids": kids, "disabled": disabled}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def directory():
    users = {u["id"]: u for u in (
        user(1, "Admin", "admin"),
        user(2, "Coach", "trener", kids=1, inviter=1),
        user(3, "Coach2", "trener", kids=0, inviter=1),
        user(4, "Adult", inviter=2),
        user(5, "Adult2", age="60+", inviter=3),
        user(6, "KidA", age="do15", inviter=2, group=10),
        user(7, "KidB", age="15-17", inviter=2, group=10),
        user(8, "KidC", age="do15", inviter=2, group=11),
        user(9, "KidLoose", age="15-17", inviter=2),
        user(10, "NoAge", age=None, inviter=2, group=10),
        user(11, "Kid2", age="do15", inviter=3, group=12),
        user(12, "Off", inviter=2, off=1),
    )}
    return users, set()


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.users, self.blocks = directory()

    def see(self, a, b):
        u = self.users
        r = R.can_see(u[a], u[b], u, self.blocks)
        self.assertEqual(r, R.can_see(u[b], u[a], u, self.blocks), "must be symmetric")
        return r

    def test_adults_see_adults_and_trainers_not_minors(self):
        self.assertTrue(self.see(4, 5))
        self.assertTrue(self.see(4, 1))
        self.assertTrue(self.see(4, 2) and self.see(4, 3))
        for kid in (6, 7, 8, 9, 10):
            self.assertFalse(self.see(4, kid))
            self.assertFalse(self.see(1, kid))  # the admin is an adult, not a trainer

    def test_children_in_a_group(self):
        self.assertTrue(self.see(6, 7))       # same group
        self.assertTrue(self.see(6, 10))      # no age group = minor
        self.assertFalse(self.see(6, 8))      # another group of the same trainer
        self.assertFalse(self.see(9, 6))      # outside every group: only the trainer
        self.assertTrue(self.see(9, 2))
        self.assertTrue(self.see(6, 2))
        self.assertFalse(self.see(6, 3))      # not their own trainer

    def test_trainer_switch_for_children(self):
        self.assertEqual(R.has_access(self.users[11], self.users), "kids")  # Coach2 has the room off for children
        self.assertFalse(self.see(11, 3))
        self.assertIsNone(R.has_access(self.users[6], self.users))

    def test_single_student_off_and_blocks(self):
        self.assertEqual(R.has_access(self.users[12], self.users), "off")
        self.assertFalse(self.see(12, 4))
        self.blocks.add((4, 5))
        self.assertFalse(self.see(4, 5))
        self.assertFalse(self.see(5, 4))

    def test_trainers_see_each_other(self):
        self.assertTrue(self.see(2, 3))


class RoomTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.dir = directory()
        self.seen = set()
        self.room = R.Room(lambda: self.dir, clock=self.clock, seen=lambda uid: uid in self.seen)

    def tick(self, s):
        self.clock.t += s

    def status(self, viewer, uid):
        return next(u for u in self.room.state(viewer)["users"] if u["id"] == uid)

    def connect(self, a=4, b=5):
        self.room.state(a), self.room.state(b)
        self.assertIsNone(self.room.knock(a, b))
        self.assertIsNone(self.room.answer(b, a, True))

    def test_list_and_status(self):
        st = self.room.state(4)
        self.assertTrue(st["access"])
        self.assertEqual([u["nick"] for u in st["users"]], ["Admin", "Adult2", "Coach", "Coach2"])
        self.assertEqual(self.status(4, 5)["status"], "off")
        self.seen.add(5)
        self.assertEqual(self.status(4, 5)["status"], "app")
        self.room.state(5)
        self.assertEqual(self.status(4, 5)["status"], "room")
        self.tick(R.PRESENT_S + 1)
        self.room.state(4)
        self.assertEqual(self.status(4, 5)["status"], "app")

    def test_no_access(self):
        st = self.room.state(12)
        self.assertEqual(st, {"access": False, "reason": "off"})
        self.assertEqual(self.room.state(11)["reason"], "kids")

    def test_knock_reaches_the_app_outside_the_room(self):
        """0.13.6: the app outside the room tab asks for knocks – the user is reachable (not present) for BELL_S."""
        self.room.state(4)
        self.assertFalse(self.status(4, 5)["reach"])
        self.assertEqual(self.room.knocks_for(5), {"access": True, "knocks": []})
        self.assertTrue(self.status(4, 5)["reach"])
        self.assertNotEqual(self.status(4, 5)["status"], "room")
        self.assertIsNone(self.room.knock(4, 5))
        self.assertEqual(self.room.knocks_for(5)["knocks"], [{"id": 4, "nick": "Adult"}])
        self.assertEqual(self.room.knocks_for(6)["knocks"], [])
        self.assertEqual(self.room.knocks_for(12), {"access": False})
        self.room.state(5)                       # opens the room tab and accepts
        self.assertIsNone(self.room.answer(5, 4, True))
        self.assertEqual(self.room.state(4)["link"]["nick"], "Adult2")
        self.room.hangup(4)
        self.tick(R.BELL_S + 1)                  # the app stopped asking (closed) → not reachable
        self.room.state(4)
        self.assertFalse(self.status(4, 5)["reach"])
        self.assertEqual(self.room.knock(4, 5), "notInRoom")

    def test_knock_accept_and_hangup(self):
        self.room.state(4)
        self.assertEqual(self.room.knock(4, 5), "notInRoom")
        self.room.state(5)
        self.assertEqual(self.room.knock(4, 6), "notFound")  # an adult cannot reach a child
        self.assertIsNone(self.room.knock(4, 5))
        self.assertTrue(self.status(5, 4)["knockIn"])
        self.assertTrue(self.status(4, 5)["knockOut"])
        self.assertIsNone(self.room.answer(5, 4, True))
        st = self.room.state(4)
        self.assertEqual(st["link"]["nick"], "Adult2")
        self.assertEqual(self.status(2, 4)["status"], "linked")
        self.room.state(2)
        self.assertEqual(self.room.knock(2, 4), "busy")
        self.assertIsNone(self.room.hangup(5))
        st = self.room.state(4)
        self.assertIsNone(st["link"])
        self.assertEqual(st["notice"], {"kind": "hangup", "nick": "Adult2"})
        self.assertNotIn("notice", self.room.state(4))  # shown once

    def test_decline_and_expiry(self):
        self.room.state(4), self.room.state(5)
        self.room.knock(4, 5)
        self.assertIsNone(self.room.answer(5, 4, False))
        self.assertEqual(self.room.state(4)["notice"]["kind"], "declined")
        self.room.knock(4, 5)
        for _ in range(int(R.KNOCK_S / 4) + 2):  # both stay in the room, the knock expires
            self.tick(4)
            self.room.state(4), self.room.state(5)
        self.assertEqual(self.room.answer(5, 4, True), "noKnock")

    def test_one_knock_at_a_time(self):
        for u in (4, 5, 2):
            self.room.state(u)
        self.room.knock(4, 5)
        self.room.knock(4, 2)
        self.assertFalse(self.status(5, 4)["knockIn"])
        self.assertTrue(self.status(2, 4)["knockIn"])

    def test_idle_link_ends(self):
        self.connect()
        self.tick(R.LINK_IDLE_S - 1)
        self.assertIsNotNone(self.room.state(4)["link"])
        self.tick(2)
        st = self.room.state(4)  # only this side polls, the other one has been silent for too long
        self.assertIsNone(st["link"])
        self.assertEqual(st["notice"]["kind"], "idle")

    def test_leave_hangs_up(self):
        self.connect()
        self.room.leave(5)
        self.assertEqual(self.room.state(4)["notice"]["kind"], "hangup")

    def test_channel_over_and_receiver(self):
        self.connect()
        err, res = self.room.tx(4, start=True, els=[[0, 60]])
        self.assertIsNone(err)
        oid = res["over"]
        self.assertEqual(self.room.state(4)["channel"], "tx")
        st = self.room.state(5)
        self.assertEqual(st["channel"], "rx")
        self.assertEqual(st["rx"], [{"id": oid, "from": 0, "els": [[0, 60]], "end": False, "t": 0}])
        self.assertEqual(self.room.tx(5, start=True, els=[[0, 60]])[0], "channelBusy")
        self.room.tx(4, over=oid, els=[[120, 300], [100, 110]])  # out of order element dropped
        st = self.room.state(5, over=oid, n=1)
        self.assertEqual(st["rx"][0]["els"], [[120, 300]])
        self.room.tx(4, over=oid, end=True)
        self.assertTrue(self.room.state(5, over=oid, n=2)["rx"][0]["end"])
        self.assertEqual(self.room.state(5)["channel"], "rx")   # busy until it has died away at the receiver
        st = self.room.state(5, done=oid)
        self.assertEqual(st["channel"], "free")
        self.assertIsNone(self.room.tx(5, start=True, els=[[0, 60]])[0])
        self.assertEqual(self.room.state(4)["channel"], "rx")

    def test_receiver_reports_done_with_its_start(self):
        """0.13.2: the receiver frees the channel by `done` in the same request that starts its reply."""
        self.connect()
        _e, res = self.room.tx(4, start=True, els=[[0, 60]])
        self.room.tx(4, over=res["over"], end=True)
        self.tick(0.4)
        st = self.room.state(5)
        self.assertEqual(st["rx"][0]["t"], 400)      # age of the over at the server
        self.assertEqual(self.room.tx(5, start=True, els=[[0, 60]])[0], "channelBusy")
        self.assertIsNone(self.room.tx(5, start=True, els=[[0, 60]], done=res["over"])[0])
        self.assertEqual(self.room.state(4)["channel"], "rx")

    def test_reloaded_receiver_gets_the_open_over_again(self):
        """0.13.3: a receiver that lost its state (reloaded page, new RxPlayout asks over=1, n=0) gets the whole open
        over from its first element; an over it has reported done is not sent again."""
        self.connect()
        _e, res = self.room.tx(4, start=True, els=[[0, 60]])
        self.room.tx(4, over=res["over"], els=[[120, 300]])
        self.room.state(5, over=res["over"], n=2)
        st = self.room.state(5, over=1, n=0)
        self.assertEqual(st["rx"][0]["els"], [[0, 60], [120, 300]])
        self.room.tx(4, over=res["over"], end=True)
        self.room.state(5, done=res["over"])
        self.assertEqual(self.room.state(5, over=res["over"] + 1, n=0)["rx"], [])

    def test_channel_freed_without_receiver_report(self):
        self.connect()
        _e, res = self.room.tx(4, start=True, els=[[0, 60]])
        self.tick(R.OVER_IDLE_S + 0.5)
        self.room.state(5)
        _e, res2 = self.room.tx(4, over=res["over"], els=[[500, 560]])
        self.assertTrue(res2["ended"])      # idle → ended, the late batch is dropped
        self.tick(R.END_GRACE_S + 0.5)
        self.assertEqual(self.room.state(5)["channel"], "free")

    def test_sender_may_start_a_new_over(self):
        self.connect()
        _e, r1 = self.room.tx(4, start=True, els=[[0, 60]])
        self.room.tx(4, over=r1["over"], end=True)
        _e, r2 = self.room.tx(4, start=True, els=[[0, 60]])
        self.assertGreater(r2["over"], r1["over"])
        st = self.room.state(5)
        self.assertEqual([o["id"] for o in st["rx"]], [r1["over"], r2["over"]])

    def test_simultaneous_start_one_winner(self):
        for _ in range(20):
            self.room.clear()
            self.connect()
            results = {}
            barrier = threading.Barrier(2)

            def go(uid):
                barrier.wait()
                results[uid] = self.room.tx(uid, start=True, els=[[0, 50]])[0]
            ts = [threading.Thread(target=go, args=(u,)) for u in (4, 5)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(sorted(results.values(), key=str), [None, "channelBusy"])

    def test_batch_validation(self):
        self.assertEqual(R.clean_elements([[0, 10.4], [20, 30]]), [[0, 10], [20, 30]])
        for bad in ("x", [[0]], [[5, 1]], [[-1, 3]], [[0, True]], [[0, 1]] * (R.BATCH_MAX + 1),
                    [[0, R.OVER_MAX_MS + 1]]):
            self.assertIsNone(R.clean_elements(bad), bad)


class CwApiTest(unittest.TestCase):
    """End to end through Flask: groups, invitations into a group, trainer switches, the room and the channel."""

    @classmethod
    def setUpClass(cls):
        live_room.clear()
        cls.admin = Client()
        assert cls.admin.register(make_invite("admin"), "CwSpravce").status_code == 201
        cls.coach = Client()
        assert cls.coach.register(make_invite("trener"), "CwTrener").status_code == 201

    def student(self, nick, age="18-59", group=None):
        c = Client()
        r = self.coach.req("POST", "/api/invites", {"role": "zak", "group_id": group})
        self.assertEqual(r.status_code, 201, r.get_json())
        consent = {"parent_consent": True} if age == "do15" else {}
        r = c.register(r.get_json()["token"], nick, age_group=age, **consent)
        self.assertEqual(r.status_code, 201, r.get_json())
        c.id = r.get_json()["user"]["id"]
        return c

    def nicks(self, c):
        st = c.req("GET", "/api/cw/state").get_json()
        return st, {u["nick"] for u in st.get("users", [])}

    def test_key_lab(self):
        """0.14.4: the trainer opens the key page to one of their students; coaches always have it."""
        kid = self.student("CwKlic", "do15")
        me = lambda c: c.req("GET", "/api/me").get_json()["user"]["key_lab"]  # noqa: E731
        self.assertFalse(me(kid))
        self.assertTrue(me(self.coach))
        other = Client()
        assert other.register(make_invite("trener"), "CwTrener3").status_code == 201
        self.assertEqual(other.req("PUT", f"/api/users/{kid.id}/key-lab", {"on": True}).status_code, 404)
        self.assertEqual(kid.req("PUT", f"/api/users/{kid.id}/key-lab", {"on": True}).status_code, 403)
        self.assertEqual(self.coach.req("PUT", f"/api/users/{self.coach_id()}/key-lab", {"on": True}).status_code, 404)
        self.assertEqual(self.coach.req("PUT", f"/api/users/{kid.id}/key-lab", {"on": True}).status_code, 200)
        self.assertTrue(me(kid))
        users = {u["nick"]: u for u in self.coach.req("GET", "/api/users").get_json()["users"]}
        self.assertEqual(users["CwKlic"]["key_lab"], 1)
        self.assertEqual(self.admin.req("PUT", f"/api/users/{kid.id}/key-lab", {"on": False}).status_code, 200)
        self.assertFalse(me(kid))

    def coach_id(self):
        return self.coach.req("GET", "/api/me").get_json()["user"]["id"]

    def test_groups_crud(self):
        r = self.coach.req("POST", "/api/groups", {"name": "  Krouzek   A "})
        self.assertEqual(r.status_code, 201)
        gid = r.get_json()["id"]
        self.assertEqual(self.coach.req("POST", "/api/groups", {"name": "Krouzek A"}).status_code, 409)
        self.assertEqual(self.coach.req("POST", "/api/groups", {"name": " "}).status_code, 400)
        kid = self.student("CwDite", "do15", gid)
        groups = self.coach.req("GET", "/api/groups").get_json()["groups"]
        self.assertEqual([(x["name"], x["members"]) for x in groups if x["id"] == gid], [("Krouzek A", 1)])
        self.assertEqual(self.coach.req("PATCH", f"/api/groups/{gid}", {"name": "Krouzek B"}).status_code, 200)
        other = Client()
        assert other.register(make_invite("trener"), "CwTrener2").status_code == 201
        self.assertEqual(other.req("DELETE", f"/api/groups/{gid}").status_code, 404)
        self.assertEqual(other.req("PUT", f"/api/users/{kid.id}/group", {"group_id": None}).status_code, 404)
        self.assertEqual(self.coach.req("DELETE", f"/api/groups/{gid}").status_code, 200)
        users = {u["nick"]: u for u in self.coach.req("GET", "/api/users").get_json()["users"]}
        self.assertIn("CwDite", users)                 # the student stays, only without a group
        self.assertIsNone(users["CwDite"]["group_id"])
        self.assertEqual(kid.req("GET", "/api/me").status_code, 200)

    def test_management_lists(self):
        """0.13.0 User management: users carry the trainer, the minor flag and the trainer's children switch,
        invitations carry the group name."""
        gid = self.coach.req("POST", "/api/groups", {"name": "Sprava"}).get_json()["id"]
        self.student("CwSprDite", "15-17", gid)
        self.student("CwSprDosp", "60+")
        r = self.coach.req("GET", "/api/users").get_json()
        users = {u["nick"]: u for u in r["users"]}
        self.assertIn("kids", r)
        self.assertTrue(users["CwSprDite"]["minor"])
        self.assertFalse(users["CwSprDosp"]["minor"])
        self.assertEqual(users["CwSprDite"]["coach_nick"], "CwTrener")
        self.assertEqual(users["CwSprDite"]["group_id"], gid)
        invites = self.coach.req("GET", "/api/invites").get_json()["invites"]
        self.assertIn("Sprava", {i["group_name"] for i in invites})
        adm = {u["nick"]: u for u in self.admin.req("GET", "/api/users").get_json()["users"]}
        self.assertIn("cw_kids", adm["CwTrener"])       # the administrator sees the trainer's switch
        self.coach.req("DELETE", f"/api/groups/{gid}")

    def test_room_rules_and_connection(self):
        gid = self.coach.req("POST", "/api/groups", {"name": "Deti"}).get_json()["id"]
        a1, a2 = self.student("CwDosp1"), self.student("CwDosp2")
        k1, k2 = self.student("CwKid1", "do15", gid), self.student("CwKid2", "15-17", gid)
        k3 = self.student("CwKid3", "15-17")
        st, _ = self.nicks(k1)
        self.assertEqual(st, {"access": False, "reason": "kids"})   # the trainer has not enabled children yet
        self.assertEqual(self.coach.req("PUT", "/api/cw/kids", {"on": True}).status_code, 200)
        _st, seen = self.nicks(k1)
        self.assertEqual(seen, {"CwTrener", "CwKid2"})
        _st, seen = self.nicks(k3)
        self.assertEqual(seen, {"CwTrener"})                    # outside a group: only the trainer
        self.assertEqual(self.coach.req("PUT", f"/api/users/{k3.id}/group", {"group_id": gid}).status_code, 200)
        _st, seen = self.nicks(k3)
        self.assertEqual(seen, {"CwTrener", "CwKid1", "CwKid2"})
        _st, seen = self.nicks(a1)
        self.assertIn("CwDosp2", seen)
        self.assertIn("CwTrener", seen)
        self.assertFalse(seen & {"CwKid1", "CwKid2", "CwKid3"})
        # trainer switches a student off
        man = self.coach.req("GET", "/api/cw/manage").get_json()
        self.assertTrue(man["kids"])
        self.assertTrue(next(u for u in man["users"] if u["nick"] == "CwKid1")["minor"])
        self.assertEqual(a2.req("PUT", "/api/cw/access", {"id": a1.id, "off": True}).status_code, 403)
        self.coach.req("PUT", "/api/cw/access", {"id": k2.id, "off": True})
        self.assertEqual(self.nicks(k2)[0]["reason"], "off")
        self.coach.req("PUT", "/api/cw/access", {"id": k2.id, "off": False})
        # knock knock → connection → channel
        self.nicks(a2)
        self.assertEqual(a1.req("POST", "/api/cw/knock", {"to": k1.id}).get_json()["code"], "notFound")
        self.assertEqual(a1.req("POST", "/api/cw/knock", {"to": a2.id}).status_code, 200)
        st, _ = self.nicks(a2)
        self.assertTrue(next(u for u in st["users"] if u["nick"] == "CwDosp1")["knockIn"])
        self.assertEqual(a2.req("POST", "/api/cw/answer", {"from": a1.id, "accept": True}).status_code, 200)
        r = a1.req("POST", "/api/cw/tx", {"start": True, "els": [[0, 60], [120, 300]]})
        self.assertEqual(r.status_code, 200, r.get_json())
        oid = r.get_json()["over"]
        self.assertEqual(a2.req("POST", "/api/cw/tx", {"start": True, "els": []}).get_json()["code"], "channelBusy")
        self.assertEqual(a1.req("POST", "/api/cw/tx", {"over": oid, "els": [[5, 1]]}).status_code, 400)
        st = a2.req("GET", "/api/cw/state").get_json()
        self.assertEqual(st["channel"], "rx")
        self.assertEqual(st["rx"][0]["els"], [[0, 60], [120, 300]])
        a1.req("POST", "/api/cw/tx", {"over": oid, "end": True})
        st = a2.req("GET", f"/api/cw/state?over={oid}&n=2&done={oid}").get_json()
        self.assertEqual(st["channel"], "free")
        # block: the blocked user disappears and the connection ends
        self.assertEqual(a2.req("POST", "/api/cw/block", {"id": a1.id}).status_code, 200)
        ex = a2.req("GET", "/api/export").get_json()["cw"]  # 0.13.10: the export carries blocks and the trainer
        self.assertEqual([b["nick"] for b in ex["blocked"]], ["CwDosp1"])
        self.assertEqual(ex["coach"], "CwTrener")
        st, seen = self.nicks(a2)
        self.assertNotIn("CwDosp1", seen)
        self.assertEqual(st["blocked"], [{"id": a1.id, "nick": "CwDosp1"}])
        self.assertIsNone(st["link"])
        a2.req("POST", "/api/cw/block", {"id": a1.id, "on": False})
        self.assertIn("CwDosp1", self.nicks(a2)[1])

    def test_requires_login_and_csrf(self):
        c = Client()
        self.assertEqual(c.req("GET", "/api/cw/state").status_code, 403)
        a = self.student("CwCsrf")
        a.csrf = "wrong"
        self.assertEqual(a.req("POST", "/api/cw/leave").status_code, 403)


if __name__ == "__main__":
    unittest.main()
