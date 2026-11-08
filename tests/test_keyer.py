# SPDX-License-Identifier: EUPL-1.2
"""VK keyer (tests/keyer.py = port of web/js/keyer.js): iambic A/B, memory, single lever, bug, straight key."""
import re
import unittest
from pathlib import Path

from tests import keyer as K

ROOT = Path(__file__).resolve().parent.parent
CHARSET = (ROOT / 'web/js/charset.js').read_text(encoding='utf-8')
MORSE = dict(re.findall(r"""\[['"](.)['"], '([.-]+)'\]""", CHARSET))


def run(kind, events, wpm=20, until=5000):
    """Drives the keyer like keyerui.js: events (time ms, side, down); a decision at the end of each trailing gap.
    Returns the elements sent as a string."""
    k = K.Keyer(kind, wpm)
    u = k.unit
    out, decision = [], None
    events = sorted(events)
    i = 0

    def start(el, t):
        nonlocal decision
        out.append(el)
        decision = t + k.element_ms(el) + u

    while True:
        t_ev = events[i][0] if i < len(events) else None
        if decision is not None and (t_ev is None or decision <= t_ev):
            t = decision
            decision = None
            el = k.next()
            if el:
                start(el, t)
            continue
        if t_ev is None or t_ev > until:
            break
        t, side, down = events[i]
        i += 1
        if down:
            if k.press(side):
                el = k.next()
                if el:
                    start(el, t)
        else:
            k.release(side)
    return ''.join(out)


class KeyerTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(K.KEY_TYPES, ['iambicB', 'iambicA', 'single', 'bug', 'straight'])
        self.assertEqual((K.CONSTS['KEYER_WPM_MIN'], K.CONSTS['KEYER_WPM_MAX']), (5, 40))
        self.assertEqual(K.unit_ms(20), 60)
        k = K.Keyer('iambicA', 20, ratio=9)
        self.assertEqual(k.element_ms(K.DASH), 60 * 3.5)   # ratio clamped
        self.assertEqual(K.Keyer('nonsense').type, 'iambicB')
        self.assertEqual(K.Keyer(wpm=100).wpm, 40)

    def test_single_paddle_repeats(self):
        for kind in ('iambicA', 'iambicB', 'single'):
            self.assertEqual(run(kind, [(0, 'dot', True), (170, 'dot', False)]), '..', kind)       # 0, 120
            self.assertEqual(run(kind, [(0, 'dash', True), (250, 'dash', False)]), '--', kind)     # 0, 240

    def test_squeeze_alternates(self):
        ev = [(0, 'dot', True), (10, 'dash', True), (700, 'dot', False), (700, 'dash', False)]
        self.assertEqual(run('iambicA', ev), '.-.-')   # 0 . 120 - 360 . 480 - (720: released)
        self.assertEqual(run('iambicB', ev), '.-.-.')  # B: squeezed during the last dash → one more dot
        ev = [(0, 'dash', True), (10, 'dot', True), (200, 'dash', False), (200, 'dot', False)]
        self.assertEqual(run('iambicA', ev), '-.')    # the dot came while the dash ran → dot memory, also in A

    def test_mode_a_vs_b(self):
        # squeeze held into the dash and released during it: A stops, B adds the opposite element
        ev = [(0, 'dot', True), (10, 'dash', True), (200, 'dot', False), (200, 'dash', False)]
        self.assertEqual(run('iambicA', ev), '.-')
        self.assertEqual(run('iambicB', ev), '.-.')
        # released already in the gap after the first dot: both modes '.-' (the dash comes from memory)
        ev = [(0, 'dot', True), (10, 'dash', True), (100, 'dot', False), (100, 'dash', False)]
        self.assertEqual(run('iambicA', ev), '.-')
        self.assertEqual(run('iambicB', ev), '.-')

    def test_memory(self):
        # K by squeezing with a tap: dash held, dot tapped during the dash → dash dot, dash still held → dash
        ev = [(0, 'dash', True), (50, 'dot', True), (80, 'dot', False), (400, 'dash', False)]
        self.assertEqual(run('iambicA', ev), '-.-')
        # memory survives the release of the paddle (tap shorter than the element)
        ev = [(0, 'dash', True), (50, 'dot', True), (80, 'dot', False), (100, 'dash', False)]
        self.assertEqual(run('iambicA', ev), '-.')

    def test_single_lever_last_wins(self):
        ev = [(0, 'dash', True), (100, 'dot', True), (500, 'dot', False), (500, 'dash', False)]
        self.assertEqual(run('single', ev), '-...')   # never alternates: the latest pressed side (dot) wins
        ev = [(0, 'dash', True), (100, 'dot', True), (130, 'dot', False), (400, 'dash', False)]
        self.assertEqual(run('single', ev), '-.-')     # the tap (memory) first, then the held dash again

    def test_bug_and_straight(self):
        k = K.Keyer('bug', 20)
        self.assertFalse(k.press('dash'))           # dash by hand – the driver keys the tone
        self.assertIsNone(k.next())
        self.assertEqual(run('bug', [(0, 'dot', True), (290, 'dot', False)]), '...')
        self.assertEqual(run('bug', [(0, 'dot', True), (50, 'dash', True), (290, 'dot', False), (300, 'dash', False)]), '...')
        k = K.Keyer('straight')
        self.assertFalse(k.press('dot'))
        self.assertIsNone(k.next())
        self.assertEqual(K.manual_side('straight'), 'dot')
        self.assertEqual(K.manual_side('bug'), 'dash')
        self.assertIsNone(K.manual_side('iambicB'))

    def test_release_all(self):
        k = K.Keyer('iambicB')
        k.press('dot')
        k.next()
        k.press('dash')
        k.release_all()
        self.assertIsNone(k.next())
        self.assertFalse(k.busy)

    def test_charset(self):
        self.assertEqual(MORSE['K'], '-.-')
        self.assertEqual(len(MORSE), 51)

    def test_js_port_in_sync(self):
        js = K.KEYER_JS
        for frag in ("el = opposite(this.last); // B", "if (this.busy && this.type !== 'bug' && this.type !== 'straight') this.mem[side] = true;",
                     "this.squeeze = this.down.dot && this.down.dash;", "if (this.mem.dot !== this.mem.dash) el = this.mem.dot ? DOT : DASH;"):
            self.assertIn(frag, js)


if __name__ == '__main__':
    unittest.main()
