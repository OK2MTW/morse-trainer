# SPDX-License-Identifier: EUPL-1.2
"""0.16.0 virtual operator of the CW room (web/js/vo.js): whole QSOs in both modes from simulated decoder output
(typos, AGN, QRS, the end with SK), the timing of its own sending and the port of the JS."""
import random
import unittest

from tests import vo as V
from tests import decoder as D
from tests.test_decoder import MORSE
from tests.test_decoder_hw import hand, build


def rng_of(seed):
    return random.Random(seed).random


def keyed(text, wpm=22, seed=0, late=4):
    """What the decoder makes of the user's over keyed on a HW key (human gaps, late key events) → over_text."""
    rng = random.Random(seed)
    seq = []
    for w in text.split():
        if w in V.PROSIGN_CODES:
            seq.append((V.PROSIGN_CODES[w], 2))
        else:
            seq += build(w)
    r = D.decode_tones(hand(seq, wpm, rng, sigma=0.15, late=late), 18, MORSE, machine=True, dot=1200 / wpm)
    return V.over_text(r['chars'])


class HearTest(unittest.TestCase):
    def test_tolerant_reading(self):
        h = V.hear('OK1XYZ DE OK2MTW GM TNX FER CALL = UR RST 579 579 = NAME IS MARTIN = QTH LIBEREC = HW? K',
                   'OK1XYZ')
        self.assertTrue(h['to_vo'])
        self.assertEqual((h['from'], h['rst'], h['name'], h['qth']), ('OK2MTW', '579', 'MARTIN', 'LIBEREC'))
        self.assertTrue(h['end'])
        h = V.hear('OK1XZ DE OK2MTW UR 5NN OP JAN K', 'OK1XYZ')   # one character missing in the call
        self.assertTrue(h['to_vo'])
        self.assertEqual((h['rst'], h['name']), ('5NN', 'JAN'))
        self.assertFalse(V.hear('OK1ABC DE OK2MTW K', 'OK1XYZ')['to_vo'])   # two mistakes = someone else
        h = V.hear('PSE AGN ? QRS RIG? ANT ? 73 SK', 'OK1XYZ')
        self.assertTrue(h['agn'] and h['qrs'] and h['bye'] and h['end'])
        self.assertEqual(h['asks'], ['RIG', 'ANT'])
        self.assertTrue(V.hear('CQ CQ DE OK2MTW K', 'OK1XYZ')['cq'])
        self.assertTrue(V.hear('', 'OK1XYZ')['empty'])

    def test_over_text_prosigns(self):
        chars = [{'ch': 'T', 'code': '-'}, {'ch': 'U', 'code': '..-'}, {'ch': ' ', 'code': ' '},
                 {'ch': '*', 'code': '...-.-'}, {'ch': '(', 'code': '-.--.'}, {'ch': '+', 'code': '.-.-.'}]
        self.assertEqual(V.over_text(chars), 'TU SK KN AR')
        self.assertTrue(V.over_ended('TU SK'))
        self.assertFalse(V.over_ended('NAME MARTIN'))

    def test_keyed_over_reaches_the_vo(self):
        self.assertEqual(keyed('CQ CQ DE OK2MTW K'), 'CQ CQ DE OK2MTW K')
        self.assertEqual(keyed('TU 73 SK'), 'TU 73 SK')


class QsoTest(unittest.TestCase):
    def run_qso(self, mode, overs, seed=1, first_cq=False):
        vo = V.VirtualOperator(mode=mode, user_call='OK2MTW', rng=rng_of(seed), hour=20)
        log = []
        if first_cq:
            log.append(vo.cq()['text'])
        for o in overs:
            r = vo.reply(keyed(o.replace('{VO}', vo.call), seed=len(log)))
            log.append(r['text'])
        return vo, log

    def test_quick_user_calls_cq(self):
        vo, log = self.run_qso('quick', ['CQ CQ DE OK2MTW OK2MTW K',
                                         '{VO} DE OK2MTW GE TNX FER CALL UR RST 599 599 NAME MARTIN QTH LIBEREC HW? K',
                                         'TNX QSO 73 SK'])
        v = vo.call
        self.assertEqual(log[0], f'OK2MTW DE {v} {v} K')
        self.assertTrue(log[1].startswith(f'OK2MTW DE {v} R TNX FER RPRT DR MARTIN = UR RST '))
        self.assertIn(f"NAME {vo.p['name']}", log[1])
        self.assertNotIn('RIG HR', log[1])   # quick: no topics
        self.assertTrue(log[2].endswith(f'OK2MTW DE {v} SK'))
        self.assertTrue(vo.phase == 'done')

    def test_quick_user_calls_the_vo(self):
        vo, log = self.run_qso('quick', ['{VO} DE OK2MTW K', '{VO} DE OK2MTW R TNX UR 579 NAME JAN QTH BRNO K'],
                               first_cq=True)
        v = vo.call
        self.assertEqual(log[0], f'CQ CQ CQ DE {v} {v} {v} K')
        self.assertTrue(log[1].startswith(f'OK2MTW DE {v} GE TNX FER CALL = UR RST'))
        self.assertTrue(log[1].endswith('KN'))
        self.assertIn('DR JAN', log[2])
        self.assertTrue(log[2].endswith('SK'))
        self.assertEqual(vo.phase, 'done')

    def test_chatty_topics_and_questions(self):
        for seed in range(6):
            vo, log = self.run_qso('chatty', ['CQ DE OK2MTW K', '{VO} DE OK2MTW UR RST 599 NAME MARTIN QTH LIBEREC K',
                                              'R FB WX? K', 'TNX K', 'TNX K', 'TNX K'], seed=seed)
            topics = sum(x.count(k) for x in log if x for k in ('RIG HR', 'ANT ', 'PWR ', 'WX ', 'AGE ', 'QSL VIA'))
            self.assertGreaterEqual(topics, V.VO_TOPICS_MIN, log)
            self.assertIn('WX ', log[2], log)   # the asked topic is answered at once
            self.assertTrue(any(x and x.endswith('SK') for x in log), log)
            self.assertEqual(vo.phase, 'done', log)

    def test_agn_qrs_qrq(self):
        vo = V.VirtualOperator(user_call='OK2MTW', rng=rng_of(3))
        first = vo.reply('CQ CQ DE OK2MTW K')['text']
        self.assertEqual(vo.reply('AGN K')['text'], first)
        r = vo.reply('QRS PSE K')
        self.assertEqual((r['text'], r['wpm']), (first, V.VO_WPM - V.VO_QRS))
        r = vo.reply('QRQ')
        self.assertEqual(r['wpm'], V.VO_WPM)
        for _ in range(20):
            vo.reply('QRS')
        self.assertEqual(vo.wpm, V.VO_WPM_MIN)

    def test_not_understood(self):
        vo = V.VirtualOperator(user_call='OK2MTW', rng=rng_of(4))
        v = vo.call
        self.assertEqual(vo.reply('EEE TTT K')['text'], f'QRZ? DE {v} K')
        vo.reply('CQ DE OK2MTW K')
        self.assertEqual(vo.reply('IIII K')['text'], f'OK2MTW DE {v} PSE AGN K')
        self.assertIsNone(vo.reply('')['text'])
        anon = V.VirtualOperator(rng=rng_of(4))
        self.assertEqual(anon.reply('CQ CQ K')['text'], f'QRZ? DE {anon.call} K')
        self.assertEqual(anon.reply('CQ DE OK1ABC K')['text'], f'OK1ABC DE {anon.call} {anon.call} K')

    def test_done_keeps_silent(self):
        vo, log = self.run_qso('quick', ['CQ DE OK2MTW K', '{VO} DE OK2MTW 599 MARTIN K', '73 SK', 'TEST K'])
        self.assertIsNone(log[-1])

    def test_deterministic_with_seed(self):
        a = self.run_qso('chatty', ['CQ DE OK2MTW K', '{VO} UR 599 K', 'TNX K'], seed=9)[1]
        b = self.run_qso('chatty', ['CQ DE OK2MTW K', '{VO} UR 599 K', 'TNX K'], seed=9)[1]
        self.assertEqual(a, b)


class TimingTest(unittest.TestCase):
    def test_vo_sending_decodes(self):
        rng = random.Random(1)
        for mode in V.VO_MODES:
            vo = V.VirtualOperator(mode=mode, user_call='OK2MTW', rng=rng.random)
            text = vo.reply('CQ CQ DE OK2MTW K')['text']
            for wpm, fwpm in ((18, 18), (25, None), (35, None)):   # (Farnsworth gaps are no human gaps)
                tm = V.vo_timings(text, wpm, fwpm, MORSE)
                tones = [{'start': e['start'], 'end': e['end']} for e in tm['els']]
                r = D.decode_tones(tones, wpm, MORSE, machine=True, dot=1200 / wpm)
                self.assertEqual(V.over_text(r['chars']), text, (wpm, fwpm))

    def test_farnsworth_and_prosigns(self):
        a = V.vo_timings('PARIS PARIS', 20, None, MORSE)
        b = V.vo_timings('PARIS PARIS', 20, 10, MORSE)
        self.assertAlmostEqual(a['end'], 2 * 60000 / 20 / 1 - 7 * 60, delta=1)   # 50 units minus the last word gap
        self.assertGreater(b['end'], a['end'] * 1.5)
        sk = V.vo_timings('SK', 20, None, MORSE)
        self.assertEqual(len(sk['els']), 6)
        self.assertAlmostEqual(sk['els'][3]['start'] - sk['els'][2]['end'], 60)   # one character, no gap of 3
        self.assertEqual({e['word'] for e in V.vo_timings('TU 73', 20, None, MORSE)['els']}, {0, 1})


class PortTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((V.VO_WPM, V.VO_WPM_MIN, V.VO_WPM_MAX, V.VO_QRS), (18, 10, 40, 4))
        self.assertEqual((V.VO_TOPICS_MIN, V.VO_TOPICS_MAX, V.VO_TOPICS_PER_OVER), (2, 4, 2))
        self.assertEqual((V.CONSTS['VO_REPLY_MS'], V.CONSTS['VO_SILENCE_MS']), (1500, 3000))
        self.assertEqual(V.VO_MODES, ['quick', 'chatty'])
        self.assertEqual(V.OVER_ENDS, ['K', 'KN', 'BK', 'SK', 'AR'])
        self.assertEqual(V.PROSIGNS, {'...-.-': 'SK', '-.--.': 'KN', '.-.-.': 'AR', '-...-.-': 'BK'})
        self.assertTrue(all(V.QSO[k] for k in V.QSO))
        self.assertIn('OK', V.VO_PREFIXES)

    def test_looks_like_call(self):
        self.assertTrue(V.looks_like_call('OK2MTW'))
        self.assertTrue(V.looks_like_call('OK2MTW/P'))
        self.assertFalse(V.looks_like_call('TRENER1X'))
        self.assertFalse(V.looks_like_call('MARTIN'))
        self.assertIn('export const looksLikeCall = (s) => CALL_RE.test(s);', V.VO_JS)

    def test_vo_call(self):
        rng = rng_of(7)
        for _ in range(50):
            c = V.vo_call(rng)
            self.assertRegex(c, r'^[A-Z0-9]{1,2}[1-9][A-Z]{2,3}$')
            self.assertTrue(V.CALL_RE.match(c))

    def test_js_fragments(self):
        for frag in ("&& (heard === callSign || (callSign.length >= 4 && editDistance(heard, callSign) <= 1));",
                     "const own = this.topics.filter((tp) => !asks.includes(tp)).slice(0, Math.max(0, VO_TOPICS_PER_OVER - asks.length));",
                     "if ((h.agn || h.qrs || h.qrq) && this.last && !(h.rst || h.name || h.qth || h.asks.length)) {",
                     "if (h.toVo) { this.phase = 'reported'; return this._out(this._say(this._report()), h); }",
                     "if (this.phase === 'cq' && h.from) { this.phase = 'reported'; return this._out(this._say(this._report()), h); }",
                     "return `${this._hdr()} TNX FER QSO${dr} = 73 GL = ${this._hdr()} SK`;",
                     "this._out(this._say(`${this._hdr()} R TNX FER RPRT${dr} = TNX QSO ES 73 GL = ${this._hdr()} SK`), h);",
                     "const ta = (60000 * wpm - 37200 * fwpm) / (wpm * fwpm);",
                     "if (ci || wi) t += cg - u;",
                     "if (asked && VO_TOPICS.includes(p) && !h.asks.includes(p)) h.asks.push(p);",
                     "h.rst = rst && RST_RE.test(rst) ? rst : (plain.find((tk) => RST_RE.test(tk)) || null);"):
            self.assertIn(frag, V.VO_JS)
