# SPDX-License-Identifier: EUPL-1.2
"""Tests of copy-behind content (Python port of content.js, M7 + M8): only mastered characters, lengths, words, abbreviations, call signs."""
import random
import re
import unittest

from server import coach
from tests import content as T

ALL = list(coach.KOCH)


class TestWords(unittest.TestCase):
    def test_list(self):
        self.assertGreaterEqual(len(T.WORDS), 180)
        self.assertEqual(len(T.WORDS), len(set(T.WORDS)), [w for w in T.WORDS if T.WORDS.count(w) > 1])
        for w in T.WORDS:
            self.assertRegex(w, r'^[A-Z]{2,5}$')
        raw = re.search(r'WORDS = `(.*?)`', T.WORDS_JS, re.S).group(1).split()
        self.assertEqual(raw, T.WORDS)  # filtr v JS nic nevyhazuje

    def test_templates(self):
        lens = {len(t) for t in T.PSEUDO_TEMPLATES}
        self.assertEqual((min(lens), max(lens)), (T.PSEUDO_MIN, T.PSEUDO_MAX))

    def test_generators_in_js(self):
        names = set(re.findall(r'^  (\w+): \(chars', T.CONTENT_JS, re.M))
        self.assertEqual(names, set(T.GENERATORS))
        self.assertLessEqual({s["content"] for s in coach.COPY_STEPS}, names)

    def test_long_and_abbr_lists(self):
        self.assertGreaterEqual(len(T.WORDS_LONG), 150)
        self.assertEqual(len(T.WORDS_LONG), len(set(T.WORDS_LONG)))
        raw = re.search(r'WORDS_LONG = `(.*?)`', T.WORDS_JS, re.S).group(1).split()
        self.assertEqual(raw, T.WORDS_LONG)
        self.assertFalse(set(T.WORDS_LONG) & set(T.WORDS))
        self.assertGreaterEqual(len(T.ABBR), 60)
        self.assertEqual(len(T.ABBR), len(set(T.ABBR)), [w for w in T.ABBR if T.ABBR.count(w) > 1])
        for w in T.ABBR:  # only the project's character set
            self.assertTrue(set(w) <= set(ALL), w)


class TestGenerators(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(3).random

    def test_only_mastered(self):
        part = list('KMURESNAPTLWI.JZ=FO')
        for content in T.GENERATORS:
            for it in T.make_items(content, part, 200, self.rng):
                self.assertTrue(set(it) <= set(part), (content, it))

    def test_group_lengths_and_shares(self):
        items = [T.group(ALL, self.rng) for _ in range(3000)]
        self.assertTrue(all(T.GROUP_MIN <= len(x) <= T.GROUP_MAX for x in items))
        s = ''.join(items)
        letters = sum(c in T.LETTERS for c in s) / len(s)
        digits = sum(c in T.DIGITS for c in s) / len(s)
        self.assertAlmostEqual(letters, 0.7, delta=0.03)
        self.assertAlmostEqual(digits, 0.2, delta=0.03)

    def test_pseudo(self):
        items = [T.pseudo(ALL, self.rng) for _ in range(2000)]
        self.assertTrue(all(T.PSEUDO_MIN <= len(x) <= T.PSEUDO_MAX and x.isalpha() for x in items))
        # does not crash without vowels
        self.assertTrue(T.pseudo(list('KMRS'), self.rng))
        # without letters → a group of the other characters
        self.assertTrue(set(T.pseudo(list('5/9'), self.rng)) <= set('5/9'))

    def test_words_full_set(self):
        items = T.make_items('words', ALL, 300, self.rng)
        self.assertTrue(all(x in T.WORDS for x in items))
        self.assertTrue(all(a != b for a, b in zip(items, items[1:])))

    def test_words_few_letters_mix_pseudo(self):
        few = list('KMURESN')  # few letters → few words
        av = T.words_for(few)
        self.assertLess(len(av), T.WORDS_MIN)
        items = T.make_items('words', few, 300, self.rng)
        share = sum(x in av for x in items) / len(items)
        self.assertGreater(share, 0.1)
        self.assertLess(share, 0.9)


class TestU4Content(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(5).random

    def test_calls_format(self):
        items = [T.call(ALL, self.rng) for _ in range(3000)]
        pat = re.compile(r'^([A-Z]{1,2}|[0-9][A-Z])[0-9][A-Z]{1,3}(/[PM])?$')
        for x in items:
            self.assertRegex(x, pat)
            self.assertNotEqual(x[0], 'Q')
        slash = sum('/' in x for x in items) / len(items)
        self.assertAlmostEqual(slash, T.CALL_SLASH, delta=0.03)
        self.assertGreater(len(set(items)), 2500)  # generated, not from a list

    def test_calls_without_digits_or_slash(self):
        no_dig = [c for c in ALL if c not in T.DIGITS]
        self.assertTrue(all(not any(ch.isdigit() for ch in T.call(no_dig, self.rng)) for _ in range(200)))
        no_sl = [c for c in ALL if c != '/']
        self.assertTrue(all('/' not in T.call(no_sl, self.rng) for _ in range(500)))

    def test_abbr_and_long(self):
        a = T.make_items('abbr', ALL, 300, self.rng)
        self.assertTrue(all(x in T.ABBR for x in a))
        lw = T.make_items('long', ALL, 300, self.rng)
        self.assertTrue(all(x in T.WORDS_LONG for x in lw))
        # few letters → filled up with shorter words / pseudo-words, but always only from mastered characters
        few = list('KMURESNAPTLWIO')
        for x in T.make_items('long', few, 200, self.rng) + T.make_items('abbr', few, 200, self.rng):
            self.assertTrue(set(x) <= set(few), x)

    def test_mix_shares(self):
        items = T.make_items('mix', ALL, 4000, self.rng)
        calls = sum(bool(re.match(r'^([A-Z]{1,2}|[0-9][A-Z])[0-9][A-Z]{1,3}(/[PM])?$', x)) and x not in T.ABBR
                    for x in items) / len(items)
        ab = sum(x in T.ABBR for x in items) / len(items)
        wd = sum(x in T.WORDS or x in T.WORDS_LONG for x in items) / len(items)
        self.assertAlmostEqual(calls, 1 - T.MIX_WORDS - T.MIX_ABBR, delta=0.04)
        self.assertAlmostEqual(ab, T.MIX_ABBR, delta=0.04)
        self.assertAlmostEqual(wd, T.MIX_WORDS, delta=0.04)


if __name__ == '__main__':
    unittest.main()
