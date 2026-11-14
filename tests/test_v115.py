# SPDX-License-Identifier: EUPL-1.2
"""1.1.5 (Martin 2026-11-14): the sending step `char` as a drill – a new character is played first, the student sends
it until right 3× in a row, then the next one; a shuffled round over all characters = one lesson."""
import json
import random
import unittest
from pathlib import Path

from tests import sendeval as E

WEB = Path(__file__).resolve().parent.parent / 'web'
KEYER = (WEB / 'js/keyerui.js').read_text(encoding='utf-8')
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
NEWS = (WEB / 'js/news.js').read_text(encoding='utf-8')


def fn_body(src, name):
    a = src.index(f'function {name}(')
    return src[a:src.index('\n  }\n', a)]


class CharDrillTest(unittest.TestCase):
    CHARS = list('KMURESNAPT')

    def test_need_from_js(self):
        self.assertEqual(E.SEND_DRILL_NEED, 3)

    def test_round_covers_all_characters_once(self):
        d = E.CharDrill(self.CHARS, random.Random(1).random)
        seen = []
        while True:
            seen.append(d.cur)
            r = None
            for _ in range(3):
                r = d.record(True)
            if r == 'round':
                break
            self.assertEqual(r, 'next')
        self.assertEqual(sorted(seen), sorted(self.CHARS))
        self.assertEqual(d.attempts, 30)
        self.assertIsNone(d.cur)
        self.assertEqual(d.record(True), 'round')

    def test_three_in_a_row_or_again(self):
        d = E.CharDrill(self.CHARS, random.Random(2).random)
        c = d.cur
        self.assertEqual([d.record(x) for x in (True, True, False, True, True)], ['again'] * 5)
        self.assertEqual(d.cur, c)                       # a mistake starts the count from zero
        self.assertEqual(d.record(True), 'next')
        self.assertNotEqual(d.cur, c)
        self.assertEqual((d.attempts, d.ok), (6, 5))

    def test_pseudo_random_order_and_no_repeat_across_rounds(self):
        a = E.CharDrill(self.CHARS, random.Random(3).random).bag
        b = E.CharDrill(self.CHARS, random.Random(4).random).bag
        self.assertNotEqual(a, b)
        for seed in range(30):
            d = E.CharDrill(self.CHARS, random.Random(seed).random, last=a[-1])
            self.assertNotEqual(d.bag[0], a[-1])
        self.assertEqual(E.CharDrill(['E', 'E', 'T'], random.Random(0).random).bag.count('E'), 1)

    def test_js_shape(self):
        js = E.SENDEVAL_JS
        for s in ('export class CharDrill {', 'if (this.streak < this.need) return \'again\';',
                  "return this.i >= this.bag.length ? 'round' : 'next';", 'function shuffled(a, rng, last = null)',
                  'if (a.length > 1 && a[0] === last) [a[0], a[1]] = [a[1], a[0]];', '[...new Set(chars)]'):
            self.assertIn(s, js)


class DrillUiTest(unittest.TestCase):
    def test_start_plays_the_first_character(self):
        body = fn_body(KEYER, 'exStart')
        self.assertIn("if (kindNow() === 'char')", body)
        self.assertIn('new CharDrill(getChars(), Math.random, SEND_DRILL_NEED, X.drill?.bag.at(-1) ?? null)', body)
        self.assertIn('playTarget();', body)

    def test_listen_then_send(self):
        body = fn_body(KEYER, 'playTarget')
        self.assertIn("X.phase = 'listen';", body)
        self.assertIn('player.play(X.target).done', body)
        self.assertIn("X.phase = 'send';", body)
        self.assertIn('tok !== X.playTok', body)
        self.assertIn("if (X.phase === 'send') exTone(", KEYER)   # keying while listening is not the answer

    def test_drill_goes_on_by_itself(self):
        # 1.1.7: every sent character counts on its own and live (Martin keyed "A A A" in one attempt)
        self.assertIn('if (X.drill && drillLive(false)) return;', fn_body(KEYER, 'exTone'))
        self.assertIn('if (!drillLive(true)) {', fn_body(KEYER, 'exFinish'))
        body = fn_body(KEYER, 'drillLive')
        self.assertIn("const chars = dec.chars.filter((c) => c.ch !== ' ');", body)
        self.assertIn('const upto = final ? chars.length : chars.length - 1;', body)
        self.assertIn('X.drill.record(ok, got)', body)
        self.assertIn('playTarget();', body)
        self.assertIn('if (X.lesson) lessonSave(drillSummary(X.results, X.drill, MORSE));', body)

    def test_page(self):
        self.assertIn('id="send-ex-play"', HTML)
        self.assertIn("$('#send-ex-play').addEventListener('click'", KEYER)

    def test_texts(self):
        keys = ('intro', 'progress', 'listen', 'go', 'ok', 'bad', 'newChar', 'play')
        for lang in ('cs', 'en'):
            d = json.loads((WEB / f'i18n/{lang}.json').read_text(encoding='utf-8'))
            for k in keys:
                self.assertTrue(d[f'send.drill.{k}'], k)
            self.assertIn('3', d['send.lesson.about.char'])
            self.assertTrue(d['news.sendDrill'])
        self.assertIn("{ id: 20, version: '1.1.5'", NEWS)


class DrillLiveTest(unittest.TestCase):
    """1.1.7: the port of drillLive – characters of one attempt one by one."""

    def drill(self):
        d = E.CharDrill(list('AKM'), random.Random(5).random)
        return d, d.cur

    def test_three_in_one_attempt(self):
        d, c = self.drill()
        seen, r = E.drill_live(d, [c, c], 0, final=False)   # live: the last character may still grow
        self.assertEqual((seen, r), (1, 'again'))
        seen, r = E.drill_live(d, [c, c, c, c], seen, final=False)
        self.assertEqual((seen, r), (3, 'next'))           # the third right one moves on at once
        self.assertNotEqual(d.cur, c)

    def test_mistake_in_the_middle_resets(self):
        d, c = self.drill()
        seen, r = E.drill_live(d, [c, 'W', c, c], 0, final=True)
        self.assertEqual((seen, r, d.streak, d.cur), (4, 'again', 2, c))
        self.assertEqual(d.misses, [(c, 'W')])

    def test_summary_counts_characters(self):
        js = E.SENDEVAL_JS
        for s in ('export function drillSummary(list, drill, morse)', 's.acc = { ok: drill.ok, sub: n - drill.ok',
                  'this.misses.push([this.cur, got])', 's.tasks = n;'):
            self.assertIn(s, js)


if __name__ == '__main__':
    unittest.main()
