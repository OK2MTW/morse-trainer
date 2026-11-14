# SPDX-License-Identifier: EUPL-1.2
"""1.1.6 (Martin 2026-11-14): the Sending page shows only the essentials – the task, what is sent and what an operator
would read; characters and tempo, the analysis (a short indicator when collapsed), the HW key and the firmware are
collapsed."""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
KEYER = (WEB / 'js/keyerui.js').read_text(encoding='utf-8')
FWUI = (WEB / 'js/fwui.js').read_text(encoding='utf-8')
NEWS = (WEB / 'js/news.js').read_text(encoding='utf-8')


def section():
    a = HTML.index('<section id="view-key"')
    return HTML[a:HTML.index('</section>', a)]


def details(sec, did):
    a = sec.index(f'<details id="{did}"')
    depth, i = 0, a
    for m in re.finditer(r'<(/?)details\b', sec[a:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return sec[a:a + m.end()]
    raise AssertionError(did)


class SendingPageTest(unittest.TestCase):
    def test_collapsed_parts(self):
        sec = section()
        for did, inside in (('send-setup', ('data-key="sendChars"', 'data-key="sendWpm"', 'id="send-wpm-key"')),
                            ('key-stats', ('id="key-eval"', 'id="key-est"', 'id="key-hand"', 'id="key-codes"',
                                           'id="key-diag-box"', 'id="key-rec"')),
                            ('key-hw-box', ('id="key-sidetone"', 'id="key-learn"', 'id="key-log"')),
                            ('fw-box', ('id="fw-wizard"', 'id="fw-midi-on"'))):
            d = details(sec, did)
            self.assertNotIn(f'<details id="{did}" open', sec)   # collapsed by default
            for s in inside:
                self.assertIn(s, d, (did, s))

    def test_essentials_visible(self):
        sec = section()
        for did in ('send-setup', 'key-stats', 'key-hw-box', 'fw-box'):
            d = details(sec, did)
            for s in ('id="send-lesson-start"', 'id="send-ex-target"', 'id="key-text"', 'id="key-read"', 'id="key-clear"'):
                self.assertNotIn(s, d)
        self.assertNotIn('data-go="settings"', sec)

    def test_indicators(self):
        self.assertIn('export function statsIndicator(m, wpm)', KEYER)
        self.assertIn('sum.textContent = statsIndicator(m, r.wpm);', KEYER)
        self.assertIn("$('#send-setup-sum').textContent = t('send.setupSum'", KEYER)
        self.assertIn("$('#fw-box').open = true;", FWUI)   # the update offer opens the collapsed firmware

    def test_texts(self):
        for lang in ('cs', 'en'):
            d = json.loads((WEB / f'i18n/{lang}.json').read_text(encoding='utf-8'))
            for k in ('key.textLabel', 'send.setup', 'key.stats', 'news.sendTidy'):
                self.assertTrue(d[k])
            self.assertIn('{n}', d['send.setupSum'])
            self.assertIn('{wpm}', d['send.setupSum'])
            self.assertNotIn('(', d['key.title'])   # no "(experimental)" any more
        self.assertIn("{ id: 21, version: '1.1.6'", NEWS)


if __name__ == '__main__':
    unittest.main()
