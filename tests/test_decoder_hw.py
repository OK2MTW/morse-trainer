# SPDX-License-Identifier: EUPL-1.2
"""0.14.0 decoder branch for the stream of a HW keyer (docs/hw/klic-rozhrani.md, spec A-11, A-13): elements with
machine timing (±1 ms of USB frames), gaps between characters and words made by a human. Target: 100 % characters."""
import json
import math
import random
import unittest

from tests import decoder as D
from tests.test_decoder import MORSE, CHARS, ROOT, char_accuracy, text_accuracy


def stream(words, wpm, rng, sigma=0.25, jitter=1.0, wpm_of=None):
    """Tones of the HW stream: keyer elements exact (dot = 1200/wpm, dash = 3 dots, gap inside = 1 dot), every edge
    rounded to 1 ms and shifted by ±jitter ms; gaps between characters 3 dots and words 7 dots × lognormal(sigma),
    never shorter than the keyer allows (a human gap ≥ 2.2 dots, a word ≥ 5.5 dots). wpm_of(word index) = speed
    changed on the HW (KEY button) between words."""
    t, out = 0.0, []

    def edge(x):
        return round(x) + rng.uniform(-jitter, jitter)
    for wi, word in enumerate(words):
        u = 1200 / (wpm_of(wi) if wpm_of else wpm)
        for ci, ch in enumerate(word):
            code = MORSE[ch]
            for ei, e in enumerate(code):
                on = u * (3 if e == '-' else 1)
                out.append({'start': edge(t), 'end': edge(t + on)})
                t += on
                if ei < len(code) - 1:
                    t += u
                elif ci < len(word) - 1:
                    t += max(2.2, 3 * math.exp(rng.gauss(0, sigma))) * u
                else:
                    t += max(5.5, 7 * math.exp(rng.gauss(0, sigma))) * u
    return out


def groups(rng, n=6):
    return [''.join(rng.choice(CHARS) for _ in range(5)) for _ in range(n)]


class MachineDecoderTest(unittest.TestCase):
    def test_constants_and_port(self):
        c = D.CONSTS
        self.assertEqual((c['DEC_MACH_SPLIT'], c['DEC_MACH_WIN'], c['DEC_MACH_WORD'], c['DEC_MACH_SEP'], c['DEC_MACH_SD']),
                         (2, 8, 5, 1.3, 0.15))
        self.assertEqual((c['DEC_MACH_LOOK'], c['DEC_MACH_WORD_LO'], c['DEC_MACH_WORD_HI'], c['DEC_MACH_GAPS'],
                          c['DEC_MACH_MIN'], c['DEC_MACH_IN_N'], c['DEC_MACH_IN_LO'], c['DEC_MACH_IN_HI']),
                         (6, 5, 9, 24, 6, 3, 0.5, 1.5))
        for frag in ('export function machineDot(lens, gaps, hint) {', 'const m = apart(split(lens), DEC_MACH_SPLIT);',
                     'if (gaps.length && Math.min(...gaps) < md / DEC_MACH_SPLIT) return md / 3;',
                     'return md < DEC_MACH_SPLIT * hint ? md : md / 3;',
                     'const m1 = Math.min(lens.length, i + DEC_MACH_LOOK + 1);', 'const m0 = Math.max(0, m1 - n);',
                     'u = machineDot(lens.slice(m0, m1), gms.slice(m0, m1 - 1), u);',
                     'return { ...tn, el: lens[i] < DEC_MACH_SPLIT * u ? DOT : DASH, u, g: innerGap(gms.slice(m0, m1 - 1), u) };',
                     'const g = gaps.filter((x) => x < DEC_MACH_SPLIT * u);', 'if (g.length < DEC_MACH_IN_N) return u;',
                     'return Math.min(DEC_MACH_IN_HI * u, Math.max(DEC_MACH_IN_LO * u, median(g)));',
                     'if (ms < DEC_MACH_SPLIT * u) return 0;', 'return ms < word * u ? 1 : 2;',
                     'if (units.length < DEC_MACH_MIN) return fb;',
                     'let a = Math.log(3);', 'let b = Math.log(7);', 'for (let k = 0; k < 15; k++) {',
                     'A = h.filter((x) => Math.abs(x - a) <= Math.abs(x - b));',
                     'B = h.filter((x) => Math.abs(x - a) > Math.abs(x - b));',
                     'if (A.length < 2 || !B.length || b - a < Math.log(DEC_MACH_SEP)) return fb;',
                     'const s2 = Math.max((sqDev(A, a) + sqDev(B, b)) / h.length, DEC_MACH_SD ** 2);',
                     'const w = Math.exp((a + b) / 2 + (s2 * Math.log(A.length / B.length)) / (b - a));',
                     'return Math.min(DEC_MACH_WORD_HI, Math.max(DEC_MACH_WORD_LO, w));',
                     'if (machine) tones = machineTones(tones, opts.dot || 1200 / wpm);',
                     'const tu = (tn.u + tones[i - 1].u) / 2;', 'const g = (tn.g + tones[i - 1].g) / 2;',
                     'const u = (tu + g) / 2;', 'const x = (ms + (tu - g) / 2) / u;',
                     'const word = machineWordGap(human.slice(-DEC_MACH_GAPS), opts.word || DEC_MACH_WORD);',
                     'kind = st.gap(ms, gm ? gm.kinds[i] : machineGapKind(x, 1, word));', 'if (x >= DEC_MACH_SPLIT) human.push(x);',
                     'if (machine) { units.push(null); words.push(null); }',
                     'chars, marks, gaps, fixes, units, words,'):
            self.assertIn(frag, D.DECODER_JS)

    def test_example_of_the_interface_doc(self):
        # klic-rozhrani.md 6.3: A = down 0, up 60, down 120, up 300; N = down 0, up 180, down 240, up 300
        a = [{'start': 0, 'end': 60}, {'start': 120, 'end': 300}]
        n = [{'start': 480, 'end': 660}, {'start': 720, 'end': 780}]   # a human gap of 3 dots after A
        r = D.decode_tones(a + n, 18, MORSE, machine=True, dot=60)
        self.assertEqual(r['text'], 'AN')
        self.assertEqual([t['el'] for t in r['tones']], ['.', '-', '-', '.'])

    def test_cw_peer_times_of_an_over(self):
        # 0.15.3: the CW Chat decodes the other station with machine timing from the times of its over (ms from its
        # first key down, rounded to 1 ms like cwlink.js TxOver.add), without the hint of its dot (unknown speed)
        for wpm in (16, 25, 40):
            rng = random.Random(100 + wpm)
            for _ in range(5):
                words = groups(rng, 4)
                tones = stream(words, wpm, rng)
                t0, prev, els = tones[0]['start'], 0, []
                for tn in tones:
                    s = max(prev, round(tn['start'] - t0))
                    prev = round(tn['end'] - t0)
                    els.append({'start': s, 'end': prev})
                r = D.decode_tones(els, 18, MORSE, machine=True)
                self.assertEqual(r['text'].replace(' ', ''), ''.join(words), wpm)

    def test_all_speeds_100_percent_characters(self):
        for wpm in (20, 30, 40, 50, 60):
            rng = random.Random(wpm)
            for _ in range(15):
                words = groups(rng)
                r = D.decode_tones(stream(words, wpm, rng), 18, MORSE, machine=True)
                self.assertEqual(r['text'].replace(' ', ''), ''.join(words), wpm)
                self.assertAlmostEqual(r['wpm'], wpm, delta=0.04 * wpm)

    def test_word_gaps(self):
        total, n = 0, 0
        for wpm in (20, 40, 60):
            rng = random.Random(100 + wpm)
            for _ in range(10):
                words = groups(rng)
                r = D.decode_tones(stream(words, wpm, rng, sigma=0.2), 18, MORSE, machine=True)
                total += text_accuracy(' '.join(words), r['text'])
                n += 1
        self.assertGreaterEqual(total / n, 0.97)   # human gaps overlap (3 vs 7 dots, spread 20 %)

    def test_hint_does_not_matter_with_context(self):
        rng = random.Random(8)
        words = ['PARIS', 'CQ', 'TEST', 'OK2MTW']
        for wpm in (20, 60):
            for hint in (20, 60, 100):
                r = D.decode_tones(stream(words, wpm, rng, sigma=0.1), 18, MORSE, machine=True, dot=hint)
                self.assertEqual(r['text'], 'PARIS CQ TEST OK2MTW', (wpm, hint))

    def test_single_characters(self):
        # one group of lengths: dashes are told by the gap inside the character; one-element characters by the hint
        rng = random.Random(3)
        for ch in ('5', 'H', 'S', '0', 'O', 'M', 'A', 'N', 'E', 'T'):
            for wpm in (20, 60):
                r = D.decode_tones(stream([ch], wpm, rng), 18, MORSE, machine=True, dot=1200 / wpm)
                self.assertEqual(r['text'], ch, (ch, wpm))
        for ch in ('0', 'O', 'M'):    # dashes known from the gap even with a wrong hint
            r = D.decode_tones(stream([ch], 20, rng), 18, MORSE, machine=True, dot=180)
            self.assertEqual(r['text'], ch)

    def test_speed_changed_on_the_hw(self):
        rng = random.Random(11)
        speeds = [20, 30, 40, 50, 60, 20]
        words = groups(rng, 36)
        r = D.decode_tones(stream(words, 0, rng, wpm_of=lambda i: speeds[i // 6]), 18, MORSE, machine=True)
        self.assertGreaterEqual(char_accuracy(' '.join(words), r['text']), 0.97)

    def test_evaluation_without_hand_metrics(self):
        # A-14: a HW keyer – no dash:dot ratio, no gap inside characters and no spread of elements (the machine makes
        # them); correctness, gaps between characters / words and tempo stay
        from tests import sendeval as E
        rng = random.Random(21)
        words = groups(rng)
        dec = D.decode_tones(stream(words, 30, rng), 18, MORSE, machine=True)
        ev = E.evaluate_sending(' '.join(words), dec['tones'], dec, MORSE)
        m = ev['metrics']
        self.assertEqual(ev['acc']['v'], 1)
        self.assertIsNone(m['ratio'])
        self.assertIsNone(m['inGap'])
        self.assertIsNotNone(m['charGap'])
        self.assertIsNone(m['stability']['dot'])
        self.assertAlmostEqual(m['charWpm'], 30, delta=1.5)
        self.assertIn(E.focus_of(m, ev)['key'], ('good', 'charGap', 'wordGap', 'stability'))

    def test_hand_decoder_unchanged_without_machine(self):
        rng = random.Random(5)
        tones = stream(['PARIS'], 20, rng)
        r = D.decode_tones(tones, 20, MORSE)
        self.assertIs(r['tones'], tones)
        self.assertNotIn('el', tones[0])


if __name__ == '__main__':
    unittest.main()


FIX = '.' * 7


def hand(seq, wpm, rng, cg=3.0, wg=7.0, sigma=0.2, late=0.0, wpm_at=None):
    """0.15.4: a HW stream from [(code, after)] – after 1 = a gap between characters, 2 = words (human, lognormal
    around cg / wg dots, never under 2.1); late = ms by which every key-up event comes late (tones longer, gaps
    shorter); wpm_at(index of the code) = speed changed on the HW."""
    t, out = 0.0, []
    for k, (code, after) in enumerate(seq):
        u = 1200 / (wpm_at(k) if wpm_at else wpm)
        for ei, e in enumerate(code):
            on = u * (3 if e == '-' else 1)
            out.append({'start': round(t), 'end': round(t + on + late)})
            t += on
            if ei < len(code) - 1:
                t += u
        t += max(2.1, (cg if after == 1 else wg) * math.exp(rng.gauss(0, sigma))) * u
    return out


def build(text):
    """Words of the text; '#' = the error sign after a word gap, '#c' = right after the word (a gap between
    characters)."""
    seq = []
    for w in text.split(' '):
        if w in ('#', '#c'):
            if w == '#c':
                seq[-1] = (seq[-1][0], 1)
            seq.append((FIX, 2))
            continue
        seq += [(MORSE[c], 1 if i < len(w) - 1 else 2) for i, c in enumerate(w)]
    return seq


class SendingHandTest(unittest.TestCase):
    """0.15.4 (Martin 2026-11-12: gaps between letters / words are read badly, an erased word comes back with the
    next sending): decoding the growing record again and again, late key events, the error sign of 7 dots (0.16.1)."""

    def decode(self, tones, wpm):
        return D.decode_tones(tones, 18, MORSE, machine=True, dot=1200 / wpm)

    def test_erased_word_never_comes_back(self):
        # before 0.15.4 the word threshold came from all gaps of the record and the dot from 8 tones ahead: with
        # gaps of a hurried hand (letters ~4, words ~5.5 dots) the erased call came back in 2 of 15 runs
        txt = 'CQ DE OK2MTW K UR RST 599 OK2XYZ #c NAME IS MARTIN QTH LIBEREC'
        for cg, wg in ((3, 7), (3.6, 5.8), (4, 5.5)):
            for seed in range(8):
                rng = random.Random(seed)
                wpm = rng.choice([18, 22, 25, 30])
                seq = build(txt)
                tones = hand(seq, wpm, rng, cg, wg, 0.25)
                k = [i for i, s in enumerate(seq) if s[0] == FIX][0]
                n0 = sum(len(s[0]) for s in seq[:k + 1])
                for n in range(n0 + 1, len(tones) + 1, 3):
                    text = self.decode(tones[:n], wpm)['text']
                    self.assertNotIn('XYZ', text, (cg, wg, seed, n))
                    self.assertIn('599', text.replace(' ', ''), (cg, wg, seed, n))

    def test_older_decisions_are_final(self):
        # the gaps and elements of tone i do not change once DEC_MACH_LOOK more tones have come
        rng = random.Random(4)
        tones = hand(build('CQ CQ DE OK2MTW OK2MTW PSE K'), 25, rng, 3.5, 6, 0.25)
        full = self.decode(tones, 25)
        for n in range(4, len(tones), 5):
            r = self.decode(tones[:n], 25)
            m = max(0, n - D.MACH_LOOK)
            self.assertEqual(r['gaps'][:m], full['gaps'][:m], n)
            self.assertEqual([t['el'] for t in r['tones'][:m]], [t['el'] for t in full['tones'][:m]], n)

    def test_error_sign_seven_dots(self):
        rng = random.Random(1)
        for txt, want in (('CQ DE OK2XYZ # OK2MTW K', 'CQ DE OK2MTW K'), ('CQ DE OK2XYZ #c OK2MTW K', 'CQ DE OK2MTW K'),
                          ('TEST # #', ''), ('UR RST 5NN #c 599', 'UR RST 599')):
            r = self.decode(hand(build(txt), 22, rng, sigma=0.1), 22)
            self.assertEqual(r['text'], want, txt)
        five = [(MORSE['C'], 2), ('.....', 2), (MORSE['Q'], 2)]   # 5 dots = the digit 5
        self.assertEqual(self.decode(hand(five, 22, rng, sigma=0.1), 22)['text'], 'C 5 Q')
        six = [(MORSE['C'], 2), (MORSE['Q'], 2), ('......', 2), (MORSE['K'], 2)]   # 6 dots erase nothing (0.16.1)
        self.assertTrue(self.decode(hand(six, 22, rng, sigma=0.1), 22)['text'].startswith('C Q '))

    def test_late_key_events(self):
        # a key-up event that comes 8–15 ms late made every gap look shorter: before 0.15.4 not one of 20 texts
        # had the right characters at 8 ms (whole words merged); the gap inside a character now measures the shift
        words = 'CQ DE OK2MTW UR RST 599 NAME IS MARTIN QTH LIBEREC TNX FER QSO 73 SK'.split()
        for late in (-8, 8, 15):
            ok, acc = 0, 0
            for seed in range(10):
                rng = random.Random(seed)
                wpm = rng.choice([20, 25, 30])
                ws = words[:]
                rng.shuffle(ws)
                r = self.decode(hand(build(' '.join(ws)), wpm, rng, late=late), wpm)
                ok += r['text'].replace(' ', '') == ''.join(ws)
                acc += text_accuracy(' '.join(ws), r['text'])
            self.assertGreaterEqual(ok, 9, late)
            self.assertGreaterEqual(acc / 10, 0.97, late)

    def test_diagnostics_units_and_thresholds(self):
        rng = random.Random(2)
        tones = hand(build('PARIS PARIS'), 20, rng, sigma=0.0)
        r = self.decode(tones, 20)
        self.assertEqual(r['text'], 'PARIS PARIS')
        self.assertEqual(len(r['units']), len(tones))
        self.assertIsNone(r['units'][0])
        self.assertIsNone(r['words'][0])
        for x, k, w in zip(r['units'][1:], r['gaps'][1:], r['words'][1:]):
            self.assertAlmostEqual(x, {0: 1, 1: 3, 2: 7}[k], delta=0.1)
            self.assertTrue(D.MACH_WORD_LO <= w <= D.MACH_WORD_HI)

    def test_simulated_hand_criterion(self):
        # the criterion of 0.15.4 (requirements): a hand with gaps 3 / 7 dots ± 20 %, speed changed on the HW,
        # between words, late events up to 10 ms, error signs in different places → ≥ 98 % characters, ≥ 96 % text
        # (the rest are gaps of the simulated hand right at a threshold; the old decoder: 92 % / 92 % with late events)
        words = 'CQ DE OK2MTW UR RST 599 NAME IS MARTIN QTH LIBEREC RIG ANT DIPOLE WX SUNNY TNX QSO 73'.split()
        acc_c, acc_t = 0, 0
        for seed in range(12):
            rng = random.Random(50 + seed)
            ws = words[:]
            rng.shuffle(ws)
            first = build(' '.join(ws[:6] + ['OK2XYZ', '#c'] + ws[6:10]))   # the speed changed between words
            seq = first + build(' '.join(ws[10:12] + ['TEST', '#'] + ws[12:]))
            want = ' '.join(ws)
            speeds = rng.sample([18, 22, 25, 28, 32], 2)
            tones = hand(seq, 0, rng, late=rng.uniform(0, 10), wpm_at=lambda k: speeds[k >= len(first)])
            r = self.decode(tones, speeds[0])
            acc_c += char_accuracy(want, r['text'])
            acc_t += text_accuracy(want, r['text'])
        self.assertGreaterEqual(acc_c / 12, 0.98)
        self.assertGreaterEqual(acc_t / 12, 0.96)

    def test_gap_diagnostics(self):
        # the key page "How the decoder reads": the last 3 words gap by gap, close gaps marked
        rng = random.Random(5)
        seq = build('CQ DE OK2MTW K')
        tones = hand(seq, 25, rng, sigma=0.0)
        r = self.decode(tones, 25)
        d = D.gap_diagnostics(r, MORSE)
        self.assertEqual(''.join(x['ch'] for x in d['rows']), 'DEOK2MTWK')
        self.assertEqual([x['kind'] for x in d['rows']][:3], [2, 1, 2])
        self.assertAlmostEqual(d['dot'], 48, delta=1)
        self.assertAlmostEqual(d['wpm'], 25, delta=0.5)
        self.assertFalse(any(x['close'] or x['in_close'] for x in d['rows']))
        self.assertAlmostEqual(d['rows'][0]['in_max'], 1, delta=0.1)   # D -..
        self.assertIsNone(d['rows'][1]['in_max'])                       # E .
        # a gap of 4.9 dots before the last word is close to the word threshold; the error sign is ''
        seq = build('PARIS PARIS #c TEST')
        t = hand(seq, 20, rng, sigma=0.0)
        r = self.decode(t, 20)
        d = D.gap_diagnostics(r, MORSE)
        self.assertIn('', [x['ch'] for x in d['rows']])
        self.assertEqual(r['text'], 'PARIS TEST')
        self.assertIsNone(D.gap_diagnostics(self.decode([], 20), MORSE))
        for frag in ('export function gapDiagnostics(dec, morse, nWords = DEC_DIAG_WORDS) {',
                     'if (gaps[i] === 2 && ++seen >= nWords) { start = i; break; }',
                     'if (row.before !== null) row.close = near(row.before, DEC_MACH_SPLIT) || near(row.before, row.word);',
                     'row.inClose = near(row.inMax, DEC_MACH_SPLIT);', 'const dot = (last.u + last.g) / 2;',
                     "for (const r of rows) r.ch = fix.test(r.code) ? '' : (byCode[r.code] ?? null);"):
            self.assertIn(frag, D.DECODER_JS)
        self.assertEqual((D.CONSTS['DEC_DIAG_WORDS'], D.CONSTS['DEC_DIAG_NEAR']), (3, 1.15))

    def test_real_hw_recordings(self):
        # 0.16.3: Martin's hand on the HW key (2026-11-12, 20 WPM): gaps between characters 2.7–7 dots, words 9–17;
        # with the word threshold within 5–7 "C Q", "OK2 MTW", "P SE" were torn apart. The threshold may now go up to
        # 9 and the device remembers it (opts.word) → the next record starts with the hand's threshold, not 5 dots
        # (a fixed start of 6 would merge the first words of a norm hand in short overs: 122 of 300 vs 15 at 5).
        # The paddle errors (a missing / extra dot) stay – the decoder reads what was keyed ('keyed').
        data = json.loads((ROOT / 'tests/data/key_recordings_hw.json').read_text(encoding='utf-8'))['recordings']
        tones = [[{'start': s, 'end': e} for s, e in r['tones']] for r in data]
        first = D.decode_tones(tones[0], 20, MORSE, machine=True, dot=60)
        self.assertEqual(first['text'], 'CQ CQ C * DE OK2MTW OKJMTW PSE K')   # no hint yet: the very start is torn
        learned = D.learned_word_gap(first)
        self.assertGreaterEqual(learned, 7)
        for r, tn in zip(data, tones):
            self.assertEqual(D.decode_tones(tn, r['wpm'], MORSE, machine=True, dot=60, word=learned)['text'], r['keyed'])

    def test_word_hint_and_norm_hand(self):
        # a norm hand (3 / 7 dots) learns about 5 dots; a remembered hint only rules until 6 human gaps are known
        rng = random.Random(7)
        words = 'CQ DE OK2MTW UR RST 599 NAME IS MARTIN QTH LIBEREC TNX'.split()
        r = self.decode(hand(build(' '.join(words)), 22, rng, sigma=0.15), 22)
        self.assertLessEqual(D.learned_word_gap(r), 6)
        self.assertIsNone(D.learned_word_gap(self.decode(hand(build('CQ CQ'), 22, rng), 22)))
        self.assertIsNone(D.learned_word_gap({}))
        tones = hand(build(' '.join(words)), 22, random.Random(8), sigma=0.15)
        with_hint = D.decode_tones(tones, 18, MORSE, machine=True, dot=1200 / 22, word=9)
        # another hand on a device that learned 9 dots: only the first words may merge, then its own threshold rules
        self.assertTrue(with_hint['text'].endswith(' '.join(words[3:])), with_hint['text'])
        self.assertEqual(with_hint['text'].replace(' ', ''), ''.join(words))
        self.assertEqual(D.machine_word_gap([3] * 5, 12), D.MACH_WORD_HI)   # a hint is kept within LO–HI
        self.assertEqual(D.machine_word_gap([3] * 5, 2), D.MACH_WORD_LO)
        for frag in ('export function learnedWordGap(dec) {', 'return machineWordGap(h.slice(-DEC_MACH_GAPS), null);',
                     'const fb = start === null ? null : Math.min(DEC_MACH_WORD_HI, Math.max(DEC_MACH_WORD_LO, start));',
                     "const WORD_STORE = 'morse.dec.word';", 'return w >= DEC_MACH_WORD_LO && w <= DEC_MACH_WORD_HI ? w : undefined;'):
            self.assertIn(frag, D.DECODER_JS)
