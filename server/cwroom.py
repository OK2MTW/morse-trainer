# SPDX-License-Identifier: EUPL-1.2
"""CW room 1:1 (0.13.0, design in docs/requirements.md): who may see whom, presence, "Knock Knock",
connections and the shared half-duplex channel. Everything lives in memory only (a restart ends all connections);
the database holds just the trainer switches (users.cw_off, users.cw_kids) and blocks (cw_blocks).

The channel carries the keying time line (element start/end in ms from the start of an over), never sound. The first
station whose `tx start` reaches the server takes the channel; it stays busy until the over has died away at the
receiver (the receiver reports `done`, fallback END_GRACE_S after the end)."""
import threading
import time

from server import admission

ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT = "admin", "trener", "zak"  # stored values
ADULT_AGES = ("18-59", "60+")  # stored values; a student without an age group counts as a minor (safer)

PRESENT_S = 5          # in the room = polled within this time (the page polls every 0.25–1 s while visible)
KNOCK_S = 60           # a knock expires
BELL_S = 15            # 0.13.6: reachable for a knock = in the room or the app asked for knocks this recently (à 5 s)
LINK_IDLE_S = 120      # a connection ends when one side has not polled for this long
NOTICE_S = 15          # how long "the other side hung up / declined" stays in the state
OVER_IDLE_S = 3        # no batch for this long = the over has ended (the client normally sends `end`)
OVER_MAX_MS = 120_000  # an over is at most 2 min
END_GRACE_S = 3        # the channel is free at the latest this long after the end of an over
BATCH_MAX = 64         # elements in one batch
DIRECTORY_TTL_S = 5    # the user directory (from the DB) is cached this long


def is_minor(u):
    return u["role"] == ROLE_STUDENT and u["age_group"] not in ADULT_AGES


def has_access(u, users):
    """None = may use the room, else the reason code ('disabled', 'off', 'kids')."""
    if u["disabled"]:
        return "disabled"
    if u["cw_off"]:
        return "off"
    if is_minor(u):
        coach = users.get(u["invited_by"])
        if not coach or coach["role"] != ROLE_COACH or coach["disabled"] or not coach["cw_kids"]:
            return "kids"
    return None


def can_see(a, b, users, blocks):
    """Symmetric: may a and b see each other in the room (and connect)? (Martin 2026-11-08)
    - adults (students, admin) see all adults and trainers, never minors;
    - a trainer sees adults, other trainers and the minors they invited;
    - a minor in a group sees the minors of the same group and their own trainer; outside a group only the trainer."""
    if a["id"] == b["id"] or has_access(a, users) or has_access(b, users):
        return False
    if (a["id"], b["id"]) in blocks or (b["id"], a["id"]) in blocks:
        return False
    for x, y in ((a, b), (b, a)):
        if x["role"] == ROLE_COACH:
            return y["role"] == ROLE_COACH or not is_minor(y) or y["invited_by"] == x["id"]
    ma, mb = is_minor(a), is_minor(b)
    if ma and mb:
        return a["group_id"] is not None and a["group_id"] == b["group_id"]
    return not ma and not mb


class Over:
    def __init__(self, oid, sender, at):
        self.id, self.sender = oid, sender
        self.els = []            # [[start_ms, end_ms], …] from the first key down of the over
        self.started = self.last = at
        self.ended_at = None     # monotonic time of the end
        self.done = False        # the receiver has played it to the end

    def end(self, at):
        if self.ended_at is None:
            self.ended_at = at


class Link:
    def __init__(self, a, b, at):
        self.a, self.b, self.since = a, b, at
        self.overs = []          # not yet finished at the receiver, oldest first
        self.next_id = 1

    def peer(self, uid):
        return self.b if uid == self.a else self.a

    def tidy(self, at):
        for o in self.overs:
            if o.ended_at is None and (at - o.last > OVER_IDLE_S):
                o.end(o.last)
        self.overs = [o for o in self.overs
                      if not (o.ended_at is not None and (o.done or at - o.ended_at > END_GRACE_S))]

    def holder(self):
        """Who holds the channel (the sender of the newest unfinished over) or None."""
        return self.overs[-1].sender if self.overs else None

    def current(self, uid):
        """The sender's over that is still open for new elements."""
        o = self.overs[-1] if self.overs else None
        return o if o and o.sender == uid and o.ended_at is None else None


class Room:
    def __init__(self, load_directory, clock=time.monotonic, seen=None):
        """load_directory() → (users {id: dict}, blocks {(blocker, blocked)}); seen(uid) → active in the app."""
        self._load = load_directory
        self._clock = clock
        self._seen = seen or (lambda uid: admission.active.seen(uid))
        self._lock = threading.Lock()
        self._dir = None
        self._dir_at = 0.0
        self.present = {}        # uid → last poll
        self.bell = {}           # uid → last knock check of the app outside the room (0.13.6)
        self.knocks = {}         # (from, to) → time
        self.links = {}          # uid → Link (both ends)
        self.notices = {}        # uid → (kind, nick, time)

    # ---------- directory ----------
    def invalidate(self):
        with self._lock:
            self._dir = None

    def _directory(self, at):
        if self._dir is None or at - self._dir_at > DIRECTORY_TTL_S:
            self._dir = self._load()
            self._dir_at = at
        return self._dir

    def clear(self):
        with self._lock:
            self._dir = None
            self.present.clear(), self.knocks.clear(), self.links.clear(), self.notices.clear()

    # ---------- housekeeping ----------
    def _tidy(self, at):
        users, blocks = self._directory(at)
        for uid, link in list(self.links.items()):
            if uid != link.a:
                continue
            gone = [u for u in (link.a, link.b) if at - self.present.get(u, -1e9) > LINK_IDLE_S
                    or u not in users or not can_see(users[link.a], users[link.b], users, blocks)]
            if gone:
                self._unlink(link, gone[0], "idle", at)
            else:
                link.tidy(at)
        for k, t0 in list(self.knocks.items()):
            f, to = k
            if (at - t0 > KNOCK_S or not self._in_room(f, at) or f in self.links or to in self.links
                    or f not in users or to not in users or not can_see(users[f], users[to], users, blocks)):
                del self.knocks[k]
        for uid, (_k, _n, t0) in list(self.notices.items()):
            if at - t0 > NOTICE_S:
                del self.notices[uid]

    def _in_room(self, uid, at):
        return at - self.present.get(uid, -1e9) <= PRESENT_S

    def _reachable(self, uid, at):
        """0.13.6: a knock can reach the user – in the room, or the app is open elsewhere and asks for knocks."""
        return self._in_room(uid, at) or at - self.bell.get(uid, -1e9) <= BELL_S

    def _nick(self, uid, at):
        u = self._directory(at)[0].get(uid)
        return u["nick"] if u else "?"

    def _unlink(self, link, by, kind, at):
        for u in (link.a, link.b):
            self.links.pop(u, None)
        other = link.peer(by)
        self.notices[other] = (kind, self._nick(by, at), at)

    def _status(self, uid, at):
        if uid in self.links:
            return "linked"
        if self._in_room(uid, at):
            return "room"
        return "app" if self._seen(uid) else "off"

    # ---------- state (poll) ----------
    def state(self, uid, over=0, n=0, done=0, touch=True):
        at = self._clock()
        with self._lock:
            users, blocks = self._directory(at)
            me = users.get(uid)
            if me is None:
                return {"access": False, "reason": "disabled"}
            reason = has_access(me, users)
            if reason:
                self.present.pop(uid, None)
                link = self.links.get(uid)
                if link:
                    self._unlink(link, uid, "hangup", at)
                self.knocks = {k: v for k, v in self.knocks.items() if uid not in k}
                return {"access": False, "reason": reason}
            if touch:
                self.present[uid] = at
            link = self.links.get(uid)
            if link and done:
                for o in link.overs:
                    if o.id == done and o.sender != uid:
                        o.done = True
            self._tidy(at)
            link = self.links.get(uid)
            out = {"access": True, "users": [], "link": None, "channel": "free", "rx": [], "over": 0}
            for v in sorted(users.values(), key=lambda v: v["nick"].lower()):
                if not can_see(me, v, users, blocks):
                    continue
                out["users"].append({
                    "id": v["id"], "nick": v["nick"], "coach": v["role"] == ROLE_COACH,
                    "status": self._status(v["id"], at), "reach": self._reachable(v["id"], at),
                    "knockIn": (v["id"], uid) in self.knocks, "knockOut": (uid, v["id"]) in self.knocks})
            out["blocked"] = sorted(({"id": b, "nick": users[b]["nick"]} for (a, b) in blocks
                                     if a == uid and b in users), key=lambda x: x["nick"].lower())
            notice = self.notices.pop(uid, None)
            if notice:
                out["notice"] = {"kind": notice[0], "nick": notice[1]}
            if link:
                peer = link.peer(uid)
                out["link"] = {"id": peer, "nick": users[peer]["nick"], "s": int(at - link.since)}
                holder = link.holder()
                out["channel"] = "free" if holder is None else ("tx" if holder == uid else "rx")
                mine = link.current(uid)
                out["over"] = mine.id if mine else 0
                for o in link.overs:
                    if o.sender == uid or o.id < over:
                        continue
                    start = n if o.id == over else 0
                    out["rx"].append({"id": o.id, "from": start, "els": o.els[start:],
                                      "end": o.ended_at is not None,
                                      "t": round((at - o.started) * 1000)})  # age at the server → delay estimate
            return out

    def knocks_for(self, uid):
        """0.13.6: the app outside the room tab asks who is knocking (marks the user reachable, not present)."""
        at = self._clock()
        with self._lock:
            users, _blocks = self._directory(at)
            me = users.get(uid)
            if me is None or has_access(me, users):
                self.bell.pop(uid, None)
                return {"access": False}
            self.bell[uid] = at
            self._tidy(at)
            return {"access": True, "knocks": sorted(({"id": f, "nick": users[f]["nick"]} for (f, to) in self.knocks
                                                      if to == uid), key=lambda x: x["nick"].lower())}

    def leave(self, uid):
        at = self._clock()
        with self._lock:
            self.present.pop(uid, None)
            self.knocks = {k: v for k, v in self.knocks.items() if uid not in k}
            link = self.links.get(uid)
            if link:
                self._unlink(link, uid, "hangup", at)

    # ---------- knock knock ----------
    def _check_pair(self, uid, other, at):
        users, blocks = self._directory(at)
        if uid not in users or other not in users:
            return "notFound"
        if has_access(users[uid], users):
            return "noAccess"
        if not can_see(users[uid], users[other], users, blocks):
            return "notFound"
        return None

    def knock(self, uid, to):
        at = self._clock()
        with self._lock:
            self._tidy(at)
            problem = self._check_pair(uid, to, at)
            if problem:
                return problem
            if uid in self.links:
                return "linkedSelf"
            if to in self.links:
                return "busy"
            if not self._reachable(to, at):
                return "notInRoom"
            self.present[uid] = at
            self.knocks = {k: v for k, v in self.knocks.items() if k[0] != uid}  # one knock at a time
            self.knocks[(uid, to)] = at
            return None

    def cancel_knock(self, uid):
        with self._lock:
            self.knocks = {k: v for k, v in self.knocks.items() if k[0] != uid}

    def answer(self, uid, frm, accept):
        at = self._clock()
        with self._lock:
            self._tidy(at)
            if self.knocks.pop((frm, uid), None) is None:
                return "noKnock"
            if not accept:
                self.notices[frm] = ("declined", self._nick(uid, at), at)
                return None
            problem = self._check_pair(uid, frm, at)
            if problem:
                return problem
            if uid in self.links or frm in self.links:
                return "busy"
            link = Link(frm, uid, at)
            self.links[frm] = self.links[uid] = link
            self.present[uid] = at
            self.knocks = {k: v for k, v in self.knocks.items() if not ({uid, frm} & set(k))}
            return None

    def hangup(self, uid):
        at = self._clock()
        with self._lock:
            link = self.links.get(uid)
            if not link:
                return "notLinked"
            self._unlink(link, uid, "hangup", at)
            return None

    # ---------- channel ----------
    def tx(self, uid, over=0, start=False, els=(), end=False, done=0):
        """→ (problem or None, {over, ended}). start = the first key down of a new over (takes the channel).
        done = the other station's over I have just played to the end (frees the channel before my start)."""
        at = self._clock()
        with self._lock:
            link = self.links.get(uid)
            if not link:
                return "notLinked", {}
            self.present[uid] = at
            if done:
                for o in link.overs:
                    if o.id == done and o.sender != uid:
                        o.done = True
            link.tidy(at)
            if start:
                holder = link.holder()
                if holder is not None and holder != uid:
                    return "channelBusy", {}
                cur = link.current(uid)
                if cur:
                    cur.end(at)
                o = Over(link.next_id, uid, at)
                link.next_id += 1
                link.overs.append(o)
            else:
                o = link.current(uid)
                if o is None or o.id != over:
                    return None, {"over": over, "ended": True}  # ended meanwhile (idle / 2 min) – drop
            last = o.els[-1][1] if o.els else 0
            for s, e in els:
                if s < last or e < s or e > OVER_MAX_MS:
                    continue
                o.els.append([s, e])
                last = e
            o.last = at
            if end or last >= OVER_MAX_MS or (at - o.started) * 1000 > OVER_MAX_MS + 5000:
                o.end(at)
            return None, {"over": o.id, "ended": o.ended_at is not None}


def clean_elements(raw):
    """A batch from the client → [[start, end], …] in ms (ints); invalid input → None."""
    if not isinstance(raw, list) or len(raw) > BATCH_MAX:
        return None
    out = []
    for p in raw:
        if (not isinstance(p, list) or len(p) != 2
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in p)):
            return None
        s, e = int(round(p[0])), int(round(p[1]))
        if s < 0 or e < s or e > OVER_MAX_MS:
            return None
        out.append([s, e])
    return out
