# SPDX-License-Identifier: EUPL-1.2
"""1.1.3 (Martin 2026-11-15): the Sending page shows how an operator would read the transcript – the gap model of the
hand and the lexicon as the virtual operator, after every pause (no K needed); the strict line and the evaluation stay."""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
KEYER = (WEB / 'js/keyerui.js').read_text(encoding='utf-8')
VOUI = (WEB / 'js/voui.js').read_text(encoding='utf-8')
NEWS = (WEB / 'js/news.js').read_text(encoding='utf-8')


def fn_body(src, name):
    a = src.index(f'function {name}(')
    b = src.index('\n  }\n', a)
    return src[a:b]


class KeyReadTest(unittest.TestCase):
    def test_lines_on_the_page(self):
        a = HTML.index('id="key-text"')
        b = HTML.index('id="key-free"')
        self.assertIn('id="key-read"', HTML[a:b])   # visible in free keying and in lessons, outside the free-keying box
        self.assertIn('id="key-hand"', HTML[b:HTML.index('id="key-hw-box"')])   # 1.1.6: in the collapsed analysis

    def test_texts_cs_en(self):
        for lang in ('cs', 'en'):
            d = json.loads((WEB / f'i18n/{lang}.json').read_text(encoding='utf-8'))
            self.assertIn('{v}', d['key.read'])
            self.assertIn('{c}', d['key.hand'])
            self.assertIn('{w}', d['key.hand'])
            self.assertTrue(d['news.keyRead'])

    def test_read_with_model_and_lexicon_after_a_pause(self):
        body = fn_body(KEYER, 'renderRead')
        self.assertIn('model: true', body)
        self.assertIn('gapPrior: S.gm', body)
        self.assertIn('segment(units', body)
        self.assertIn('unsureMarks(units', body)
        self.assertIn('scheduleRead()', fn_body(KEYER, 'renderOut'))
        self.assertIn('setTimeout(renderRead, KEY_READ_MS)', fn_body(KEYER, 'scheduleRead'))
        self.assertNotRegex(fn_body(KEYER, 'renderRead'), r'overEnded|\bK\b')   # not bound to K
        ms = int(re.search(r'KEY_READ_MS = (\d+)', KEYER).group(1))
        self.assertTrue(300 <= ms <= 1500)

    def test_strict_reading_and_evaluation_unchanged(self):
        dec = fn_body(KEYER, 'decode')
        self.assertNotIn('model', dec)
        self.assertNotIn('segment', fn_body(KEYER, 'renderOut'))

    def test_hand_learned_across_clears(self):
        self.assertIn('S.gm = S.lastGm.learned()', fn_body(KEYER, 'clearOut'))

    def test_shared_rendering_of_unsure_gaps(self):
        self.assertIn('export function showRead(', KEYER)
        self.assertIn('showRead', VOUI)
        self.assertIn("import { loadKeyConfig, HW_WPM, showRead } from './keyerui.js';", VOUI)

    def test_news(self):
        self.assertIn("{ id: 18, version: '1.1.3'", NEWS)
        self.assertIn("'news.keyRead'", NEWS)


if __name__ == '__main__':
    unittest.main()


class KeyTempoTest(unittest.TestCase):
    """1.1.4 (Martin 2026-11-14): the key starts the Sending page at its sending tempo and the CW Chat at the
    receiving tempo (USB MIDI)."""
    MAIN = (WEB / 'js/main.js').read_text(encoding='utf-8')

    def test_helper(self):
        body = KEYER[KEYER.index('export async function keyTempoTo(w)'):KEYER.index('export function initKeyerUi(')]
        for s in ('midiSwitchOn()', 'HwMidi.supported()', 'm.set(KEY_WPM_ID, w)', 'if (cur === w) return w;'):
            self.assertIn(s, body)

    def test_sending_page_on_entering(self):
        self.assertIn('const fresh = !S.open;', KEYER)
        self.assertIn('if (fresh) keyTempoTo(Math.round(getSendWpm()))', KEYER)

    def test_cw_chat_on_entering(self):
        self.assertIn("if (prev !== 'cw') keyTempoTo(Math.round(settings.wpm));", self.MAIN)
        self.assertIn('const prev = view;\n  view = name;', self.MAIN)
        self.assertIn("import { initKeyerUi, keyTempoTo } from './keyerui.js';", self.MAIN)

    def test_news(self):
        self.assertIn("{ id: 19, version: '1.1.4'", NEWS)
        self.assertIn("'news.keyTempoIn'", NEWS)
        ats = re.findall(r"at: '([^']+)'", NEWS)
        self.assertEqual(ats, sorted(ats))   # in time order, none in the future of the next one
