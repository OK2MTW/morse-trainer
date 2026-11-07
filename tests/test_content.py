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
        self.assertGreaterEqual(len(T.ALL_ABBR), 150)  # 0.10.9: forms of all abbreviations and Q codes of the vocabulary trainer
        self.assertEqual(len(T.ALL_ABBR), len(set(T.ALL_ABBR)))
        for w in T.ALL_ABBR:  # only the project's character set
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
        a = T.make_items('abbr', ALL, 300, self.rng, T.ALL_ABBR)
        self.assertTrue(all(x in T.ALL_ABBR for x in a))
        lw = T.make_items('long', ALL, 300, self.rng)
        self.assertTrue(all(x in T.WORDS_LONG for x in lw))
        # few letters → filled up with shorter words / pseudo-words, but always only from mastered characters
        few = list('KMURESNAPTLWIO')
        for x in T.make_items('long', few, 200, self.rng) + T.make_items('abbr', few, 200, self.rng, T.ALL_ABBR):
            self.assertTrue(set(x) <= set(few), x)

    def test_mix_shares(self):
        items = T.make_items('mix', ALL, 4000, self.rng, T.ALL_ABBR)
        calls = sum(bool(re.match(r'^([A-Z]{1,2}|[0-9][A-Z])[0-9][A-Z]{1,3}(/[PM])?$', x)) and x not in T.ALL_ABBR
                    for x in items) / len(items)
        ab = sum(x in T.ALL_ABBR and x not in T.WORDS and x not in T.WORDS_LONG for x in items) / len(items)
        wd = sum(x in T.WORDS or x in T.WORDS_LONG for x in items) / len(items)
        self.assertAlmostEqual(calls, 1 - T.MIX_WORDS - T.MIX_ABBR, delta=0.04)
        self.assertAlmostEqual(ab, T.MIX_ABBR, delta=0.04)
        self.assertAlmostEqual(wd, T.MIX_WORDS, delta=0.04)




class TestQso(unittest.TestCase):
    """M9 (U5): QSO lines from templates – only mastered characters, order kept, fallback to the mix."""
    FULL = list(T.LETTERS + T.DIGITS + './?=')

    def test_full_set(self):
        import random
        rng = random.Random(5).random
        for _ in range(200):
            line = T.qso_line(self.FULL, rng)
            self.assertTrue(line)
            self.assertTrue(all(c in self.FULL for w in line for c in w), line)
            self.assertNotIn('{', ' '.join(line))

    def test_order_and_repetitions_kept(self):
        import random
        items = T.make_items('qso', self.FULL, 60, random.Random(1).random)
        self.assertEqual(len(items), 60)
        self.assertTrue(any(a == b for a, b in zip(items, items[1:])), 'CQ CQ / call call repetitions belong to a QSO')

    def test_fallback_without_needed_characters(self):
        import random
        chars = list('KMURESNAPTLWI')  # no digits → no call sign → no template fits
        items = T.make_items('qso', chars, 10, random.Random(2).random)
        self.assertEqual(len(items), 10)
        self.assertTrue(all(c in chars for w in items for c in w))


if __name__ == '__main__':
    unittest.main()


class TestAbbrFromVocab(unittest.TestCase):
    """0.10.9: copy-behind abbreviations only from items mastered in the vocabulary trainer."""

    def setUp(self):
        self.rng = random.Random(5).random

    @staticmethod
    def stat(d):
        return lambda lst, code: d.get((lst, code))

    def test_forms_of_mastered_items_only(self):
        self.assertEqual(T.copy_abbr_forms(self.stat({})), [])
        st = {('abbr', 'TNX'): [3, 0, 1], ('q', 'QRL'): [5, 1, 1], ('pfx', 'OK'): [9, 0, 1],
              ('abbr', 'FB'): [2, 0, 1],      # too few answers
              ('abbr', 'UR'): [5, 2, 1],      # 60 % right
              ('abbr', 'DE'): [5, 0, 0]}      # the last answer wrong
        forms = T.copy_abbr_forms(self.stat(st))
        self.assertIn('TNX', forms)
        self.assertIn('TKS', forms)           # every form of the item
        self.assertTrue(any(f.startswith('QRL') for f in forms))
        self.assertFalse({'OK', 'OL', 'FB', 'UR', 'DE'} & set(forms))  # prefixes are not abbreviations; not mastered

    def test_no_prosigns(self):
        st = {('abbr', p): [3, 0, 1] for p in T.PROSIGNS}
        self.assertEqual([f for f in T.copy_abbr_forms(self.stat(st)) if f in T.PROSIGNS], [])
        self.assertFalse(set(T.PROSIGNS) & set(T.ALL_ABBR))

    def test_nothing_mastered_gives_words(self):
        for content in ('abbr', 'mix'):  # QRL, TNX, CQ are neither words nor pseudo-word templates
            items = T.make_items(content, ALL, 1000, self.rng)
            self.assertEqual([x for x in items if x in ('TNX', 'QRL', 'CQ', 'QSL', 'RST')], [], content)

    def test_few_mastered_filled_with_words(self):
        forms = ['TNX', 'TKS']
        a = T.make_items('abbr', ALL, 3000, self.rng, forms)
        share = sum(x in forms for x in a) / len(a)
        self.assertAlmostEqual(share, len(forms) / T.ABBR_MIN, delta=0.04)
        self.assertTrue(all(x in forms or x in T.WORDS or len(x) <= T.PSEUDO_MAX for x in a))
        # a form needs mastered characters: without X no TNX
        b = T.make_items('abbr', [c for c in ALL if c != 'X'], 500, self.rng, forms)
        self.assertNotIn('TNX', b)

    def test_js_wiring(self):
        vocab_js, copy_js = T.VOCAB_JS, (T.ROOT / 'web/js/copylesson.js').read_text(encoding='utf-8')
        self.assertIn('export function copyAbbrForms(stat)', vocab_js)
        self.assertNotIn('abbr.js', T.CONTENT_JS)
        self.assertFalse((T.ROOT / 'web/js/abbr.js').exists())
        self.assertIn('export function makeItems(content, chars, n, rng = Math.random, abbrForms = [])', T.CONTENT_JS)
        self.assertIn('makeItems(C.plan.content, C.plan.chars, ROUND_ITEMS, Math.random, C.abbrForms)', copy_js)
        self.assertIn('vocabForms: () => vocab.copyForms()', (T.ROOT / 'web/js/main.js').read_text(encoding='utf-8'))
