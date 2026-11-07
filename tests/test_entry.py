# SPDX-License-Identifier: EUPL-1.2
"""Z-14 entry test (tests/entry.py = port of web/js/entry.js)."""
import random
import unittest

from tests import entry as E

KOCH = list("KMURESNAPTLWI.JZ=FOYVG5/Q92H38B?47C1D60X-(+&")


def trials(chars, bad=(), slow=(), miss=()):
    out = []
    for c in E.entry_sequence(chars, random.Random(1).random):
        out.append({'ch': c, 'ans': None if c in miss else ('X' if c in bad else c), 'ttr': 2500 if c in slow else 800})
    return out


class EntryTest(unittest.TestCase):
    def test_sequence(self):
        seq = E.entry_sequence(KOCH, random.Random(3).random)
        self.assertEqual(len(seq), len(KOCH) * E.ENTRY_REPS)
        self.assertEqual(sorted(seq), sorted(KOCH * E.ENTRY_REPS))
        self.assertFalse(any(a == b for a, b in zip(seq, seq[1:])))

    def test_all_known(self):
        r = E.entry_result(KOCH, trials(KOCH))
        self.assertEqual((r['level'], r['unsure']), (44, []))

    def test_prefix_stops_at_first_unsure(self):
        r = E.entry_result(KOCH, trials(KOCH, bad={'P'}))
        self.assertEqual(r['level'], KOCH.index('P'))
        self.assertEqual(r['unsure'], ['P'])
        r = E.entry_result(KOCH, trials(KOCH, slow={'W'}, miss={'4'}))
        self.assertEqual((r['level'], r['unsure']), (KOCH.index('W'), ['W', '4']))

    def test_minimum_level(self):
        r = E.entry_result(KOCH, trials(KOCH, bad={'K'}))
        self.assertEqual(r['level'], E.ENTRY_MIN_LEVEL)

    def test_per_char(self):
        r = E.entry_result(KOCH, trials(KOCH, bad={'U'}))
        u = next(x for x in r['perChar'] if x['ch'] == 'U')
        self.assertEqual((u['n'], u['acc'], u['ttr']), (2, 0.0, None))

    def test_server_keeps_entry_flag(self):
        from server.api import clean_detail
        d = clean_detail({"perChar": [{"ch": "K", "n": 2, "acc": 1.0, "ttr": 700}], "adv": "entry", "entry": True})
        self.assertIs(d["entry"], True)
        self.assertNotIn("entry", clean_detail({"perChar": [], "entry": "yes"}) or {})

    def test_coach_skips_entry_lesson(self):
        import json
        from server import coach
        les = {"at": "2026-11-07T10:00:00Z", "mode": "znak", "level": 2, "trials": 88, "acc": 0.8,
               "detail": json.dumps({"perChar": [], "entry": True})}
        self.assertEqual(coach.char_lessons([les]), [])
        self.assertEqual(len(coach.char_lessons([{**les, "detail": json.dumps({"perChar": []})}])), 1)

    def test_js_shape(self):
        for name in ('export function entrySequence(', 'export function entryResult('):
            self.assertIn(name, E.ENTRY_JS)
