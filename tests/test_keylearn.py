# SPDX-License-Identifier: EUPL-1.2
"""0.13.11 learning the key mapping with confirmation (tests/keylearn.py = port of web/js/keylearn.js):
one gesture per step (HW mode C: Ctrl + F13 together, mode B: a series of F13), confirmation, same key refused."""
import unittest

from tests import keylearn as L


def feed(kl, events):
    """events = (ms, code, down[, repeat]); the clock ticks with every event."""
    for ev in events:
        ts, code, down = ev[:3]
        kl.tick(ts)
        kl.key(code, down, ts, ev[3] if len(ev) > 3 else False)


def mode_c(t0, ctrl, first_ctrl=True, els=1):
    """One paddle press of the HW key in mode C: Ctrl and F13 in the same ms (any order), els elements of 60 ms."""
    ev = [(t0, ctrl, True), (t0, 'F13', True)] if first_ctrl else [(t0, 'F13', True), (t0, ctrl, True)]
    ev.append((t0 + 60, 'F13', False))
    for i in range(1, els):
        ev += [(t0 + 120 * i, 'F13', True), (t0 + 120 * i + 60, 'F13', False)]
    ev.append((t0 + 120 * els - 50, ctrl, False))
    return ev


def mode_b(t0, n):
    """A held paddle in mode B: n dots of F13 (60 ms, gap 60 ms)."""
    ev = []
    for i in range(n):
        ev += [(t0 + 120 * i, 'F13', True), (t0 + 120 * i + 60, 'F13', False)]
    return ev


class TestKeyLearn(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(L.QUIET_MS, 600)
        self.assertEqual(L.SKIP, ['Escape', 'Enter', 'NumpadEnter', 'Tab'])

    def test_waits_for_confirmation(self):
        kl = L.KeyLearn(['dot', 'dash'])
        feed(kl, [(0, 'KeyZ', True), (100, 'KeyZ', False)])
        self.assertEqual(kl.phase, 'gesture')
        self.assertFalse(kl.tick(699))
        self.assertTrue(kl.tick(700))
        self.assertEqual((kl.phase, kl.code, kl.error), ('confirm', 'KeyZ', None))
        feed(kl, [(800, 'KeyX', True), (900, 'KeyX', False)])   # ignored before the confirmation
        self.assertEqual((kl.step, kl.code), ('dot', 'KeyZ'))
        self.assertTrue(kl.confirm())
        self.assertEqual((kl.step, kl.phase), ('dash', 'wait'))
        feed(kl, [(1000, 'KeyX', True), (1050, 'KeyX', False)])
        kl.tick(2000)
        kl.key('Enter', True, 2001)
        self.assertEqual(kl.phase, 'done')
        self.assertEqual(kl.result, {'dot': 'KeyZ', 'dash': 'KeyX'})

    def test_mode_c_paddle_is_ctrl_in_any_order(self):
        for first_ctrl in (True, False):
            kl = L.KeyLearn(['dot', 'dash'])
            feed(kl, mode_c(0, 'ControlLeft', first_ctrl, els=3))
            kl.tick(5000)
            kl.confirm()
            feed(kl, mode_c(6000, 'ControlRight', not first_ctrl, els=2))
            kl.tick(9000)
            kl.confirm()
            self.assertEqual(kl.result, {'dot': 'ControlLeft', 'dash': 'ControlRight'})

    def test_mode_c_stream_is_not_ctrl(self):
        for first_ctrl in (True, False):
            kl = L.KeyLearn(['stream'])
            feed(kl, mode_c(0, 'ControlLeft', first_ctrl, els=2))
            kl.tick(5000)
            self.assertEqual(kl.code, 'F13')

    def test_mode_b_series_is_one_gesture(self):
        kl = L.KeyLearn(['dot', 'dash'])
        feed(kl, mode_b(0, 10))   # held paddle: the gaps of 60 ms do not end the gesture
        self.assertEqual(kl.phase, 'gesture')
        kl.tick(1140 + 600)
        self.assertEqual((kl.phase, kl.code), ('confirm', 'F13'))
        kl.confirm()
        feed(kl, mode_b(3000, 3))
        kl.tick(9000)
        # mode B sends the same key for both paddles → refused with an explanation, confirm does nothing
        self.assertEqual((kl.phase, kl.error), ('confirm', 'same'))
        self.assertFalse(kl.confirm())
        kl.key('Enter', True, 9001)   # Enter = try again
        self.assertEqual((kl.phase, kl.step, kl.error), ('wait', 'dash', None))
        self.assertEqual(kl.result, {'dot': 'F13'})

    def test_autorepeat_marked_and_unmarked(self):
        kl = L.KeyLearn(['dot'])
        feed(kl, [(0, 'ControlLeft', True), (500, 'ControlLeft', True, True), (530, 'ControlLeft', True),
                  (560, 'ControlRight', True, True), (900, 'ControlLeft', False)])
        kl.tick(1600)
        self.assertEqual(kl.code, 'ControlLeft')
        self.assertEqual(len(kl.gesture), 1)

    def test_escape_cancels_anytime(self):
        for at in ('wait', 'gesture', 'confirm'):
            kl = L.KeyLearn(['dot', 'dash'])
            if at != 'wait':
                feed(kl, [(0, 'KeyZ', True), (50, 'KeyZ', False)])
            if at == 'confirm':
                kl.tick(1000)
            kl.key('Escape', True, 2000)
            self.assertEqual(kl.phase, 'cancel')
            self.assertFalse(kl.active)
            self.assertFalse(kl.key('KeyZ', True, 2100))

    def test_control_keys_not_learned(self):
        kl = L.KeyLearn(['dot'])
        feed(kl, [(0, 'Enter', True), (10, 'Enter', False), (20, 'Tab', True)])
        self.assertEqual(kl.phase, 'wait')

    def test_held_key_from_before_and_blur(self):
        kl = L.KeyLearn(['dot'])
        feed(kl, [(0, 'KeyQ', False)])     # released a key pressed before learning
        self.assertEqual(kl.phase, 'wait')
        feed(kl, [(10, 'KeyZ', True)])
        self.assertIsNone(kl.due_at())     # held → the gesture does not end
        kl.release_all(100)                # focus lost, no keyup comes
        self.assertEqual(kl.due_at(), 700)
        kl.tick(700)
        self.assertEqual((kl.phase, kl.code), ('confirm', 'KeyZ'))

    def test_new_press_during_silence_extends_gesture(self):
        kl = L.KeyLearn(['dot'])
        feed(kl, [(0, 'KeyZ', True), (50, 'KeyZ', False), (500, 'KeyX', True), (550, 'KeyX', False)])
        self.assertFalse(kl.tick(1000))
        self.assertTrue(kl.tick(1150))
        self.assertEqual(kl.code, 'KeyZ')   # the first key of the gesture

    def test_retry_same_step(self):
        kl = L.KeyLearn(['dot', 'dash'])
        feed(kl, [(0, 'KeyZ', True), (50, 'KeyZ', False)])
        kl.tick(1000)
        kl.retry()
        self.assertEqual((kl.phase, kl.step), ('wait', 'dot'))
        feed(kl, [(1100, 'KeyA', True), (1150, 'KeyA', False)])
        kl.tick(2000)
        self.assertEqual(kl.code, 'KeyA')


if __name__ == '__main__':
    unittest.main()
