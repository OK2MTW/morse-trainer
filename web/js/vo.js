// SPDX-License-Identifier: EUPL-1.2
// 0.16.0 – the virtual operator (VO) of the CW room: a QSO partner that runs in the browser only (no server, nothing
// stored). A state machine with templates – no AI. It reads what the decoder made of the user's over (tolerant: call
// signs with one mistake, RST patterns, NAME / QTH, AGN / QRS / QRQ), answers in one of two modes and plays through
// the band of the room (voui.js). It never keys the HW (H-21). Python port: tests/vo.py.
import { QSO_NAMES, QSO_QTH, QSO_WX, QSO_RIG, QSO_ANT, QSO_PWR } from './content.js';

export const VO_MODES = ['quick', 'chatty'];  // quick QSO / ragchew (topics)
export const VO_REPLY_MS = 1500;   // the VO answers 1.5 s after an over that ended with K / KN / BK / SK / AR …
export const VO_SILENCE_MS = 3000; // … or after 3 s of silence without such an end
export const VO_WPM = 18;          // the default speed (the UI starts at the speed of the user's key)
export const VO_WPM_MIN = 10;
export const VO_WPM_MAX = 40;
export const VO_QRS = 4;           // QRS / QRQ: −/+ 4 WPM
export const VO_TOPICS_MIN = 2;    // ragchew: 2–4 topics of the VO …
export const VO_TOPICS_MAX = 4;
export const VO_TOPICS_PER_OVER = 2; // … at most 2 in one over
export const VO_TOPICS = ['RIG', 'ANT', 'PWR', 'WX', 'AGE', 'QSL'];
export const OVER_ENDS = ['K', 'KN', 'BK', 'SK', 'AR'];
// prosigns keyed as one character (the decoder gives their code; KN and AR are also '(' and '+' of the ITU set)
export const PROSIGNS = { '...-.-': 'SK', '-.--.': 'KN', '.-.-.': 'AR', '-...-.-': 'BK' };
const PROSIGN_CODES = Object.fromEntries(Object.entries(PROSIGNS).map(([c, p]) => [p, c]));
// call signs of the VO: European prefixes, a digit, 2–3 letters (OK1ABC, DL4XY, S52QW)
export const VO_PREFIXES = ['OK', 'OK', 'OL', 'OM', 'DL', 'DK', 'SP', 'HA', 'OE', 'S5', '9A', 'G', 'F', 'I', 'ON', 'PA', 'LY', 'YL', 'ES', 'SM'];
const LETTERS = [...'ABCDEFGHIJKLMNOPRSTUVWXYZ'];
const FILLER = ['IS', 'HR', 'NR', 'OP', 'ES'];
const RST_RE = /^[1-5][1-9N][1-9N]$/;
const CALL_RE = /^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{3,7}(\/[A-Z0-9]{1,3})?$/;

const pick = (list, rng) => list[Math.floor(rng() * list.length)];

/** A nickname that looks like a call sign (a suggestion of the user's call). */
export const looksLikeCall = (s) => CALL_RE.test(s);

/** Edit distance (Levenshtein) of two strings. */
export function editDistance(a, b) {
  const d = Array.from({ length: b.length + 1 }, (_, k) => k);
  for (let i = 1; i <= a.length; i++) {
    let p = d[0];
    d[0] = i;
    for (let k = 1; k <= b.length; k++) {
      const q = d[k];
      d[k] = Math.min(d[k] + 1, d[k - 1] + 1, p + (a[i - 1] !== b[k - 1] ? 1 : 0));
      p = q;
    }
  }
  return d[b.length];
}

/** A heard token is the call sign: equal, or one mistake in a call of 4+ characters. */
export const sameCall = (heard, callSign) => !!heard && !!callSign
  && (heard === callSign || (callSign.length >= 4 && editDistance(heard, callSign) <= 1));

/** Text of a decoded over (decodeTones chars) with prosigns as words: SK, KN, AR, BK. */
export function overText(chars) {
  let out = '';
  for (const c of chars) out += PROSIGNS[c.code] ? ` ${PROSIGNS[c.code]} ` : c.ch;
  return out.replace(/\s+/g, ' ').trim();
}

/** The over is finished by its last word: K, KN, BK, SK, AR. */
export const overEnded = (text) => OVER_ENDS.includes(text.trim().split(/\s+/).at(-1));

/** A call sign of the VO. */
export function voCall(rng = Math.random) {
  let out = pick(VO_PREFIXES, rng) + String(1 + Math.floor(rng() * 9));
  const n = 2 + Math.floor(rng() * 2);
  for (let i = 0; i < n; i++) out += pick(LETTERS, rng);
  return out;
}

/** A new persona of the VO: call sign, name, QTH and the topics of a ragchew. */
export function persona(rng = Math.random, year = 2026) {
  const years = 1 + Math.floor(rng() * 50);
  return {
    call: voCall(rng), name: pick(QSO_NAMES, rng), qth: pick(QSO_QTH, rng), rig: pick(QSO_RIG, rng),
    ant: pick(QSO_ANT, rng), pwr: pick(QSO_PWR, rng), wx: pick(QSO_WX, rng), temp: String(Math.floor(rng() * 25)),
    age: String(Math.max(18 + years, 20 + Math.floor(rng() * 60))), since: String(year - years),
    qsl: pick(['BURO', 'LOTW', 'EQSL'], rng), rst: pick(['599', '579', '589', '5NN'], rng),
  };
}

/** One topic of the VO as a line of its over. */
export function topicLine(topic, p) {
  switch (topic) {
    case 'RIG': return `RIG HR ${p.rig}`;
    case 'ANT': return `ANT ${p.ant}`;
    case 'PWR': return `PWR ${p.pwr}W`;
    case 'WX': return `WX ${p.wx} TEMP ${p.temp}C`;
    case 'AGE': return `AGE ${p.age} ES HAM SINCE ${p.since}`;
    default: return `QSL VIA ${p.qsl}`;
  }
}

const token = (tk) => tk.replace(/\?+$/, '');
/** The value after a keyword (NAME / QTH / RST / UR), fillers like IS / HR skipped. */
function after(tokens, keys) {
  for (let i = 0; i < tokens.length; i++) {
    if (!keys.includes(token(tokens[i]))) continue;
    let k = i + 1;
    while (k < tokens.length && FILLER.includes(tokens[k])) k++;
    if (k < tokens.length && !tokens[k].endsWith('?') && tokens[k] !== '=') return tokens[k];
  }
  return null;
}

/**
 * What the VO heard in one over (tokens of overText): {cq, toVo, from (the call after DE), rst, name, qth, agn, qrs,
 * qrq, asks: [topics], bye (73 / SK / TU), end (over end word), empty}.
 */
export function hear(text, voCall, userCall = '') {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  const plain = tokens.map(token);
  const h = {
    cq: plain.includes('CQ'), toVo: tokens.some((tk) => sameCall(token(tk), voCall)), from: null, rst: null,
    name: null, qth: null, agn: false, qrs: false, qrq: false, asks: [], bye: false, end: overEnded(text),
    empty: !tokens.length,
  };
  const de = plain.indexOf('DE');
  if (de >= 0 && de + 1 < plain.length && CALL_RE.test(plain[de + 1])) h.from = plain[de + 1];
  if (!h.from && userCall) h.from = plain.find((tk) => sameCall(tk, userCall)) || null;
  if (!h.from) h.from = plain.find((tk) => CALL_RE.test(tk) && !sameCall(tk, voCall) && !RST_RE.test(tk)) || null;
  const rst = after(tokens, ['RST', 'UR']);
  h.rst = rst && RST_RE.test(rst) ? rst : (plain.find((tk) => RST_RE.test(tk)) || null);
  h.name = after(tokens, ['NAME', 'OP']);
  h.qth = after(tokens, ['QTH']);
  for (let i = 0; i < tokens.length; i++) {
    const tk = tokens[i];
    const p = plain[i];
    if (tk === '?' || p === 'AGN' || p === 'RPT') h.agn = true;
    if (p === 'QRS') h.qrs = true;
    if (p === 'QRQ') h.qrq = true;
    const asked = tk.endsWith('?') || tokens[i + 1] === '?';
    if (asked && VO_TOPICS.includes(p) && !h.asks.includes(p)) h.asks.push(p);
    if (p === '73' || p === 'SK' || p === 'GB') h.bye = true;
  }
  return h;
}

/** The greeting by the hour: GM before 12, GA before 18, else GE. */
export const greeting = (hour) => (hour < 12 ? 'GM' : (hour < 18 ? 'GA' : 'GE'));

/**
 * The VO of one connection. opts = {mode, userCall, rng, hour, year, wpm}. reply(text) takes the decoded over of the
 * user (overText) and returns {text (null = the VO keeps silent), heard, phase, done, wpm}; cq() makes the VO call CQ.
 */
export class VirtualOperator {
  constructor(opts = {}) {
    this.mode = VO_MODES.includes(opts.mode) ? opts.mode : 'quick';
    this.rng = opts.rng || Math.random;
    this.p = persona(this.rng, opts.year || 2026);
    this.hour = opts.hour ?? 12;
    this.user = opts.userCall || '';
    this.userName = null;
    this.wpm = opts.wpm || VO_WPM;
    this.phase = 'listen';  // listen → cq → called / reported → rag → done
    this.last = null;
    const n = VO_TOPICS_MIN + Math.floor(this.rng() * (VO_TOPICS_MAX - VO_TOPICS_MIN + 1));
    const topics = [...VO_TOPICS];
    this.topics = [];
    while (this.topics.length < n) this.topics.push(...topics.splice(Math.floor(this.rng() * topics.length), 1));
  }

  get call() { return this.p.call; }

  _say(text) { this.last = text; return text; }

  _out(text, heard) {
    return { text, heard, phase: this.phase, done: this.phase === 'done', wpm: this.wpm };
  }

  _hdr() { return `${this.user} DE ${this.p.call}`; }

  /** The VO calls CQ (the user answers with its call). */
  cq() {
    this.phase = 'cq';
    const v = this.p.call;
    return this._out(this._say(`CQ CQ CQ DE ${v} ${v} ${v} K`), null);
  }

  /** The first report of the VO (it was called). */
  _report() {
    const p = this.p;
    return `${this._hdr()} ${greeting(this.hour)} TNX FER CALL = UR RST ${p.rst} ${p.rst} = NAME ${p.name} ${p.name}`
      + ` = QTH ${p.qth} ${p.qth} = HW? ${this._hdr()} KN`;
  }

  /** Topics for the next over: the asked ones first, then its own up to VO_TOPICS_PER_OVER in all. */
  _topics(asks) {
    const own = this.topics.filter((tp) => !asks.includes(tp)).slice(0, Math.max(0, VO_TOPICS_PER_OVER - asks.length));
    const out = [...asks, ...own];
    this.topics = this.topics.filter((tp) => !out.includes(tp));
    return out.map((tp) => topicLine(tp, this.p));
  }

  _bye() {
    this.phase = 'done';
    const dr = this.userName ? ` ${this.userName}` : '';
    return `${this._hdr()} TNX FER QSO${dr} = 73 GL = ${this._hdr()} SK`;
  }

  reply(text) {
    const h = hear(text, this.p.call, this.user);
    if (h.from && !this.user) this.user = h.from;
    if (h.from && this.user && !sameCall(h.from, this.user) && this.phase === 'listen') this.user = h.from;
    if (h.name) this.userName = h.name;
    if (h.empty || this.phase === 'done') return this._out(null, h);
    const others = h.cq || h.toVo || h.rst || h.name || h.qth || h.asks.length || h.bye;
    // QRS / QRQ / AGN: the last over again (at the new speed)
    if (h.qrs) this.wpm = Math.max(VO_WPM_MIN, this.wpm - VO_QRS);
    if (h.qrq) this.wpm = Math.min(VO_WPM_MAX, this.wpm + VO_QRS);
    if ((h.agn || h.qrs || h.qrq) && this.last && !(h.rst || h.name || h.qth || h.asks.length)) {
      return this._out(this.last, h);
    }
    if (!this.user) return this._out(this._say(`QRZ? DE ${this.p.call} K`), h);
    switch (this.phase) {
      case 'listen':
      case 'cq':
        if (h.toVo) { this.phase = 'reported'; return this._out(this._say(this._report()), h); }
        if (h.cq) {
          this.phase = 'called';
          const v = this.p.call;
          return this._out(this._say(`${this.user} DE ${v} ${v} K`), h);
        }
        if (this.phase === 'cq' && h.from) { this.phase = 'reported'; return this._out(this._say(this._report()), h); }
        return this._out(this._say(`QRZ? DE ${this.p.call} K`), h);
      case 'called': {
        if (h.bye && !h.rst) return this._out(this._say(this._bye()), h);
        if (!h.rst && !h.name && !h.qth) return this._out(this._say(`${this._hdr()} PSE AGN K`), h);
        const p = this.p;
        const dr = this.userName ? ` DR ${this.userName}` : '';
        const lines = [`R TNX FER RPRT${dr}`, `UR RST ${p.rst} ${p.rst}`, `NAME ${p.name} ${p.name}`, `QTH ${p.qth} ${p.qth}`];
        if (this.mode === 'chatty') { lines.push(...this._topics(h.asks)); this.phase = 'rag'; } else this.phase = 'final';
        return this._out(this._say(`${this._hdr()} ${lines.join(' = ')} = HW? ${this._hdr()} K`), h);
      }
      case 'reported': {
        if (h.bye && !h.rst && !h.name) return this._out(this._say(this._bye()), h);
        if (!h.rst && !h.name && !h.qth && !h.asks.length) return this._out(this._say(`${this._hdr()} PSE AGN K`), h);
        const dr = this.userName ? ` DR ${this.userName}` : '';
        if (this.mode === 'quick') {
          this.phase = 'done';
          return this._out(this._say(`${this._hdr()} R TNX FER RPRT${dr} = TNX QSO ES 73 GL = ${this._hdr()} SK`), h);
        }
        this.phase = 'rag';
        const lines = [`R TNX FER RPRT${dr}`, ...this._topics(h.asks)];
        return this._out(this._say(`${this._hdr()} ${lines.join(' = ')} = ${this._hdr()} K`), h);
      }
      case 'final':
        if (h.bye || others) return this._out(this._say(this._bye()), h);
        return this._out(this._say(`${this._hdr()} PSE AGN K`), h);
      default: { // rag
        if (h.bye && !h.asks.length) return this._out(this._say(this._bye()), h);
        const lines = this._topics(h.asks);
        if (!lines.length) return this._out(this._say(this._bye()), h);
        return this._out(this._say(`${this._hdr()} R ${lines.join(' = ')} = ${this._hdr()} K`), h);
      }
    }
  }
}

/**
 * Timing of a VO over: elements [{start, end, word}] in ms from 0 and the end. wpm = character speed, fwpm =
 * Farnsworth speed (gaps between characters and words stretched as by ARRL; fwpm ≥ wpm = no stretch). Prosign words
 * (SK, KN, AR, BK) are keyed as one character.
 */
export function voTimings(text, wpm, fwpm, morse) {
  const u = 1200 / wpm;
  let cg = 3 * u;
  let wg = 7 * u;
  if (fwpm && fwpm < wpm) {
    const ta = (60000 * wpm - 37200 * fwpm) / (wpm * fwpm);   // ms of all gaps in PARIS at fwpm
    cg = (3 * ta) / 19;
    wg = (7 * ta) / 19;
  }
  const els = [];
  let t = 0;
  text.trim().split(/\s+/).forEach((w, wi) => {
    if (wi) t += wg - cg;
    const codes = PROSIGN_CODES[w] ? [PROSIGN_CODES[w]] : [...w].map((c) => morse[c]).filter(Boolean);
    codes.forEach((code, ci) => {
      if (ci || wi) t += cg - u;
      for (const e of code) {
        const on = e === '-' ? 3 * u : u;
        els.push({ start: t, end: t + on, word: wi });
        t += on + u;
      }
    });
  });
  return { els, end: els.length ? els.at(-1).end : 0 };
}
