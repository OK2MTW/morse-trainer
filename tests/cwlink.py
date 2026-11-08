# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/cwlink.js (0.13.2, CW room channel timing) – keep in sync."""
import math

BATCH_MS = 250
BATCH_SLOW_MS = 500
POLL_MS = 1000
POLL_RX_MS = 250
POLL_TX_MS = 2000
BUFFER_MS = 500
BUFFER_STEP_MS = 200
BUFFER_MAX_MS = 1400
CLEAN_OVERS = 3
LATE_MARGIN_MS = 30
END_MIN_MS = 1000
END_DOTS = 7
OVER_SPLIT_MS = 110000
DELAY_KEEP = 10


def js_round(x):
    """Math.round (halves up)."""
    return int(math.floor(x + 0.5))


def over_end_ms(dot_ms):
    return max(END_MIN_MS, END_DOTS * dot_ms)


class TxOver:
    def __init__(self, t0):
        self.t0 = t0
        self.els = []
        self.sent = 0
        self.last_end = t0
        self.id = 0

    def add(self, start, end):
        prev = self.els[-1][1] if self.els else 0
        s = max(prev, js_round(start - self.t0))
        e = js_round(end - self.t0)
        if e <= s:
            return False
        self.els.append([s, e])
        self.last_end = max(self.last_end, end)
        return True

    def batch(self, now):
        out = []
        while self.sent < len(self.els) and self.els[self.sent][0] + self.t0 <= now:
            out.append(self.els[self.sent])
            self.sent += 1
        return out

    def rest(self):
        out = self.els[self.sent:]
        self.sent = len(self.els)
        return out

    def silent(self, now, dot_ms, key_down):
        return not key_down and now - self.last_end >= over_end_ms(dot_ms)

    def too_long(self, now):
        return now - self.t0 >= OVER_SPLIT_MS


class RxPlayout:
    def __init__(self):
        self.buffer = BUFFER_MS
        self.clean = 0
        self.cur = None
        self.last_id = 0
        self.delays = []

    def query(self):
        if self.cur:
            return {"over": self.cur["id"], "n": self.cur["n"], "done": self.last_id}
        return {"over": self.last_id + 1, "n": 0, "done": self.last_id}

    def receive(self, oid, els, end, now, age=None, rtt=0):
        if oid <= self.last_id:
            return []
        if self.cur and self.cur["id"] != oid:
            self.finish()
        if not self.cur:
            self.cur = {"id": oid, "base": None, "late": False, "n": 0, "end": False, "lastEnd": now, "delay": None}
        o = self.cur
        out = []
        for s, e in els:
            if o["base"] is None:
                o["base"] = now + self.buffer - s
            at = o["base"] + s
            if at < now + LATE_MARGIN_MS:
                o["base"] += now + LATE_MARGIN_MS - at
                o["late"] = True
                at = o["base"] + s
            out.append([at, o["base"] + e])
            o["lastEnd"] = o["base"] + e
            o["n"] += 1
        if age is not None and o["base"] is not None:
            o["delay"] = js_round(o["base"] - (now - age - rtt))
        if end:
            o["end"] = True
        return out

    def played_out(self, now):
        o = self.cur
        return bool(o) and o["end"] and (o["base"] is None or now >= o["lastEnd"])

    def busy(self, now):
        return bool(self.cur) and not self.played_out(now)

    def finish(self):
        o = self.cur
        if not o:
            return 0
        self.cur = None
        self.last_id = max(self.last_id, o["id"])
        if o["base"] is None:
            return o["id"]
        if o["late"]:
            self.buffer = min(BUFFER_MAX_MS, self.buffer + BUFFER_STEP_MS)
            self.clean = 0
        else:
            self.clean += 1
            if self.clean >= CLEAN_OVERS and self.buffer > BUFFER_MS:
                self.buffer = max(BUFFER_MS, self.buffer - BUFFER_STEP_MS)
                self.clean = 0
        if o["delay"] is not None:
            self.delays.append(o["delay"])
            if len(self.delays) > DELAY_KEEP:
                self.delays.pop(0)
        return o["id"]

    def avg_delay(self):
        if not self.delays:
            return None
        return js_round(sum(self.delays) / len(self.delays))
