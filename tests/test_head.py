# SPDX-License-Identifier: EUPL-1.2
"""U6 head copy (0.10.14): templates, questions and checking of written answers (tests/head.py = port of head.js)."""
import json
import re
import unittest
from pathlib import Path

from tests import head as H

WEB = Path(__file__).resolve().parent.parent / 'web'


class TestTemplates(unittest.TestCase):
    def test_parsed(self):
        self.assertGreaterEqual(len(H.TEMPLATES), 5)
        self.assertEqual(len(H.TEMPLATES), H.HEAD_JS.count('{ text: '))

    def test_fields_present_in_text(self):
        for tp in H.TEMPLATES:
            ph = set(re.findall(r'\{(\w+)\}', tp['text']))
            self.assertIn(tp['from'], ph)
            if tp['to']:
                self.assertIn(tp['to'], ph)
            for f in tp['fields']:
                self.assertIn(f, ph, tp['text'])
                self.assertIn(f, H.HEAD_FIELDS)
            self.assertGreaterEqual(1 + bool(tp['to']) + len(tp['fields']), H.HEAD_Q, tp['text'])  # enough questions

    def test_values_exist_in_content(self):
        content = (WEB / 'js' / 'content.js').read_text()
        for tp in H.TEMPLATES:
            for k in re.findall(r'\{(\w+)\}', tp['text']):
                self.assertRegex(content, rf'\b{k}: ', k)  # qsoValues provides it

    def test_server_fields_match(self):
        from server import api
        self.assertEqual(list(api.HEAD_FIELDS), H.HEAD_FIELDS)

    def test_texts(self):
        for p in (WEB / 'i18n').glob('*.json'):
            if p.stem == 'languages':
                continue
            d = json.loads(p.read_text())
            for f in H.HEAD_FIELDS:
                self.assertIn(f'head.q.{f}', d, p.stem)
                self.assertIn(f'head.f.{f}', d, p.stem)


class TestScoring(unittest.TestCase):
    QSO = {'answers': {'from': 'OK1ABC', 'RST': '579', 'PWR': '100', 'TEMP': '12', 'NAME': 'JAN'},
           'questions': ['from', 'RST', 'PWR']}

    def test_normalize(self):
        self.assertEqual(H.normalize('from', ' ok1 abc '), 'OK1ABC')
        self.assertEqual(H.normalize('PWR', '100 W'), '100')
        self.assertEqual(H.normalize('TEMP', '12c'), '12')
        self.assertEqual(H.normalize('from', 'OK1ABC/P'), 'OK1ABC/P')

    def test_score(self):
        sc = H.score_head(self.QSO, {'from': 'ok1abc', 'RST': '599', 'PWR': '100w'})
        self.assertEqual((sc['n'], sc['ok']), (3, 2))
        self.assertFalse(H.score_head(self.QSO, {})['res'][0]['ok'])  # empty answer is wrong
        self.assertFalse(H.is_correct('NAME', '', ''))

    def test_summary(self):
        r1 = {'sc': H.score_head(self.QSO, {'from': 'OK1ABC', 'RST': '579', 'PWR': '5'})}
        r2 = {'sc': H.score_head(self.QSO, {'from': 'X', 'RST': '579', 'PWR': '100'})}
        s = H.head_summary([r1, r2])
        self.assertEqual((s['q'], s['ok'], s['rounds']), (6, 4, 2))
        self.assertEqual(s['fields'], {'from': [2, 1], 'RST': [2, 2], 'PWR': [2, 1]})

    def test_js_shape(self):
        for name in ('export function normalize(', 'export function makeHeadQso(', 'export function scoreHead(',
                     'export function headSummary('):
            self.assertIn(name, H.HEAD_JS)
