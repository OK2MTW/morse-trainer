# SPDX-License-Identifier: EUPL-1.2
"""1.1 K3 part 1: the spacing of an over from P(word gap) and the lexicon (tests/vo.py segment)."""
import unittest

from tests import vo as V


def units(text, p_word=0.99, p_char=0.01, unsure=()):
    """An over as units: a space = a word gap with p_word, otherwise p_char; index in unsure → P = 0.5."""
    out, gap = [], None
    for ch in text:
        if ch == ' ':
            gap = p_word
            continue
        pw = None if not out else (gap if gap is not None else p_char)
        if out and len(out) in unsure:
            pw = 0.5
        out.append((ch, pw))
        gap = None
    return out


class SegmentTest(unittest.TestCase):
    def test_clear_gaps_are_kept(self):
        self.assertEqual(V.segment(units('CQ CQ DE OK2MTW K'), calls=('OK2MTW',)), 'CQ CQ DE OK2MTW K')
        # an unknown word with clear gaps is not split into known words, nor joined with its neighbour
        self.assertEqual(V.segment(units('NAME MARTIN MARTIN')), 'NAME MARTIN MARTIN')

    def test_unsure_gap_follows_the_lexicon(self):
        # Q|R|S unsure inside "QRS" → joined; an unsure gap between "QRS" and "K" → split
        self.assertEqual(V.segment(units('QR S PSE', unsure=(2,))), 'QRS PSE')
        self.assertEqual(V.segment(units('QRSK', unsure=(3,))), 'QRS K')
        self.assertEqual(V.segment(units('OK2 MTW DE', unsure=(3,)), calls=('OK2MTW',)), 'OK2MTW DE')

    def test_off_is_the_gap_model_only(self):
        u = units('QR S', p_word=0.6)
        self.assertEqual(V.segment(u, tol='off'), 'QR S')
        self.assertEqual(V.segment(u, tol='mid'), 'QRS')

    def test_characters_are_never_changed(self):
        for text in ('OK1AB* DE OK2MTW', 'TNX FER CALL', 'HW? K', 'RST 599 5NN'):
            out = V.segment(units(text, p_word=0.6, p_char=0.4), calls=('OK2MTW',))
            self.assertEqual(out.replace(' ', ''), text.replace(' ', ''))

    def test_prosigns_are_words(self):
        u = units('TU') + [('SK', 0.3)]
        self.assertEqual(V.segment(u), 'TU SK')

    def test_word_costs(self):
        self.assertLess(V.word_cost('QRS'), V.word_cost('599'))
        self.assertLess(V.word_cost('599'), V.word_cost('XYZQ'))
        self.assertLess(V.word_cost('OK2MTW', ('OK2MTW',)), V.word_cost('OK2MTX'))
        # two unknown words are not dearer than the same characters as one long word
        self.assertLess(2 * V.word_cost('MARTIN'), V.word_cost('MARTINMARTIN'))


class SegmentJsTest(unittest.TestCase):
    """1.1 K3 part 2: segment lives in web/js/vo.js (no JS engine on the Pi – the port is checked by its shape and the
    constants, which tests/vo.py reads from vo.js) and the VO reads a finished over with it."""

    def setUp(self):
        from pathlib import Path
        self.voui = (Path(__file__).resolve().parent.parent / 'web/js/voui.js').read_text(encoding='utf-8')

    def test_constants_from_js(self):
        for name in ('WORD', 'PATTERN', 'UNKNOWN', 'CHAR', 'PMIN', 'LONG', 'LONG_CHAR', 'MAXLEN'):
            self.assertIn(f'VO_LEX_{name}', V.CONSTS)
        self.assertEqual(V.VO_LEX_WEIGHT, {'high': 1.5, 'mid': 1.0, 'off': 0.0})
        self.assertEqual(set(V.VO_LEX_WEIGHT), set(V.VO_TOL_JOIN))     # every tolerance has a weight

    def test_js_shape(self):
        for s in ('export function wordCost(w, calls = [])', "export function segment(units, tol = 'mid', calls = [])",
                  'export function overUnits(dec)', "import { VOCAB } from './vocab.js';", 'VO_LEX_WEIGHT[tol] ?? 1',
                  'segment(units, this.tol, calls)', 'reply(text, units = null)'):
            self.assertIn(s, V.VO_JS)

    def test_vo_reads_with_segment(self):
        self.assertIn('V.vo.read(overText(own.chars), overUnits(own))', self.voui)
        self.assertIn('V.vo.reply(text, overUnits(dec))', self.voui)
        # the live line and the manual key keep mendSpacing / the plain text
        self.assertIn('${overText(decodeOwn().chars)}…', self.voui)

    def test_vo_python_reads_units(self):
        vo = V.VirtualOperator(rng=__import__('random').Random(1).random, tol='mid')
        u = units('QR S PSE', unsure=(2,))
        self.assertEqual(vo.read('QR S PSE', u), 'QRS PSE')
        self.assertEqual(vo.read('QR S PSE'), 'QRS PSE')               # without units: mendSpacing


if __name__ == '__main__':
    unittest.main()


class UnsureMarksTest(unittest.TestCase):
    """1.1 K4: the unsure gaps of a read over are shown (vo.js unsureMarks, port tests/vo.py unsure_marks)."""

    def test_marks(self):
        u = units('QR S PSE', unsure=(2,))
        read = V.segment(u)
        self.assertEqual(V.unsure_marks(u, read), [('QR', False), ('', True), ('S PSE', False)])
        u = units('QRSK', unsure=(3,))
        self.assertEqual(V.unsure_marks(u, V.segment(u)), [('QRS', False), (' ', True), ('K', False)])

    def test_no_marks(self):
        u = units('CQ DE OK2MTW')
        self.assertIsNone(V.unsure_marks(u, V.segment(u)))
        self.assertIsNone(V.unsure_marks(units('QR S', unsure=(2,)), 'QRX'))      # the read does not match
        self.assertIsNone(V.unsure_marks(None, 'QRS'))
        # a fixed boundary (1) and clear gaps are never unsure
        self.assertIsNone(V.unsure_marks([('T', None), ('U', 0.1), ('SK', 1)], 'TU SK'))
        self.assertIsNone(V.unsure_marks([('T', None), ('U', 0.1), ('SK', 0.5)], 'TU SK'))   # a prosign

    def test_vo_reply_carries_marks(self):
        vo = V.VirtualOperator(rng=__import__('random').Random(1).random, tol='mid')
        h = vo.reply('QR S PSE', units('QR S PSE', unsure=(2,)))['heard']
        self.assertEqual(h['read'], 'QRS PSE')
        self.assertTrue(h['marks'])

    def test_js_shape(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        voui = (root / 'web/js/voui.js').read_text(encoding='utf-8')
        self.assertIn('export function unsureMarks(units, read)', V.VO_JS)
        self.assertIn('h.marks = units && units.length ? unsureMarks(units, read) : null;', V.VO_JS)
        self.assertEqual(V.VO_UNSURE, 0.25)
        keyer = (root / 'web/js/keyerui.js').read_text(encoding='utf-8')
        for s in ("t('vo.unsureLegend')", 'showRead(el,', 'h.marks);'):
            self.assertIn(s, voui)
        for s in ("s.className = 'vo-unsure';", 'for (const [txt, unsure] of marks)'):   # 1.1.3: shared showRead
            self.assertIn(s, keyer)
        self.assertIn('.vo-unsure {', (root / 'web/css/app.css').read_text(encoding='utf-8'))
