# SPDX-License-Identifier: EUPL-1.2
"""VK D3 evaluation of sending (tests/sendeval.py = port of web/js/sendeval.js): form metrics on simulated hands,
correctness against the task, the one thing to focus on."""
import random
import unittest

from tests import decoder as D
from tests import sendeval as E
from tests.test_decoder import MORSE, hand


def run(words, wpm=18, target=None, **kw):
    tones = hand(words, wpm, **kw)
    dec = D.decode_tones(tones, wpm, MORSE)
    if target is None:
        return tones, dec, E.send_metrics(tones, dec)
    return tones, dec, E.evaluate_sending(target, tones, dec, MORSE)


WORDS = ['CQ', 'DE', 'OK2MTW', 'PARIS', 'TEST']


class SendEvalTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(E.RATIO, [3, 2.5, 3.5, 2.2, 4])
        self.assertEqual(E.IN_GAP, [1, 0.7, 1.4, 0.5, 2])
        self.assertEqual(E.CHAR_GAP, [3, 2.5, 4, 2, 5])
        self.assertEqual(E.WORD_GAP, [7, 5.5, 9, 4.5, 12])
        self.assertEqual((E.CV_GOOD, E.CV_OK, E.ACC_GOOD, E.ACC_OK, E.MIN_N, E.WINDOW), (0.15, 0.25, 0.9, 0.75, 3, 60))
        for frag in ("import { align, score } from './copy.js';", 'if (v >= b[1] && v <= b[2]) return',
                     'for (const el of c) u += el === DOT ? 2 : 4;',
                     'if (kind === 0) { if (!tones[i].el && !tones[i - 1].el) v.inGaps.push(g); }',
                     'if (v.hand && v.dots.length >= EVAL_MIN_N && v.dashes.length >= EVAL_MIN_N) {',
                     "const dist = Math.abs(Math.log(x.v / b[0])) / Math.log(dir === 'low' ? b[0] / b[3] : b[4] / b[0]);",
                     'return (1.4826 * median(arr.map((x) => Math.abs(x - m)))) / m;'):
            self.assertIn(frag, E.SENDEVAL_JS)

    def test_text_units(self):
        self.assertEqual(E.text_units(['.--.', '.-', '.-.', '..', '...']), 43)   # PARIS without the word gap
        self.assertEqual(E.text_units(['-', ' ', '-']), 3 + 7 + 3)
        self.assertEqual(E.text_units([]), 0)

    def test_perfect_hand(self):
        for wpm in (12, 25):
            _, _, m = run(WORDS, wpm)
            self.assertAlmostEqual(m['ratio']['v'], 3)
            self.assertAlmostEqual(m['inGap']['v'], 1)
            self.assertAlmostEqual(m['charGap']['v'], 3)
            self.assertAlmostEqual(m['wordGap']['v'], 7)
            self.assertAlmostEqual(m['stability']['v'], 0)
            self.assertAlmostEqual(m['charWpm'], wpm)
            self.assertAlmostEqual(m['effWpm'], wpm)
            self.assertEqual({m[k]['st'] for k in ('ratio', 'inGap', 'charGap', 'wordGap', 'stability')}, {'good'})
            self.assertEqual(E.focus_of(m)['key'], 'good')

    def test_habits_are_found(self):
        _, _, m = run(WORDS, ratio=2.0)
        self.assertEqual((m['ratio']['st'], E.focus_of(m)['key'], E.focus_of(m)['dir']), ('bad', 'ratio', 'low'))
        _, _, m = run(WORDS, ratio=4.3)
        self.assertEqual((m['ratio']['st'], E.focus_of(m)['dir']), ('bad', 'high'))
        _, _, m = run(WORDS, gapk=0.65)    # characters run together: 1.95 units
        self.assertEqual((m['charGap']['st'], E.focus_of(m)['key'], E.focus_of(m)['dir']), ('bad', 'charGap', 'low'))
        _, _, m = run(WORDS, gapk=1.45)    # 4.35 units between characters, 10 between words
        self.assertEqual((m['charGap']['st'], E.focus_of(m)['key']), ('ok', 'charGap'))
        _, _, m = run(WORDS * 2, sigma=0.3, rng=random.Random(5))
        self.assertEqual(m['stability']['st'], 'bad')
        self.assertGreater(m['stability']['dot'], E.CV_OK)

    def test_moderate_hand_mostly_good(self):
        # σ 8 % (a steady hand): the form should come out good in most attempts
        goods = 0
        for seed in range(20):
            _, _, m = run(WORDS, sigma=0.08, rng=random.Random(seed))
            goods += E.focus_of(m)['key'] == 'good'
        self.assertGreaterEqual(goods, 17)

    def test_iambic_has_no_ratio(self):
        _, _, m = run(WORDS, known=True)
        self.assertIsNone(m['ratio'])
        self.assertIsNone(m['inGap'])
        self.assertAlmostEqual(m['charGap']['v'], 3)
        self.assertIsNone(m['stability']['dot'])
        _, _, m = run(WORDS, known=True, gapk=0.6)
        self.assertEqual((E.focus_of(m)['key'], E.focus_of(m)['dir']), ('charGap', 'low'))

    def test_correctness_against_task(self):
        _, _, ev = run(['CQ', 'TEST'], target='CQ TEST')
        self.assertEqual((ev['acc']['ok'], ev['acc']['n'], ev['acc']['v'], ev['acc']['st']), (6, 6, 1, 'good'))
        self.assertEqual(ev['subs'], [])
        _, _, ev = run(['CQ', 'TEST'], target='CK TEST')     # Q sent instead of K
        self.assertEqual(ev['acc']['sub'], 1)
        self.assertEqual(ev['subs'], [{'want': 'K', 'wantCode': '-.-', 'got': 'Q', 'gotCode': '--.-'}])
        self.assertEqual(ev['acc']['st'], 'ok')                 # 5/6 = 83 %
        f = E.focus_of(ev['metrics'], ev)
        self.assertEqual((f['key'], f['sub']['want'], f['sub']['got']), ('acc', 'K', 'Q'))
        _, _, ev = run(['CQ'], target='CQ TEST')
        self.assertEqual((ev['acc']['del'], ev['acc']['st']), (4, 'bad'))

    def test_exercise_constants(self):
        self.assertEqual(E.SEND_KINDS, ['char', 'group', 'word', 'qso'])
        self.assertEqual((E.SEND_TASKS, E.SEND_MIN_CHARS, E.SEND_GROUP_LEN), (10, 10, 5))
        self.assertEqual((E.SEND_END_MS, E.SEND_END_UNITS), (2000, 7))
        for frag in ("import { pools, word, SHARE_LETTERS, SHARE_DIGITS } from './content.js';",
                     "const avail = chars.length > 1 ? chars.filter((c) => c !== prev) : chars;",
                     "const conf = [...cnt.values()].sort((a, b) => b.n - a.n).slice(0, 3);"):
            self.assertIn(frag, E.SENDEVAL_JS)

    def test_send_task(self):
        rng = random.Random(7).random
        chars = list('KMURESNAPT')            # the first 10 in Koch order
        prev = None
        for _ in range(200):
            ch = E.send_task('char', chars, rng, prev)
            self.assertIn(ch, chars)
            self.assertNotEqual(ch, prev)
            prev = ch
            g = E.send_task('group', chars, rng)
            self.assertEqual(len(g), 5)
            self.assertTrue(set(g) <= set(chars))
            w = E.send_task('word', chars, rng)
            self.assertTrue(set(w) <= set(chars), w)
        self.assertEqual(E.send_task('char', ['K'], rng, 'K'), 'K')

    def test_session_summary(self):
        evs = [run(['CQ'], target='CQ')[2], run(['CQ'], target='CK')[2], run(['CQ'], target='CK')[2],
               run(['TEST'], target='TEST', ratio=2.0)[2]]
        s = E.session_summary(evs)
        self.assertEqual((s['acc']['ok'], s['acc']['n'], s['tasks']), (8, 10, 4))
        self.assertEqual(s['acc']['st'], 'ok')
        self.assertEqual([(c['want'], c['got'], c['n']) for c in s['conf']], [('K', 'Q', 2)])
        # pooled raw values: CQ has 1 gap between characters, TEST 3 → 3 + 3×1 = 6 values; the dashes of TEST (ratio 2)
        # pooled with the dashes of CQ (ratio 3)
        self.assertAlmostEqual(s['metrics']['charGap']['v'], 3)
        self.assertIsNotNone(s['metrics']['ratio'])
        # single characters: no metric per attempt, but pooled over the series
        singles = [run([ch], target=ch)[2] for ch in 'KMRAN']
        self.assertTrue(all(ev['metrics']['ratio'] is None for ev in singles))
        self.assertAlmostEqual(E.session_summary(singles)['metrics']['ratio']['v'], 3)
        self.assertAlmostEqual(E.session_summary(singles)['metrics']['inGap']['v'], 1)
        self.assertEqual(E.focus_of(s['metrics'], s)['key'], 'acc')
        self.assertEqual(E.session_summary([])['acc']['v'], 0)

    def test_few_values_no_metric(self):
        _, _, m = run(['E'])
        self.assertIsNone(m['ratio'])
        self.assertIsNone(m['charGap'])
        self.assertIsNone(m['stability'])
        self.assertEqual(E.focus_of(m)['key'], 'good')

    def test_qso_step(self):
        rng = random.Random(3).random
        koch = list('KMURESNAPTLWI.JZ=FOY,VG5/Q92H38B?47C1D60X')
        self.assertFalse(E.qso_ready(list('KMURESNAPT')))
        self.assertTrue(E.qso_ready(koch))
        self.assertEqual(E.SEND_STEPS, ['char', 'group', 'word', 'qso'])
        self.assertEqual((E.SEND_PASS_ACC, E.SEND_PASS_N), (0.9, 2))
        for _ in range(200):
            line = E.send_task('qso', koch, rng)
            self.assertTrue(set(line.replace(' ', '')) <= set(koch), line)
            self.assertNotIn('{', line)
            w = E.send_task('qso', list('KMURESNAPT'), rng)     # not ready → a word of the known letters
            self.assertTrue(set(w) <= set('KMURESNAPT'), w)
        self.assertRegex(E.qso_call(rng), r'^[A-Z0-9]{1,2}[0-9][A-Z]{2,3}$')

    def test_one_element(self):
        self.assertTrue(E.one_element('-.-.', '-.-..'))
        self.assertTrue(E.one_element('--.-', '-.-'))
        self.assertFalse(E.one_element('.-', '-.'))
        self.assertFalse(E.one_element('', '.'))

    def test_hand_habits(self):
        m = {'charGap': {'v': 3.0}, 'wordGap': {'v': 7.0}}
        self.assertEqual(E.hand_habits(m), [])
        m = {'charGap': {'v': 5.0}, 'wordGap': {'v': 6.0}}
        self.assertEqual([h['key'] for h in E.hand_habits(m)], ['wordShort', 'charLong'])
        ev = {'subs': [{'wantCode': '-.-.', 'gotCode': '-.-..'}, {'wantCode': '--.-', 'gotCode': '--.--'},
                       {'wantCode': '.', 'gotCode': '-'}]}
        self.assertEqual(E.hand_habits({}, ev), [{'key': 'paddle', 'v': 2}])
        for frag in ('export function handHabits(metrics, ev = null)', 'if (n >= HABIT_PADDLE_N)',
                     "if (kind === 'qso') return qsoReady(chars) ? qsoLine(rng) : word(chars, rng);"):
            self.assertIn(frag, E.SENDEVAL_JS)

    def test_hand_habits_on_martins_hw_recordings(self):
        import json
        from tests.test_decoder import ROOT
        recs = json.loads((ROOT / 'tests/data/key_recordings_hw.json').read_text())['recordings']
        found = set()
        for r in recs:
            tones = [{'start': a, 'end': b} for a, b in r['tones']]
            dec = D.decode_tones(tones, r.get('wpm', 20), MORSE, {'machine': True})
            ev = E.evaluate_sending(r['meant'], dec['tones'], dec, MORSE)
            found |= {h['key'] for h in E.hand_habits(ev['metrics'], ev)}
        # Martin 2026-11-13: long gaps between characters and an unreliable paddle return – both must be named
        self.assertIn('charLong', found)


if __name__ == '__main__':
    unittest.main()
