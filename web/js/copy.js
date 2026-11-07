// SPDX-License-Identifier: EUPL-1.2
// Copy behind (M7, M8) – pure logic without DOM: alignment of the typed text to the sent one, lag (in characters
// and words), word results, fatigue per line. Python port: tests/copy.py (tests check that the constants match).
// Design: docs/requirements.md, sections on M7 and M8.

export const ROUND_ITEMS = 6;        // items (groups/words) in one line
export const ROUND_TAIL_MS = 3000;   // a line ends 3 s after the last tone (at least 2× the word gap)
export const COPY_MIN_CHARS = 60;    // a session is evaluated from 60 sent characters (same as server/coach.py)
// M8: fatigue in copy behind – evaluated per line (a line is a natural stop, the stream is not interrupted)
export const FAT_BASE_ROUNDS = 3;    // baseline = the first 3 lines of the lesson
export const FAT_WIN_ROUNDS = 2;     // current state = the last 2 lines
export const FAT_ACC_DROP = 0.1;     // accuracy ≥ 10 points lower …
export const FAT_ACC_FLOOR = 0.8;    // … and below 80 % (like FatigueMonitor in M5)
export const FAT_MISS_UP = 0.1;      // or the share of missing characters ≥ 10 points higher (losing the stream)
export const FAT_HOLD_S = 60;        // the signal must last > 1 min of net time
export const FAT_SNOOZE_S = 180;     // after "continue" the next proposal at the earliest in 3 min

// Order on equal backtracking cost: correct > substitution > missing > extra (deterministic scoring).
/**
 * Aligns typed characters to the sent ones (Levenshtein). sent, typed = arrays of characters (without spaces).
 * Returns operations [{op: 'ok'|'sub'|'del'|'ins', s: sent index|null, t: typed index|null}] in text order.
 * 'del' = a sent character is missing in the copy, 'ins' = an extra typed character.
 */
export function align(sent, typed) {
  const n = sent.length;
  const m = typed.length;
  const w = m + 1;
  const d = new Uint32Array((n + 1) * w);
  for (let i = 0; i <= n; i++) d[i * w] = i;
  for (let j = 0; j <= m; j++) d[j] = j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const sub = d[(i - 1) * w + j - 1] + (sent[i - 1] === typed[j - 1] ? 0 : 1);
      const del = d[(i - 1) * w + j] + 1;
      const ins = d[i * w + j - 1] + 1;
      d[i * w + j] = Math.min(sub, del, ins);
    }
  }
  const ops = [];
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    const cur = d[i * w + j];
    if (i > 0 && j > 0 && cur === d[(i - 1) * w + j - 1] + (sent[i - 1] === typed[j - 1] ? 0 : 1)) {
      ops.push({ op: sent[i - 1] === typed[j - 1] ? 'ok' : 'sub', s: i - 1, t: j - 1 });
      i--; j--;
    } else if (i > 0 && cur === d[(i - 1) * w + j] + 1) {
      ops.push({ op: 'del', s: i - 1, t: null });
      i--;
    } else {
      ops.push({ op: 'ins', s: null, t: j - 1 });
      j--;
    }
  }
  return ops.reverse();
}

/**
 * M9 part 2: operations that do not count – on a masked sent character (skip[s], the band made it unreadable) and an
 * extra character right next to a masked one. Returns an array of true/false by operation index.
 */
export function ignoredOps(ops, skip) {
  const out = ops.map(() => false);
  if (!skip || !skip.some(Boolean)) return out;
  const prev = new Array(ops.length).fill(false); // nearest sent character before / after the operation is masked
  const next = new Array(ops.length).fill(false);
  for (let k = 0, m = false; k < ops.length; k++) { prev[k] = m; if (ops[k].s !== null) m = !!skip[ops[k].s]; }
  for (let k = ops.length - 1, m = false; k >= 0; k--) { next[k] = m; if (ops[k].s !== null) m = !!skip[ops[k].s]; }
  ops.forEach((o, k) => { out[k] = o.s !== null ? !!skip[o.s] : prev[k] || next[k]; });
  return out;
}

/**
 * Operation counts, accuracy after alignment and confusions {`S→H`: n}. skip (M9 part 2) = masked sent characters:
 * they count neither way (mask = their number, n = sent characters that count).
 */
export function score(ops, sent, typed, skip = null) {
  const c = { ok: 0, sub: 0, del: 0, ins: 0, mask: 0 };
  const conf = {};
  const ign = ignoredOps(ops, skip);
  for (const [k, o] of ops.entries()) {
    if (ign[k]) { if (o.s !== null) c.mask++; continue; }
    c[o.op]++;
    if (o.op === 'sub') {
      const k = `${sent[o.s]}→${typed[o.t]}`;
      conf[k] = (conf[k] || 0) + 1;
    }
  }
  const n = sent.length - c.mask;
  const den = n + c.ins;
  return { ...c, n, acc: den ? c.ok / den : null, conf };
}

export function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const h = s.length >> 1;
  return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}

/** Percentile p (0–1), the nearest value from below (no interpolation – the same in Python). */
export function percentile(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

/**
 * Lag for paired characters (ok and substitution). ends[i] = end of the tone of sent character i (ms, performance.now),
 * times[j] = time of the press of typed character j. Returns [{s, ms, ch}] – ms after the end of the character,
 * ch = how many further sent characters have already finished.
 */
export function lagSamples(ops, ends, times, wordOf = null) {
  // M8: wordOf (word of each sent character) → lag in words too: how many further words have already finished
  const wEnd = [];
  if (wordOf) wordOf.forEach((w, i) => { wEnd[w] = ends[i]; });
  const out = [];
  for (const o of ops) {
    if (o.op !== 'ok' && o.op !== 'sub') continue;
    const t = times[o.t];
    let ch = 0;
    for (let k = o.s + 1; k < ends.length && ends[k] <= t; k++) ch++;
    const x = { s: o.s, ms: Math.round(t - ends[o.s]), ch };
    if (wordOf) {
      let wd = 0;
      for (let k = wordOf[o.s] + 1; k < wEnd.length && wEnd[k] <= t; k++) wd++;
      x.wd = wd;
    }
    out.push(x);
  }
  return out;
}

const r1 = (x) => (x === null ? null : Math.round(x * 10) / 10);

/** Lag summary: median/p90 in ms and characters, max. characters, drift (last third − first, in characters). */
export function lagSummary(samples) {
  if (!samples.length) return { lagMs: null, lagP90: null, lagCh: null, lagChP90: null, lagChMax: null, drift: null, lagW: null, lagWP90: null };
  const ms = samples.map((x) => x.ms);
  const ch = samples.map((x) => x.ch);
  const third = Math.floor(ch.length / 3);
  const drift = third >= 3 ? median(ch.slice(-third)) - median(ch.slice(0, third)) : null;
  return {
    lagMs: Math.round(median(ms)), lagP90: percentile(ms, 0.9),
    lagCh: r1(median(ch)), lagChP90: percentile(ch, 0.9), lagChMax: Math.max(...ch), drift: r1(drift),
    ...wordLag(samples),
  };
}

function wordLag(samples) {
  const wd = samples.filter((x) => x.wd !== undefined).map((x) => x.wd);
  return wd.length ? { lagW: r1(median(wd)), lagWP90: percentile(wd, 0.9) } : { lagW: null, lagWP90: null };
}

/**
 * Word results: words = array of words (strings), ops over the joined characters. A word is correct when all its
 * characters are correct and there is nothing extra inside the word. Returns an array of true/false.
 */
export function wordResults(words, ops, skip = null) {
  const wordOf = [];
  words.forEach((wd, k) => { for (let i = 0; i < wd.length; i++) wordOf.push(k); });
  const ok = words.map(() => true);
  // word of the next sent character after each operation (from the end)
  const nextWord = new Array(ops.length).fill(-1);
  for (let k = ops.length - 1, nw = -1; k >= 0; k--) {
    nextWord[k] = nw;
    if (ops[k].s !== null) nw = wordOf[ops[k].s];
  }
  const ign = ignoredOps(ops, skip);
  let lastWord = -1;
  ops.forEach((o, k) => {
    if (o.s !== null) {
      lastWord = wordOf[o.s];
      if (o.op !== 'ok' && !ign[k]) ok[lastWord] = false;
    } else if (!ign[k] && lastWord >= 0 && nextWord[k] === lastWord) {
      ok[lastWord] = false; // extra inside a word (on a word boundary it counts against neither)
    }
  });
  return ok;
}

/**
 * Line → scoring inputs. chars = [{ch, w, end}] from playStream, typed = [{ch, t}] (without spaces).
 * Returns {ops, sc, lags, words(ok[])} – used after a line and for the running word marks.
 */
export function evaluate(words, chars, typed) {
  const sent = chars.map((c) => c.ch);
  const tch = typed.map((x) => x.ch);
  const ops = align(sent, tch);
  const skip = chars.some((c) => c.mask) ? chars.map((c) => !!c.mask) : null; // M9 part 2: masked by the band
  return {
    ops, sc: score(ops, sent, tch, skip),
    lags: lagSamples(ops, chars.map((c) => c.end), typed.map((x) => x.t), chars.map((c) => c.w)),
    words: wordResults(words, ops, skip),
  };
}

/** Lesson summary from lines [{words, chars, typed, ev}] → detail.copy (without step and content – added by the caller). */
export function lessonSummary(rounds) {
  const c = { ok: 0, sub: 0, del: 0, ins: 0, n: 0, mask: 0 };
  const conf = {};
  const lags = [];
  let wn = 0;
  let wok = 0;
  for (const r of rounds) {
    for (const k of ['ok', 'sub', 'del', 'ins', 'n', 'mask']) c[k] += r.ev.sc[k] || 0;
    for (const [k, v] of Object.entries(r.ev.sc.conf)) conf[k] = (conf[k] || 0) + v;
    lags.push(...r.ev.lags);
    wn += r.ev.words.length;
    wok += r.ev.words.filter(Boolean).length;
  }
  const den = c.n + c.ins;
  const confusions = Object.entries(conf).sort((a, b) => b[1] - a[1]).map(([pair, n]) => ({ pair, n }));
  return {
    ...c, acc: den ? c.ok / den : null, ...lagSummary(lags), words: { n: wn, ok: wok },
    rounds: rounds.length, confusions: confusions.slice(0, 30),
  };
}

// ---------- fatigue in copy behind (M8) ----------
function roundStats(list) {
  let ok = 0; let n = 0; let ins = 0; let del = 0;
  for (const x of list) { ok += x.ok; n += x.n; ins += x.ins; del += x.del; }
  return { acc: n + ins ? ok / (n + ins) : 0, miss: n ? del / n : 0, n };
}

/**
 * Fatigue watch in a copy-behind lesson – after each line add(sc, startS, endS): sc = line score {ok, n, ins, del},
 * startS/endS = net lesson time at the start and end of the line. Returns {propose, kind ('acc'|'miss'|null), accDrop, missUp}.
 * Lag is not taken as fatigue (in U4 a longer lag is the goal). reset() after a pause, snooze() after "continue".
 */
export class CopyFatigue {
  constructor() {
    this.baseRounds = [];
    this.base = null;
    this.win = [];
    this.since = null;
    this.snoozeUntil = 0;
    this.last = { tired: false, accDrop: null, missUp: null };
  }

  reset() { this.win = []; this.since = null; }

  snooze(activeS) { this.snoozeUntil = activeS + FAT_SNOOZE_S; this.since = null; }

  add(sc, startS, endS) {
    const none = { propose: false, kind: null, accDrop: null, missUp: null };
    const r = { ok: sc.ok, n: sc.n, ins: sc.ins, del: sc.del, startS };
    if (!this.base) {
      this.baseRounds.push(r);
      if (this.baseRounds.length >= FAT_BASE_ROUNDS) this.base = roundStats(this.baseRounds);
      return none;
    }
    this.win.push(r);
    if (this.win.length > FAT_WIN_ROUNDS) this.win.shift();
    if (this.win.length < FAT_WIN_ROUNDS) { this.since = null; return none; }
    const cur = roundStats(this.win);
    const accDrop = Math.round((this.base.acc - cur.acc) * 1000) / 1000;
    const missUp = Math.round((cur.miss - this.base.miss) * 1000) / 1000;
    const accTired = accDrop >= FAT_ACC_DROP - 1e-9 && cur.acc < FAT_ACC_FLOOR - 1e-9;
    const missTired = missUp >= FAT_MISS_UP - 1e-9;
    this.last = { tired: accTired || missTired, accDrop, missUp };
    if (!this.last.tired) { this.since = null; return none; }
    if (this.since === null) this.since = this.win[0].startS; // the signal applies for the whole window
    const propose = endS - this.since > FAT_HOLD_S && endS >= this.snoozeUntil;
    return { propose, kind: accTired ? 'acc' : 'miss', accDrop, missUp };
  }
}
