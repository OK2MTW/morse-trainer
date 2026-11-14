// SPDX-License-Identifier: EUPL-1.2
// VK D3 (0.11.4, docs/spec-klic.md A-14): evaluation of sending – pure logic, ported to tests/sendeval.py.
// Input = the tones ({start, end, el?} in ms; el missing = keyed by hand) and their decodeTones() result.
// Form (in units = the measured dot length of this attempt): dash:dot ratio (only when hand-keyed elements exist –
// with an iambic keyer it is given by the keyer), gap inside a character (straight key), gap between characters
// (the main habit with paddles), gap between words, tempo stability (robust spread of hand dots and of the gaps
// between characters), speed (character WPM from the dot, effective WPM from the PARIS units of the decoded text).
// Correctness = alignment against the task (align/score from copy.js, as in copy behind).
// Bands are a starting proposal only – to be tuned from data (Martin's consent). Feedback is about the task.
import { align, score } from './copy.js';
import { pools, word, SHARE_LETTERS, SHARE_DIGITS } from './content.js';

export const EVAL_MIN_N = 3;            // a metric needs at least 3 values (dashes, dots, gaps)
export const EVAL_WINDOW = 60;          // free sending on the key page: the last 60 tones
export const EVAL_RATIO = [3, 2.5, 3.5, 2.2, 4];       // target, good low–high, ok low–high
export const EVAL_IN_GAP = [1, 0.7, 1.4, 0.5, 2];
export const EVAL_CHAR_GAP = [3, 2.5, 4, 2, 5];
export const EVAL_WORD_GAP = [7, 5.5, 9, 4.5, 12];
export const EVAL_CV_GOOD = 0.15;        // tempo stability: robust spread ≤ 15 % good, ≤ 25 % ok
export const EVAL_CV_OK = 0.25;
export const EVAL_ACC_GOOD = 0.9;        // correctness ≥ 90 % good, ≥ 75 % ok
export const EVAL_ACC_OK = 0.75;
// D3 step 3 (0.12.0): the sending exercise on the key page (nothing goes to the server – that comes with D4)
export const SEND_KINDS = ['char', 'group', 'word', 'qso'];   // stored in the device settings, not translated
// 0.17.0 D4 sending lessons (A-15): the steps of the ladder and the progress rule (server/sending.py checks the same)
export const SEND_STEPS = ['char', 'group', 'word', 'qso'];
export const SEND_PASS_ACC = 0.9;       // a lesson passes with correctness ≥ 90 % …
export const SEND_PASS_N = 2;           // … two in a row on the current step = the next step
// Z-24 habits of the hand – bands are an estimate only, to be tuned from data (tests/data/key_recordings_hw.json)
export const HABIT_WORD_RATIO = 1.7;    // word gap / character gap below this = word gaps too short (norm 7/3 = 2.33)
export const HABIT_CHAR_LONG = 4;       // character gaps longer than 4 dots
export const HABIT_PADDLE_N = 2;        // ≥ 2 characters with one element more / less = probably the paddle
export const SEND_TASKS = 10;           // tasks in one series
export const SEND_MIN_CHARS = 10;       // characters of the receive level, at least the first 10 in Koch order
export const SEND_GROUP_LEN = 5;        // a group of 5 characters
export const SEND_END_MS = 2000;        // a task ends after silence of 2 s …
export const SEND_END_UNITS = 7;        // … but at least 7 dot lengths (slow sending)
export const SEND_DRILL_NEED = 3;       // 1.1.5 step char: a character repeats until sent right 3× in a row

const DOT = '.';

function median(arr) {
  if (!arr.length) return null;
  const a = [...arr].sort((x, y) => x - y);
  const n = a.length;
  return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
}

/** Robust coefficient of variation: 1.4826 × MAD / median (one odd value does not spoil it). */
export function robustCv(arr) {
  if (arr.length < EVAL_MIN_N) return null;
  const m = median(arr);
  if (!m) return null;
  return (1.4826 * median(arr.map((x) => Math.abs(x - m)))) / m;
}

function band(v, b) {
  if (v >= b[1] && v <= b[2]) return 'good';
  if (v >= b[3] && v <= b[4]) return 'ok';
  return 'bad';
}

/** PARIS units of a text (dot 1, dash 3, 1 inside a character, 3 between characters, 7 between words). */
export function textUnits(codes) {
  let u = 0;
  let prev = null;
  for (const c of codes) {
    if (c === ' ') { prev = ' '; continue; }
    if (prev !== null) u += prev === ' ' ? 7 : 3;
    for (const el of c) u += el === DOT ? 2 : 4;
    u -= 1;
    prev = c;
  }
  return u;
}

/**
 * Raw values of the form of keyed tones (decoded by decodeTones): lengths of dots and dashes, hand-keyed dots, gaps
 * by kind, PARIS units of the decoded text and the duration. A series pools these (sessionSummary).
 */
export function formValues(tones, dec) {
  const len = (i) => tones[i].end - tones[i].start;
  const v = { dots: [], dashes: [], handDots: [], hand: 0, inGaps: [], charGaps: [], wordGaps: [], units: 0, dur: 0,
    dot: dec.dot };
  dec.marks.forEach((el, i) => {
    if (!tones[i].el) v.hand += 1;
    (el === DOT ? v.dots : v.dashes).push(len(i));
    if (el === DOT && !tones[i].el) v.handDots.push(len(i));
  });
  dec.gaps.forEach((kind, i) => {
    if (kind === null) return;
    const g = tones[i].start - tones[i - 1].end;
    if (kind === 0) { if (!tones[i].el && !tones[i - 1].el) v.inGaps.push(g); }
    else if (kind === 1) v.charGaps.push(g);
    else v.wordGaps.push(g);
  });
  if (tones.length && dec.codes.some((c) => c !== ' ')) {
    v.units = textUnits(dec.codes);
    v.dur = tones.at(-1).end - tones[0].start;
  }
  return v;
}

/** Form metrics from raw values (formValues or pooled). Metrics without enough data are null. */
export function metricsFrom(v) {
  const unit = v.dots.length ? median(v.dots) : (v.dashes.length ? median(v.dashes) / 3 : v.dot);
  const m = { unit, charWpm: 1200 / unit, effWpm: null, ratio: null, inGap: null, charGap: null, wordGap: null,
    stability: null };
  if (v.hand && v.dots.length >= EVAL_MIN_N && v.dashes.length >= EVAL_MIN_N) {
    const x = median(v.dashes) / median(v.dots);
    m.ratio = { v: x, st: band(x, EVAL_RATIO) };
  }
  if (v.inGaps.length >= EVAL_MIN_N) {
    const x = median(v.inGaps) / unit;
    m.inGap = { v: x, st: band(x, EVAL_IN_GAP) };
  }
  if (v.charGaps.length >= EVAL_MIN_N) {
    const x = median(v.charGaps) / unit;
    m.charGap = { v: x, st: band(x, EVAL_CHAR_GAP) };
  }
  if (v.wordGaps.length) {
    const x = median(v.wordGaps) / unit;
    m.wordGap = { v: x, st: band(x, EVAL_WORD_GAP) };
  }
  const cvDot = robustCv(v.handDots);
  const cvGap = robustCv(v.charGaps);
  const cvs = [cvDot, cvGap].filter((x) => x !== null);
  if (cvs.length) {
    const x = Math.max(...cvs);
    m.stability = { v: x, dot: cvDot, gap: cvGap, st: x <= EVAL_CV_GOOD ? 'good' : (x <= EVAL_CV_OK ? 'ok' : 'bad') };
  }
  if (v.dur > 0) m.effWpm = (1200 * v.units) / v.dur;
  return m;
}

/** Form metrics of keyed tones (decoded by decodeTones); m.values = the raw values. */
export function sendMetrics(tones, dec) {
  const values = formValues(tones, dec);
  return { ...metricsFrom(values), values };
}

/**
 * Sending of a task: correctness against the target text (spaces do not count) + form metrics.
 * morse = {char: code}. Returns {ops, acc: {ok, sub, del, ins, n, v, st}, subs: [{want, wantCode, got, gotCode}],
 * fixes, metrics}.
 */
export function evaluateSending(target, tones, dec, morse) {
  const sent = [...target.replace(/\s+/g, '')];
  const got = dec.chars.filter((c) => c.ch !== ' ');
  const typed = got.map((c) => c.ch);
  const ops = align(sent, typed);
  const sc = score(ops, sent, typed);
  const v = sc.acc ?? 0;
  const subs = ops.filter((o) => o.op === 'sub').map((o) => ({
    want: sent[o.s], wantCode: morse[sent[o.s]] ?? '', got: typed[o.t], gotCode: got[o.t].code,
  }));
  return {
    ops,
    acc: { ok: sc.ok, sub: sc.sub, del: sc.del, ins: sc.ins, n: sc.n, v,
      st: v >= EVAL_ACC_GOOD ? 'good' : (v >= EVAL_ACC_OK ? 'ok' : 'bad') },
    subs,
    fixes: dec.fixes,
    metrics: sendMetrics(tones, dec),
  };
}

const FORM = [['ratio', EVAL_RATIO], ['inGap', EVAL_IN_GAP], ['charGap', EVAL_CHAR_GAP], ['wordGap', EVAL_WORD_GAP]];

/**
 * The one thing to focus on: a wrong character first (the most frequent confusion), then the form metric furthest
 * from its target (bad before ok; distance in the log domain relative to the ok band), stability last among equals.
 * Returns {key: 'acc'|'ratio'|'inGap'|'charGap'|'wordGap'|'stability'|'good', dir: 'low'|'high'|null, v, sub?}.
 */
export function focusOf(metrics, ev = null) {
  if (ev && ev.acc.st !== 'good' && ev.subs.length) {
    const cnt = {};
    for (const s of ev.subs) { const k = `${s.want}${s.got}`; cnt[k] = (cnt[k] || 0) + 1; }
    const top = ev.subs.reduce((a, s) => (cnt[`${s.want}${s.got}`] > cnt[`${a.want}${a.got}`] ? s : a));
    return { key: 'acc', dir: null, v: ev.acc.v, sub: top };
  }
  const rank = { bad: 2, ok: 1, good: 0 };
  let best = null;
  for (const [key, b] of FORM) {
    const x = metrics[key];
    if (!x || x.st === 'good') continue;
    const dir = x.v < b[0] ? 'low' : 'high';
    const dist = Math.abs(Math.log(x.v / b[0])) / Math.log(dir === 'low' ? b[0] / b[3] : b[4] / b[0]);
    const c = { key, dir, v: x.v, r: rank[x.st], dist };
    if (!best || c.r > best.r || (c.r === best.r && c.dist > best.dist)) best = c;
  }
  const s = metrics.stability;
  if (s && s.st !== 'good') {
    const c = { key: 'stability', dir: 'high', v: s.v, r: rank[s.st], dist: s.v / EVAL_CV_OK };
    if (!best || c.r > best.r) best = c;
  }
  if (!best) return { key: 'good', dir: null, v: null };
  return { key: best.key, dir: best.dir, v: best.v };
}

const pick = (arr, rng) => arr[Math.floor(rng() * arr.length)];

// 0.17.0: sentences of a QSO (step 'qso') – needs all letters and digits in receiving, else words are sent
const QSO_LINES = ['CQ CQ DE {c} {c} K', '{c} DE {m} K', 'UR RST 5{n}9 5{n}9', 'NAME {name} {name}', 'QTH {qth} {qth}',
  'TNX FER QSO 73', 'RIG {p}W ANT DIPOLE', 'WX {wx} TEMP {t}C', 'TNX FER CALL GL', '73 TU {c} DE {m} SK'];
const QSO_PFX = ['OK', 'OL', 'OM', 'DL', 'SP', 'HA', 'OE', 'S5', 'G', 'F', 'I', 'ON'];
const QSO_NAMES = ['PETR', 'JAN', 'EVA', 'TOM', 'ANNA', 'KAREL', 'JIRI', 'HANS', 'MARIE', 'PAVEL'];
const QSO_QTH = ['PRAHA', 'BRNO', 'LIBEREC', 'PLZEN', 'OLOMOUC', 'WIEN', 'DRESDEN', 'KRAKOW', 'ZLIN', 'JIHLAVA'];
const QSO_WX = ['SUNNY', 'CLOUDY', 'RAIN', 'SNOW', 'FOG'];
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const DIGITS = '0123456789';

/** All letters and digits are in the receiving set → the QSO step can be practised. */
export function qsoReady(chars) {
  const have = new Set(chars);
  return [...LETTERS, ...DIGITS].every((c) => have.has(c));
}

/** A call sign: a prefix, a digit, 2–3 letters. */
export function qsoCall(rng) {
  let s = pick(QSO_PFX, rng) + pick([...DIGITS], rng);
  const n = rng() < 0.5 ? 2 : 3;
  for (let i = 0; i < n; i++) s += pick([...LETTERS], rng);
  return s;
}

/** One sentence of a QSO, e.g. 'UR RST 579 579'. */
export function qsoLine(rng) {
  const c = qsoCall(rng);
  const m = qsoCall(rng);
  const v = { c, m, n: String(3 + Math.floor(rng() * 7)), name: pick(QSO_NAMES, rng), qth: pick(QSO_QTH, rng),
    p: String(pick([5, 10, 50, 100], rng)), wx: pick(QSO_WX, rng), t: String(Math.floor(rng() * 30)) };
  return pick(QSO_LINES, rng).replace(/\{(\w+)\}/g, (_, k) => v[k]);
}

/**
 * Z-24: the habits of the hand in a series (metrics + sessionSummary / evaluateSending): word gaps short against the
 * character gaps, long character gaps, one element more / less in a character (probably the paddle). → [{key, v}]
 */
export function handHabits(metrics, ev = null) {
  const out = [];
  const cg = metrics?.charGap?.v;
  const wg = metrics?.wordGap?.v;
  if (cg && wg && wg / cg < HABIT_WORD_RATIO) out.push({ key: 'wordShort', v: wg / cg });
  if (cg && cg > HABIT_CHAR_LONG) out.push({ key: 'charLong', v: cg });
  const n = (ev?.subs || []).filter((x) => oneElement(x.wantCode, x.gotCode)).length;
  if (n >= HABIT_PADDLE_N) out.push({ key: 'paddle', v: n });
  return out;
}

/** b = a with exactly one element added or removed (anywhere). */
export function oneElement(a, b) {
  if (!a || !b || Math.abs(a.length - b.length) !== 1) return false;
  const [l, s] = a.length > b.length ? [a, b] : [b, a];
  for (let i = 0; i < l.length; i++) if (l.slice(0, i) + l.slice(i + 1) === s) return true;
  return false;
}

/**
 * One task: a character (not the same as prev), a group of SEND_GROUP_LEN characters (letters 70 %, digits 20 %,
 * the rest punctuation – as in copy behind), or a word from the mastered letters (pseudo-word when few words fit).
 */
export function sendTask(kind, chars, rng, prev = null) {
  if (kind === 'group') {
    const p = pools(chars);
    let out = '';
    for (let i = 0; i < SEND_GROUP_LEN; i++) {
      const r = rng();
      let pool = r < SHARE_LETTERS ? p.L : r < SHARE_LETTERS + SHARE_DIGITS ? p.D : p.P;
      if (!pool.length) pool = p.L.length ? p.L : chars;
      out += pick(pool, rng);
    }
    return out;
  }
  if (kind === 'qso') return qsoReady(chars) ? qsoLine(rng) : word(chars, rng);
  if (kind === 'word') return word(chars, rng);
  const avail = chars.length > 1 ? chars.filter((c) => c !== prev) : chars;
  return pick(avail, rng);
}

/**
 * 1.1.5 (Martin 2026-11-14): the drill of single characters (step / exercise `char`). All characters of the list in a
 * pseudo-random order (a shuffled bag, a new one every round, not starting with the last character); the app first
 * plays a new character, the student sends it until right SEND_DRILL_NEED times in a row, then the next one comes.
 * One round over all characters = one lesson. record(ok) → 'again' | 'next' | 'round'.
 */
export class CharDrill {
  constructor(chars, rng = Math.random, need = SEND_DRILL_NEED, last = null) {
    this.rng = rng;
    this.need = need;
    this.bag = shuffled([...new Set(chars)], rng, last);
    this.i = 0; this.streak = 0; this.tries = 0; this.attempts = 0; this.ok = 0;
    this.misses = [];   // 1.1.7: [want, got] of the wrong characters (the confusions of the summary)
  }

  get cur() { return this.bag[this.i] ?? null; }
  get done() { return this.i; }
  get total() { return this.bag.length; }

  record(ok, got = null) {
    if (this.cur === null) return 'round';
    this.attempts++;
    this.tries++;
    if (ok) { this.ok++; this.streak++; } else { this.streak = 0; this.misses.push([this.cur, got]); }
    if (this.streak < this.need) return 'again';
    this.i++; this.streak = 0; this.tries = 0;
    return this.i >= this.bag.length ? 'round' : 'next';
  }
}

/**
 * 1.1.7: the summary of a drill round – the form metrics from the attempts (sessionSummary of their evaluations), the
 * correctness and the confusions from the drill: every sent character counted on its own (A A A = three answers).
 */
export function drillSummary(list, drill, morse) {
  const s = sessionSummary(list);
  const n = drill.attempts;
  const v = n ? drill.ok / n : 0;
  s.acc = { ok: drill.ok, sub: n - drill.ok, del: 0, ins: 0, n, v,
    st: v >= EVAL_ACC_GOOD ? 'good' : (v >= EVAL_ACC_OK ? 'ok' : 'bad') };
  const cnt = new Map();
  for (const [want, got] of drill.misses) {
    const k = `${want}>${got ?? '*'}`;
    cnt.set(k, (cnt.get(k) || 0) + 1);
  }
  s.conf = [...cnt].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, c]) => {
    const [want, got] = k.split('>');
    return { want, wantCode: morse[want] ?? '', got, gotCode: morse[got] ?? '', n: c };
  });
  s.subs = drill.misses.map(([want, got]) => ({ want, wantCode: morse[want] ?? '', got, gotCode: morse[got] ?? '' }));
  s.tasks = n;
  return s;
}

/** Fisher–Yates; the first item is not `last` (when there are two or more). */
function shuffled(a, rng, last = null) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  if (a.length > 1 && a[0] === last) [a[0], a[1]] = [a[1], a[0]];
  return a;
}

/**
 * Summary of a series (list of evaluateSending results): correctness over all characters, the 3 most frequent
 * confusions, form metrics from the pooled raw values of all attempts (the same bands); effective speed = the PARIS
 * units of all attempts / their total duration (the pauses between tasks do not count).
 * Returns {acc, subs (all), conf: [{want, wantCode, got, gotCode, n}], fixes, metrics, tasks}.
 */
export function sessionSummary(list) {
  const c = { ok: 0, sub: 0, del: 0, ins: 0, n: 0 };
  const subs = [];
  let fixes = 0;
  for (const ev of list) {
    for (const k of Object.keys(c)) c[k] += ev.acc[k];
    subs.push(...ev.subs);
    fixes += ev.fixes;
  }
  const den = c.n + c.ins;
  const v = den ? c.ok / den : 0;
  const cnt = new Map();
  for (const s of subs) {
    const k = `${s.want}${s.got}`;
    if (!cnt.has(k)) cnt.set(k, { ...s, n: 0 });
    cnt.get(k).n += 1;
  }
  const conf = [...cnt.values()].sort((a, b) => b.n - a.n).slice(0, 3);
  // form: the raw values of all attempts pooled (one short attempt alone has too few elements for a metric)
  const pool = { dots: [], dashes: [], handDots: [], hand: 0, inGaps: [], charGaps: [], wordGaps: [], units: 0, dur: 0,
    dot: null };
  const dotsEst = [];
  for (const ev of list) {
    const fv = ev.metrics.values;
    for (const k of ['dots', 'dashes', 'handDots', 'inGaps', 'charGaps', 'wordGaps']) pool[k].push(...fv[k]);
    pool.hand += fv.hand; pool.units += fv.units; pool.dur += fv.dur;
    dotsEst.push(fv.dot);
  }
  pool.dot = median(dotsEst) ?? 60;
  const metrics = metricsFrom(pool);
  return {
    acc: { ...c, v, st: v >= EVAL_ACC_GOOD ? 'good' : (v >= EVAL_ACC_OK ? 'ok' : 'bad') },
    subs, conf, fixes, metrics, tasks: list.length,
  };
}
