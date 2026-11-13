# SPDX-License-Identifier: EUPL-1.2
"""0.14.1 keyboard input of the telegraph key (tests/keyinput.py = port of web/js/keyinput.js): since 0.15.3 only the
HW keyer stream (modes B and C) with the own autorepeat filter; other keys are not the key's."""
import unittest

from tests import keyinput as K

CFG = {'type': 'hw', 'stream': 'F13'}


def acts(ki, events):
    out = []
    for ev in events:
        r = ki.key(*ev)
        out.append(None if r is None else [(a['kind'], a.get('side'), a.get('down')) for a in r])
    return out


class TestKeyInput(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(K.HW_TYPE, 'hw')
        self.assertEqual(K.HW_PADDLES, {'ControlLeft': 'dot', 'ControlRight': 'dash'})
        # the app keyer is gone (0.15.3): no paddle keys of the keyboard, no hint of a HW key under another type
        self.assertNotIn('hwHint', K.KEYINPUT_JS)
        self.assertNotIn("kind: 'side'", K.KEYINPUT_JS)

    def test_hw_mode_b(self):
        ki = K.KeyInput(dict(CFG))
        r = acts(ki, [('F13', True), ('F13', True), ('F13', False), ('F13', False), ('KeyA', True)])
        self.assertEqual(r, [[('stream', None, True)], [], [('stream', None, False)], [], None])

    def test_hw_mode_c_paddles_only_logged(self):
        ki = K.KeyInput(dict(CFG))
        r = acts(ki, [('ControlLeft', True), ('F13', True), ('F13', False), ('ControlLeft', False)])
        self.assertEqual(r, [[('paddle', 'dot', True)], [('stream', None, True)], [('stream', None, False)],
                             [('paddle', 'dot', False)]])

    def test_learned_stream_key(self):
        ki = K.KeyInput(dict(CFG, stream='F24'))
        self.assertEqual(acts(ki, [('F13', True), ('F24', True)]), [None, [('stream', None, True)]])

    def test_release_all(self):
        ki = K.KeyInput(dict(CFG))
        acts(ki, [('F13', True)])
        ki.release_all()
        self.assertEqual(acts(ki, [('F13', False), ('F13', True)]), [[], [('stream', None, True)]])


if __name__ == '__main__':
    unittest.main()
