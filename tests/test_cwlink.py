# SPDX-License-Identifier: EUPL-1.2
"""CW room channel timing (tests/cwlink.py = port of web/js/cwlink.js): over end, batches, the receiver reserve,
late batches (rhythm kept, reserve grows and shrinks again), delay estimate; a simulation of the whole chain
sender → batches → server → polling receiver with random network delays."""
import random
import re
import unittest
from pathlib import Path

from tests import cwlink as L

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web/js/cwlink.js").read_text(encoding="utf-8")


def paris(t0, dot=60.0, words=2):
    """Elements of PARIS … keyed by a perfect keyer: [(start, end)] local ms."""
    code = {"P": ".--.", "A": ".-", "R": ".-.", "I": "..", "S": "..."}
    out, t = [], t0
    for _w in range(words):
        for ch in "PARIS":
            for i, el in enumerate(code[ch]):
                d = dot if el == "." else 3 * dot
                out.append((t, t + d))
                t += d + dot
            t += 2 * dot
        t += 4 * dot
    return out


class ConstantsTest(unittest.TestCase):
    def test_port_constants_match_js(self):
        for name in ("BATCH_MS", "BATCH_SLOW_MS", "POLL_MS", "POLL_RX_MS", "POLL_TX_MS", "BUFFER_MS", "BUFFER_STEP_MS",
                     "BUFFER_MAX_MS", "CLEAN_OVERS", "LATE_MARGIN_MS", "END_MIN_MS", "END_DOTS", "OVER_SPLIT_MS",
                     "DELAY_KEEP"):
            m = re.search(rf"export const {name} = (\d+);", JS)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1)), getattr(L, name), name)

    def test_over_end(self):
        self.assertEqual(L.over_end_ms(60), 1000)     # 20 WPM: 7 dots = 420 ms → at least 1 s
        self.assertEqual(L.over_end_ms(240), 1680)    # 5 WPM


class TxOverTest(unittest.TestCase):
    def test_batches_only_started_elements(self):
        o = L.TxOver(1000.0)
        o.add(1000, 1060)
        o.add(1120, 1300)
        o.add(1360, 1420)
        self.assertEqual(o.batch(1200), [[0, 60], [120, 300]])
        self.assertEqual(o.batch(1200), [])
        self.assertEqual(o.rest(), [[360, 420]])
        self.assertEqual(o.rest(), [])

    def test_monotonic_and_end(self):
        o = L.TxOver(0.0)
        self.assertTrue(o.add(0, 60))
        self.assertTrue(o.add(50, 120))              # overlapping start is moved behind the previous end
        self.assertEqual(o.els[-1], [60, 120])
        self.assertFalse(o.add(100, 110))            # nothing left of it
        self.assertFalse(o.silent(900, 60, False))
        self.assertFalse(o.silent(1200, 60, True))   # a held key is not silence
        self.assertTrue(o.silent(1120, 60, False))
        self.assertTrue(o.too_long(L.OVER_SPLIT_MS))


class RxPlayoutTest(unittest.TestCase):
    def test_rhythm_kept_with_reserve(self):
        rx = L.RxPlayout()
        out = rx.receive(1, [[0, 60], [120, 300]], False, 5000)
        b = 5000 + L.BUFFER_MS
        self.assertEqual(out, [[b, b + 60], [b + 120, b + 300]])
        out = rx.receive(1, [[360, 420]], True, 5300)
        self.assertEqual(out, [[b + 360, b + 420]])
        self.assertFalse(rx.played_out(b + 400))
        self.assertTrue(rx.played_out(b + 420))
        self.assertEqual(rx.finish(), 1)
        self.assertEqual(rx.buffer, L.BUFFER_MS)
        self.assertEqual(rx.query(), {"over": 2, "n": 0, "done": 1})

    def test_late_batch_shifts_rest_and_reserve_adapts(self):
        rx = L.RxPlayout()
        rx.receive(1, [[0, 60]], False, 0)                    # plays at BUFFER_MS
        out = rx.receive(1, [[1500, 1560], [1620, 1680]], True, 2200)  # due at 2100 – late
        self.assertEqual(out[0][0], 2200 + L.LATE_MARGIN_MS)
        self.assertEqual(out[1][0] - out[0][0], 120)          # the rhythm inside the batch stays
        rx.finish()
        self.assertEqual(rx.buffer, L.BUFFER_MS + L.BUFFER_STEP_MS)
        for oid in range(2, 2 + L.CLEAN_OVERS):                # clean overs → back to the start
            rx.receive(oid, [[0, 60]], True, oid * 10000)
            rx.finish()
        self.assertEqual(rx.buffer, L.BUFFER_MS)
        for oid in range(10, 20):                              # never above the maximum
            rx.receive(oid, [[0, 60]], False, oid * 10000)
            rx.receive(oid, [[5000, 5060]], True, oid * 10000 + 9000)
            rx.finish()
        self.assertEqual(rx.buffer, L.BUFFER_MAX_MS)

    def test_new_over_closes_previous_and_old_ignored(self):
        rx = L.RxPlayout()
        rx.receive(3, [[0, 60]], False, 0)
        rx.receive(4, [[0, 60]], False, 3000)
        self.assertEqual(rx.last_id, 3)
        self.assertEqual(rx.receive(2, [[0, 60]], True, 4000), [])
        self.assertEqual(rx.query(), {"over": 4, "n": 1, "done": 3})

    def test_delay_estimate(self):
        rx = L.RxPlayout()
        # the over started 300 ms ago at the server, the request took 100 ms: key down ≈ 400 ms ago, sound in BUFFER_MS
        rx.receive(1, [[0, 60]], True, 10000, age=300, rtt=100)
        rx.finish()
        self.assertEqual(rx.avg_delay(), 400 + L.BUFFER_MS)


class ChainSimulationTest(unittest.TestCase):
    """Sender → batches every BATCH_MS → server (uplink 30–150 ms) → receiver polling every 250 ms (downlink 30–150 ms)."""

    def run_chain(self, seed, overs=6, up=(30, 150), down=(30, 150)):
        rng = random.Random(seed)
        rx = L.RxPlayout()
        delays, rhythm_err, late = [], [], 0
        t = 0.0
        for oid in range(1, overs + 1):
            els = paris(t + rng.uniform(0, 200))
            o = L.TxOver(els[0][0])
            for s, e in els:
                o.add(s, e)
            # the sender: first element at once (start), then a batch every BATCH_MS
            arrivals = []   # (server time, batch, end)
            first = o.batch(els[0][0])
            arrivals.append((els[0][0] + rng.uniform(*up), first, False, els[0][0]))
            send = els[0][0] + L.BATCH_MS
            while o.sent < len(o.els):
                b = o.batch(send)
                if b:   # batches go one after another (the client waits for the previous one) – never reordered
                    arrivals.append((max(arrivals[-1][0], send + rng.uniform(*up)), b, False, None))
                send += L.BATCH_MS
            end_at = o.last_end + L.over_end_ms(60)
            arrivals.append((max(arrivals[-1][0], end_at + rng.uniform(*up)), [], True, None))
            server_start = arrivals[0][0]
            # the receiver polls every POLL_RX_MS, gets everything that reached the server before the poll
            poll = server_start - rng.uniform(0, L.POLL_RX_MS)
            got = 0
            played = []
            while got < len(arrivals):
                poll += L.POLL_RX_MS
                d_up, d_down = rng.uniform(*down), rng.uniform(*down)
                at_server = poll + d_up
                new = [a for a in arrivals[got:] if a[0] <= at_server]
                if not new:
                    continue
                got += len(new)
                now = at_server + d_down
                els_new = [x for a in new for x in a[1]]
                ended = any(a[2] for a in new)
                played += rx.receive(oid, els_new, ended, now, age=at_server - server_start, rtt=d_up + d_down)
            if rx.cur and rx.cur["late"]:
                late += 1
            rx.finish()
            # rhythm: the gaps between element starts as keyed (a late shift may lengthen one gap)
            keyed = [s for s, _ in els]
            for i in range(1, len(played)):
                rhythm_err.append(abs((played[i][0] - played[i - 1][0]) - (keyed[i] - keyed[i - 1])))
            delays.append(played[0][0] - els[0][0])
            t = played[-1][1] + 2000
        return delays, rhythm_err, late, rx

    def test_average_delay_within_one_second(self):
        all_delays = []
        for seed in range(20):
            delays, _r, _l, rx = self.run_chain(seed)
            all_delays += delays
            est = rx.avg_delay()
            self.assertLess(abs(est - sum(delays[-L.DELAY_KEEP:]) / len(delays[-L.DELAY_KEEP:])), 200, seed)
        avg = sum(all_delays) / len(all_delays)
        self.assertLess(avg, 1000, avg)

    def test_rhythm_mostly_exact(self):
        exact = total = 0
        for seed in range(20):
            _d, err, _l, _rx = self.run_chain(seed)
            total += len(err)
            exact += sum(1 for e in err if e < 1)
        self.assertGreater(exact / total, 0.98)

    def test_slow_network_grows_reserve(self):
        _d, _e, late, rx = self.run_chain(7, overs=4, up=(100, 700), down=(100, 500))
        self.assertGreater(late, 0)
        self.assertGreater(rx.buffer, L.BUFFER_MS)


if __name__ == "__main__":
    unittest.main()
