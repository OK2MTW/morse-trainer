// SPDX-License-Identifier: EUPL-1.2
// 0.16.0 – the virtual operator (VO) of the CW room: a QSO partner that runs in the browser only (no server, nothing
// stored). A state machine with templates – no AI. It reads what the decoder made of the user's over (tolerant: call
// signs with one mistake, RST patterns, NAME / QTH, AGN / QRS / QRQ), answers in one of two modes and plays through
// the band of the room (voui.js). It never keys the HW (H-21). Python port: tests/vo.py.
import { QSO_NAMES, QSO_QTH, QSO_WX, QSO_RIG, QSO_ANT, QSO_PWR } from './content.js';
import { VOCAB } from './vocab.js';

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

const token = (tk) => tk.replace(/\?+$/, '');
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

// 1.0.1: tolerance of the timing – gaps between characters / words that came out wrong are mended into known words
// ("QR S" → QRS, "OK2 MTW" → the call, "QRSK" → QRS K). Only spacing: the characters must match exactly.
export const VO_TOLS = ['auto', 'high', 'mid', 'off'];
export const VO_TOL_JOIN = { high: 3, mid: 2, off: 0 };   // at most this many fragments joined into one word
export const VO_WORDS = ['CQ', 'DE', 'QRS', 'QRQ', 'QRZ', 'AGN', 'RPT', 'RST', 'UR', 'NAME', 'OP', 'QTH', 'TU', 'TNX',
  'FER', 'FB', '73', 'GB', 'GL', 'PSE', 'HR', 'ES', 'IS', 'GM', 'GA', 'GE', 'OM', 'YL', 'HW', 'CPY', 'QSO', 'DR', 'R'];
const KNOWN = new Set([...VO_WORDS, ...VO_TOPICS, ...OVER_ENDS]);
/** The tolerance by the step of the sending lessons (D4, index 0–3): characters / groups → high, words / QSO → mid. */
export const tolForStep = (index) => (index >= 2 ? 'mid' : 'high');

/** The over with its spacing mended (tol = high / mid / off); calls = the call signs of the QSO (exact match only). */
export function mendSpacing(text, tol, calls = []) {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  const max = VO_TOL_JOIN[tol] || 0;
  if (!max) return tokens.join(' ');
  const cs = calls.filter(Boolean);
  const known = (w) => KNOWN.has(w) || RST_RE.test(w) || cs.includes(w);
  const out = [];
  let i = 0;
  while (i < tokens.length) {
    let n = Math.min(max, tokens.length - i);
    for (; n >= 2; n--) {
      const part = tokens.slice(i, i + n);
      if (part.slice(0, -1).some((tk) => tk.includes('?')) || part.some((tk) => !token(tk))) continue;
      const q = part[n - 1].match(/\?*$/)[0];
      const word = part.map(token).join('');
      if (known(word)) { out.push(word + q); break; }
    }
    if (n >= 2) { i += n; continue; }
    const tk = tokens[i++];
    const base = token(tk);
    const q = tk.slice(base.length);
    let split = null;
    if (!known(base)) {
      for (let k = base.length - 1; k >= 1 && !split; k--) {
        const a = base.slice(0, k);
        const b = base.slice(k);
        if (known(a) && known(b) && a.length >= 2 && (b.length >= 2 || OVER_ENDS.includes(b))) split = [a, b + q];
      }
    }
    out.push(...(split || [tk]));
  }
  return out.join(' ');
}

// 1.1 K3: the spacing of an over from the gap model and a lexicon (Viterbi over the word boundaries). Every gap between
// two characters has P(word gap) from the gap model of the hand (decoder GapModel); the best split of the over into
// words maximises P(gaps)·P(text)^weight, P(text) = a product of word costs: a known word (VO words, topics, ends,
// abbreviations, Q codes, QSO lists, the calls of the QSO) is cheap, a pattern (call, RST, number) a bit more, anything
// else costs per word and per character. Characters are never changed (only the spacing). Python port: tests/vo.py.
export const VO_LEX_WORD = 0.7;        // every word (against splitting into many short known words)
export const VO_LEX_PATTERN = 1.2;     // a call-like word, RST, a number, a call within one character of a call of the QSO
export const VO_LEX_UNKNOWN = 1.0;     // an unknown word …
export const VO_LEX_CHAR = 1.0;        // … plus per character
export const VO_LEX_PMIN = 0.03;       // P(word gap) clipped to [PMIN, 1 − PMIN]
export const VO_LEX_LONG = 7;          // an unknown word longer than this is rare …
export const VO_LEX_LONG_CHAR = 0.7;   // … per character over (joining two unknown words is not cheaper than two words)
export const VO_LEX_MAXLEN = 16;       // the longest word considered
export const VO_LEX_WEIGHT = { high: 1.5, mid: 1.0, off: 0.0 };   // the tolerance = the weight of the lexicon
const NUM_RE = /^\d{1,4}[A-Z]{0,2}$/;
const PROSIGN_NAMES = new Set(Object.values(PROSIGNS));
let lexicon = null;
const lex = () => lexicon || (lexicon = new Set([...KNOWN, ...QSO_NAMES, ...QSO_QTH, ...QSO_WX, ...QSO_RIG, ...QSO_ANT,
  ...QSO_PWR, ...Object.values(VOCAB).flat()]));

/** −log P(word) (up to a constant) for one word of an over; a trailing '?' is not part of the word. */
export function wordCost(w, calls = []) {
  const base = token(w);
  if (!base || base.includes('?') || base.includes('*')) return VO_LEX_WORD + VO_LEX_UNKNOWN + VO_LEX_CHAR * w.length;
  if (lex().has(base) || calls.includes(base)) return VO_LEX_WORD;
  if (RST_RE.test(base) || NUM_RE.test(base) || looksLikeCall(base) || calls.some((c) => sameCall(base, c))) {
    return VO_LEX_WORD + VO_LEX_PATTERN;
  }
  return VO_LEX_WORD + VO_LEX_UNKNOWN + VO_LEX_CHAR * base.length
    + VO_LEX_LONG_CHAR * Math.max(0, base.length - VO_LEX_LONG);
}

/**
 * units = [[text, pw]]: the characters of an over in order (a prosign as its name) with P(word gap) of the gap BEFORE
 * it (null for the first; 1 = a fixed boundary). Returns the over as text with the most probable spacing.
 */
export function segment(units, tol = 'mid', calls = []) {
  const lam = VO_LEX_WEIGHT[tol] ?? 1;
  const cs = calls.filter(Boolean);
  const isPro = (t) => PROSIGN_NAMES.has(t);
  const join = (run, a, b) => run.slice(a, b).map(([t]) => t).join('');
  // split into runs between fixed boundaries (prosigns, the start)
  const runs = [];
  let cur = [];
  units.forEach(([t, pw], i) => {
    const fixed = isPro(t) || (i > 0 && isPro(units[i - 1][0]));
    if (cur.length && (pw == null || pw >= 1 || fixed)) { runs.push(cur); cur = []; }
    cur.push([t, pw]);
  });
  if (cur.length) runs.push(cur);
  const out = [];
  for (const run of runs) {
    const n = run.length;
    if (n === 1 || isPro(run[0][0])) { out.push(join(run, 0, n)); continue; }
    const split = [0];
    const jsum = [0];             // jsum[k] = Σ join[1..k]; joins inside run[a:b] = jsum[b-1] − jsum[a]
    for (let k = 1; k < n; k++) {
      const p = Math.min(1 - VO_LEX_PMIN, Math.max(VO_LEX_PMIN, run[k][1]));
      split.push(-Math.log(p));
      jsum.push(jsum[k - 1] + -Math.log(1 - p));
    }
    const best = [0, ...new Array(n).fill(Infinity)];
    const back = new Array(n + 1).fill(0);
    for (let b = 1; b <= n; b++) {
      for (let a = Math.max(0, b - VO_LEX_MAXLEN); a < b; a++) {
        const c = best[a] + split[a] + (jsum[b - 1] - jsum[a]) + lam * wordCost(join(run, a, b), cs);
        if (c < best[b]) { best[b] = c; back[b] = a; }
      }
    }
    const words = [];
    for (let b = n; b > 0; b = back[b]) words.push(join(run, back[b], b));
    out.push(...words.reverse());
  }
  return out.join(' ');
}

/**
 * The characters of an over decoded with the gap model (decodeTones opts.model) for segment: [[text, P(word gap
 * before)]], a prosign as its name; null without the model. After the error sign the gap before the next character is
 * the word gap that preceded the error sign (its index in the space).
 */
export function overUnits(dec) {
  if (!dec || !dec.conf) return null;
  const out = [];
  let sp = null;
  for (const c of dec.chars) {
    if (c.ch === ' ') { sp = c.i0; continue; }
    const i = sp === null ? c.i0 : sp;
    const k = dec.gaps[i];
    const p = dec.conf[i];
    const pw = !out.length ? null : (p == null ? 1 : (k === 2 ? p : (k === 1 ? 1 - p : 0)));
    out.push([PROSIGNS[c.code] || c.ch, pw]);
    sp = null;
  }
  return out;
}

export const VO_UNSURE = 0.25;      // a gap with P(word gap) in [UNSURE, 1 − UNSURE] is shown as unsure (1.1 K4)

/**
 * The gaps of a read over (segment of units) the VO was unsure of: [[text, unsure]] in order – a word or a part of a
 * word (unsure false), a space ' ' or a join '' (unsure true) at a gap with P(word gap) near 0.5; null when no gap was
 * unsure or the read does not match the units. Only for showing; the reading itself does not change.
 */
export function unsureMarks(units, read) {
  if (!units || !units.length || !read) return null;
  const out = [];
  let pos = 0;
  let word = '';
  let any = false;
  for (let k = 0; k < units.length; k++) {
    const [t, pw] = units[k];
    let sep = '';
    if (k > 0 && read[pos] === ' ') { sep = ' '; pos++; }
    if (read.slice(pos, pos + t.length) !== t) return null;
    pos += t.length;
    const unsure = k > 0 && pw != null && pw < 1 && pw >= VO_UNSURE && pw <= 1 - VO_UNSURE
      && !PROSIGN_NAMES.has(t) && !PROSIGN_NAMES.has(units[k - 1][0]);   // a prosign is always a word
    if (unsure) {
      if (word) out.push([word, false]);
      out.push([sep, true]);
      word = '';
      any = true;
    } else word += sep;
    word += t;
  }
  if (pos !== read.length) return null;
  if (word) out.push([word, false]);
  return any ? out : null;
}

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
    this.tol = VO_TOL_JOIN[opts.tol] !== undefined ? opts.tol : 'off';  // 1.0.1: timing tolerance
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

  /** The over as the VO reads it: units (overUnits) → segment, else the spacing mended by the tolerance. */
  read(text, units = null) {
    const calls = [this.p.call, this.user];
    return units && units.length ? segment(units, this.tol, calls) : mendSpacing(text, this.tol, calls);   // 1.1 K3: units → the model
  }

  reply(text, units = null) {
    const read = this.read(text, units);
    const h = hear(read, this.p.call, this.user);
    h.read = read !== text.trim().split(/\s+/).filter(Boolean).join(' ') ? read : null;
    h.marks = units && units.length ? unsureMarks(units, read) : null;   // 1.1 K4: the unsure gaps (only shown)
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
