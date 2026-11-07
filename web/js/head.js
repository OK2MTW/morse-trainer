// SPDX-License-Identifier: EUPL-1.2
// U6 head copy (0.10.14) – pure logic without DOM: one transmission (over) of a QSO with its key data, questions about
// it and checking of written answers. Python port: tests/head.py (tests check that the templates and constants match).
import { qsoValues, fillQso, fitsChars } from './content.js';

export const HEAD_Q = 3; // questions after every transmission

// One over of a QSO. from/to = which call sends / is called ({A} or {B}); fields = data a question may ask about.
// Single mentions (no "RST 579 579") – in the head the operator gets it once, like a fast real QSO.
export const HEAD_TEMPLATES = [
  { text: 'CQ CQ DE {A} {A} = OP {NAME} QTH {QTH} = PSE K', from: 'A', fields: ['NAME', 'QTH'] },
  { text: '{B} DE {A} GM TNX FER CALL = UR RST {RST} = NAME {NAME} = QTH {QTH} = HW? {B} DE {A} KN', from: 'A', to: 'B', fields: ['RST', 'NAME', 'QTH'] },
  { text: '{B} DE {A} GE OM = UR {RST} {RST} = OP {NAME} = QTH {QTH} = {B} DE {A} KN', from: 'A', to: 'B', fields: ['RST', 'NAME', 'QTH'] },
  { text: '{A} DE {B} R FB = UR RST {RST} = NAME {NAME} = QTH {QTH} = RIG {RIG} PWR {PWR}W ANT {ANT} = {A} DE {B} K', from: 'B', to: 'A', fields: ['RST', 'NAME', 'QTH', 'RIG', 'PWR', 'ANT'] },
  { text: '{A} DE {B} R TNX = RIG {RIG} ES ANT {ANT} = PWR {PWR}W = WX {WX} TEMP {TEMP}C = {A} DE {B} KN', from: 'B', to: 'A', fields: ['RIG', 'ANT', 'PWR', 'WX', 'TEMP'] },
  { text: '{B} DE {A} R = WX {WX} ES {TEMP}C = PWR {PWR}W = TNX QSO 73 = {B} DE {A} SK', from: 'A', to: 'B', fields: ['WX', 'TEMP', 'PWR'] },
];
export const HEAD_FIELDS = ['from', 'to', 'RST', 'NAME', 'QTH', 'RIG', 'PWR', 'ANT', 'WX', 'TEMP']; // = server api.py HEAD_FIELDS

/** Answer normalisation: letters/digits only, upper case; a unit after power/temperature (100W, 12C) is optional. */
export function normalize(key, s) {
  let v = String(s ?? '').toUpperCase().replace(/[^A-Z0-9/?]/g, '');
  if (key === 'PWR') v = v.replace(/W$/, '');
  if (key === 'TEMP') v = v.replace(/C$/, '');
  return v;
}

export const isCorrect = (key, answer, expected) => normalize(key, answer) !== '' && normalize(key, answer) === normalize(key, expected);

/**
 * One transmission from mastered characters: {text, items (words), answers {key: value}, questions [key…]} or null.
 * The questions are HEAD_Q different keys, the sending call among them about every second time.
 */
export function makeHeadQso(chars, rng = Math.random) {
  for (let guard = 0; guard < 20; guard++) {
    const v = qsoValues(chars, rng);
    const fits = HEAD_TEMPLATES.filter((tp) => fitsChars(fillQso(tp.text, v), chars));
    if (!fits.length) continue;
    const tp = fits[Math.floor(rng() * fits.length)];
    const answers = { from: v[tp.from] };
    if (tp.to) answers.to = v[tp.to];
    for (const f of tp.fields) answers[f] = v[f];
    const keys = Object.keys(answers);
    for (let i = keys.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [keys[i], keys[j]] = [keys[j], keys[i]]; }
    const qs = keys.slice(0, HEAD_Q);
    if (!qs.includes('from') && rng() < 0.5) qs[0] = 'from';
    const text = fillQso(tp.text, v);
    return { text, items: text.split(' '), answers, questions: qs };
  }
  return null;
}

/** Scores answers {key: written} of one transmission → {n, ok, res: [{key, answer, expected, ok}]}. */
export function scoreHead(qso, written) {
  const res = qso.questions.map((key) => ({ key, answer: written[key] ?? '', expected: qso.answers[key],
    ok: isCorrect(key, written[key], qso.answers[key]) }));
  return { n: res.length, ok: res.filter((r) => r.ok).length, res };
}

/** Lesson summary from rounds [{sc}] → detail.head (without step/wpm/band – added by the caller). */
export function headSummary(rounds) {
  const fields = {};
  let n = 0;
  let ok = 0;
  for (const r of rounds) {
    for (const x of r.sc.res) {
      const f = fields[x.key] || (fields[x.key] = [0, 0]);
      f[0]++;
      if (x.ok) f[1]++;
    }
    n += r.sc.n;
    ok += r.sc.ok;
  }
  return { q: n, ok, acc: n ? ok / n : null, rounds: rounds.length, fields };
}
