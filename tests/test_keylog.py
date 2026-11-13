# SPDX-License-Identifier: EUPL-1.2
"""0.14.3 summary of the key event log (tests/keylog.py = port of web/js/keylog.js): 100 elements of a HW stream,
dots / dashes, WPM, lost and doubled events, mode C paddles."""
import random
import unittest

from tests import keylog as L


def stream_events(n, wpm, rng, code='F13', jitter=1.0):
    """n elements alternating dot / dash of a HW stream with ±jitter ms."""
    u = 1200 / wpm
    t, out = 0.0, []
    for i in range(n):
        on = u * (3 if i % 2 else 1)
        out.append({'at': t + rng.uniform(-jitter, jitter), 'code': code, 'down': True})
        out.append({'at': t + on + rng.uniform(-jitter, jitter), 'code': code, 'down': False})
        t += on + 3 * u
    return out


class TestKeyLog(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((L.CONSTS['KEYLOG_MAX'], L.SPLIT), (2000, 1.8))

    def test_hundred_elements(self):
        for wpm in (20, 40, 60):
            s = L.log_summary(stream_events(100, wpm, random.Random(wpm)))
            self.assertEqual((s['events'], s['dup'], s['orphan'], s['open']), (200, 0, 0, 0))
            k = s['keys'][0]
            self.assertEqual((k['code'], k['n'], k['dot']['n'], k['dash']['n']), ('F13', 100, 50, 50))
            self.assertAlmostEqual(k['dot']['med'], 1200 / wpm, delta=1)
            self.assertAlmostEqual(k['dash']['med'], 3600 / wpm, delta=1)
            self.assertLessEqual(k['dot']['max'] - k['dot']['min'], 4)
            self.assertAlmostEqual(k['wpm'], wpm, delta=0.06 * wpm)

    def test_lost_and_doubled(self):
        ev = [{'at': 0, 'code': 'F13', 'down': True}, {'at': 60, 'code': 'F13', 'down': True},   # lost keyup
              {'at': 120, 'code': 'F13', 'down': False}, {'at': 130, 'code': 'F13', 'down': False},  # extra keyup
              {'at': 200, 'code': 'F13', 'down': True}]                                             # held at the end
        s = L.log_summary(ev)
        self.assertEqual((s['dup'], s['orphan'], s['open'], s['keys'][0]['n']), (1, 1, 1, 1))
        self.assertIsNone(s['keys'][0]['dot'])   # one press: no two groups
        self.assertEqual(s['ms'], 200)

    def test_mode_c_keys_separately(self):
        ev = stream_events(4, 20, random.Random(1))
        ev += [{'at': 1, 'code': 'ControlLeft', 'down': True}, {'at': 500, 'code': 'ControlLeft', 'down': False}]
        ev.sort(key=lambda e: e['at'])
        s = L.log_summary(ev)
        self.assertEqual({k['code']: k['n'] for k in s['keys']}, {'F13': 4, 'ControlLeft': 1})

    def test_empty(self):
        self.assertEqual(L.log_summary([]), {'events': 0, 'ms': 0, 'keys': [], 'dup': 0, 'orphan': 0, 'open': 0})


if __name__ == '__main__':
    unittest.main()
