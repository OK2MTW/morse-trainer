// SPDX-License-Identifier: EUPL-1.2
// Trainer logic (no DOM): character selection, recording answers, evaluation, Koch progression, discrimination.
// !!! The Python port in tests/trainer.py must stay identical (tests/test_trainer.py checks the constants).
import { KOCH_ORDER, MORSE } from './charset.js';

export const ADVANCE_WINDOW = 40;     // last N characters for the decision to advance
export const ADVANCE_ACCURACY = 0.9;  // Koch threshold 90 %
export const NEW_MIN_N = 8;           // the newest character must sound at least N× in the lesson
export const NEW_ACCURACY = 0.85;     // … with an accuracy of at least 85 %
export const NEW_TTR_RATIO = 1.5;     // … and a median reaction of at most 1.5× the median of the other characters
export const PRIOR_N = 3;             // weight of long-term statistics in character selection (pseudo-trials)
export const PRIOR_MIN_N = 5;         // long-term statistics of a character are used from N trials
export const DEFAULT_ERR = 0.3;       // estimated error rate of a character without history
export const DISCRIM_TRIALS = 12;     // discrimination trials after introducing a new character
export const TREND_MIN_N = 10;        // trend only from N trials in the comparison period
export const TREND_MIN_CUR = 5;       // … and at least N in the evaluated period
// M4 (conclusions of R1)
export const MIN_WPM = 12;            // hard limit of the character speed (Koch ≥ 10 WPM, with a margin)
export const DISCRIM_SIMILAR_FROM = 17; // the most similar pairs (S/H, U/V, D/B) in discrimination only from ~1/3 of the set
export const MAINTAIN_MIN = 0.15;     // share of mastered characters in the mix (maintenance) – lower limit
export const MAINTAIN_MAX = 0.2;      // … upper limit (overlearning does not pay off)
export const MASTER_MIN_N = 20;       // mastered character: at least N trials long-term
export const MASTER_ACC = 0.9;        // … with an accuracy of at least 90 % and at most 1 error in the last 10 of the lesson
export const SCATTER_MIN_CHARS = 4;   // the new character never 2× in a row (from N characters in the set)
// Difficulty control within a lesson (loop a): target ~85 %, band 80–90 % (Wilson 2019)
export const BAND_LO = 0.8;
export const BAND_HI = 0.9;
export const DIFF_WINDOW = 20;        // accuracy of the last N characters
export const DIFF_EVERY = 5;          // adjust at most every N characters
export const DIFF_STEP = 0.15;        // step of the weight exponent
export const DIFF_MIN = 0.4;          // flat weights = easier (more known characters)
export const DIFF_MAX = 2.5;          // sharp weights = harder (more weak characters and the new one)
export const MAINTAIN_EASY_MAX = 0.3; // at the easiest setting mastered characters may make up to 30 %
// Advancing (loop b): besides 90 % also a stable reaction
export const TTR_STABLE_RATIO = 1.25; // median TTR of the 2nd half of the window at most 1.25× the 1st half
export const STABLE_REL_MIN = 5;     // 0.8.4: TTR relative to the same character (without the new one) when each half has at least N trials
// 0.8.4 (log #4, #5): a more balanced mix – the new character does not crowd out revision, weak and confused characters more often
export const NEW_SHARE_MAX = 0.3;    // the new character at most 30 % of the weights (previously practically every 2nd character)
export const CONF_BONUS = 0.25;      // extra weight for each confusion of the character (both directions, long-term statistics) …
export const CONF_CAP = 4;           // … at most N confusions count
// M6: last resort within a lesson – when the mix cannot get easier (diff = DIFF_MIN) and accuracy is below 75 %,
// the gaps (Farnsworth) get longer by GAP_EASE_STEP WPM, at most GAP_EASE_MAX steps, only in this lesson (R1 ch. 1)
export const GAP_EASE_ACC = 0.75;
export const GAP_BACK_ACC = 0.85;    // from 85 % the gaps go back one step
export const GAP_EASE_MAX = 2;
export const GAP_EASE_STEP = 2;      // WPM of effective speed per step
export const GAP_EVERY = 10;         // at most every N characters
export const FW_MIN = 5;             // longest gaps (same as server/coach.py)

export function charsForLevel(level) {
  return KOCH_ORDER.slice(0, Math.max(2, Math.min(KOCH_ORDER.length, level)));
}

export function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

export class Drill {
  /**
   * @param {string[]} chars  current character set
   * @param {string|null} newChar  newest character (comes more often, checked when advancing)
   * @param {{rng?: Function, prior?: Object}} opts  prior = long-term statistics {ch: {n, acc, ttr}} from the server
   */
  constructor(chars, newChar = null, { rng = Math.random, prior = {} } = {}) {
    this.chars = chars;
    this.newChar = newChar;
    this.rng = rng;
    this.prior = prior || {};
    this.priorTtr = median(chars.filter((c) => this.prior[c]?.ttr != null && this.prior[c].n >= PRIOR_MIN_N)
      .map((c) => this.prior[c].ttr));
    this.trials = [];   // {ch, ans, ok, ttr, repeats, timeout}
    this.stats = Object.fromEntries(chars.map((c) => [c, { n: 0, err: 0, ttrs: [] }]));
    this.diff = 1;          // weight exponent: > 1 harder, < 1 easier
    this.diffAt = 0;        // number of trials at the last adjustment
    this.diffLog = [];      // [trial, diff] – changes for the lesson detail
    this.gapEase = 0;       // M6: number of gap-lengthening steps in the lesson
    this.gapAt = 0;
    this.gapLog = [];       // [trial, gapEase]
    this.exclude = new Set(); // temporarily excluded characters (warm-up with known characters only)
    // 0.8.4: confusions from long-term statistics in both directions (W→J raises both W and J)
    this.confN = Object.fromEntries(chars.map((c) => [c, 0]));
    for (const [c, p] of Object.entries(this.prior)) {
      for (const x of p?.conf || []) {
        if (c in this.confN) this.confN[c] += x.n || 0;
        if (x.ans in this.confN) this.confN[x.ans] += x.n || 0;
      }
    }
  }

  /** Warm-up: exclude characters (only when at least 2 remain). An empty list = stop excluding. */
  setExclude(list) {
    const rest = this.chars.filter((c) => !list.includes(c));
    this.exclude = new Set(rest.length >= 2 ? list : []);
  }

  /** Loop a: keep the accuracy of the last DIFF_WINDOW characters within the 80–90 % band. */
  regulate() {
    const n = this.trials.length;
    if (n < DIFF_WINDOW) return;
    const acc = this.trials.slice(-DIFF_WINDOW).filter((t) => t.ok).length / DIFF_WINDOW;
    if (n - this.diffAt >= DIFF_EVERY) {
      let d = this.diff;
      if (acc > BAND_HI) d = Math.min(DIFF_MAX, d + DIFF_STEP);
      else if (acc < BAND_LO) d = Math.max(DIFF_MIN, d - DIFF_STEP);
      if (d !== this.diff) {
        this.diff = Math.round(d * 100) / 100;
        this.diffAt = n;
        this.diffLog.push([n, this.diff]);
      }
    }
    // M6: gaps only when the mix cannot get any easier
    if (n - this.gapAt >= GAP_EVERY) {
      let g = this.gapEase;
      if (acc < GAP_EASE_ACC && this.diff <= DIFF_MIN + 1e-9) g = Math.min(GAP_EASE_MAX, g + 1);
      else if (acc >= GAP_BACK_ACC) g = Math.max(0, g - 1);
      if (g !== this.gapEase) {
        this.gapEase = g;
        this.gapAt = n;
        this.gapLog.push([n, g]);
      }
    }
  }

  /** Effective gap speed in the lesson (WPM) for the configured fwpm. */
  lessonFwpm(fwpm) {
    return this.gapEase ? Math.max(FW_MIN, Math.min(fwpm, fwpm - GAP_EASE_STEP * this.gapEase)) : fwpm;
  }

  /** Long-term error rate of a character (or the default estimate). */
  priorErr(c) {
    const p = this.prior[c];
    return p && p.n >= PRIOR_MIN_N && p.acc != null ? 1 - p.acc : DEFAULT_ERR;
  }

  /** Weight of a character: error rate and slow reaction increase its frequency. Starts from long-term statistics. */
  weight(c) {
    if (this.exclude.has(c)) return 0;
    const s = this.stats[c];
    const recent = this.trials.filter((t) => t.ch === c).slice(-10);
    const errs = recent.filter((t) => !t.ok).length;
    const err = (errs + PRIOR_N * this.priorErr(c)) / (recent.length + PRIOR_N);
    // 0.8.4: slowness relative to the old characters – a fast (predictable) new character would distort the comparison
    const all = median(this.trials.filter((t) => t.ok && t.ttr != null && t.ch !== this.newChar).map((t) => t.ttr));
    const mine = median(s.ttrs.slice(-10));
    let slow = 1;
    if (all && mine) slow = mine / all;
    else if (this.priorTtr && this.prior[c]?.ttr && this.prior[c].n >= PRIOR_MIN_N) slow = this.prior[c].ttr / this.priorTtr;
    slow = Math.min(2, Math.max(0.5, slow));
    let w = 1 + 4 * err + 1.5 * (slow - 1) + CONF_BONUS * Math.min(CONF_CAP, this.confN[c] || 0);
    if (c === this.newChar) {
      w *= 1.8;
      // scatter the new character among known ones – never twice in a row
      if (this.chars.length >= SCATTER_MIN_CHARS && this.trials.at(-1)?.ch === c) w = 0;
    }
    // the same character at most 2× in a row
    const last2 = this.trials.slice(-2).map((t) => t.ch);
    if (last2.length === 2 && last2[0] === c && last2[1] === c) w = 0;
    return Math.max(0, w);
  }

  /** Mastered character (maintenance only): long-term ≥ 90 % of ≥ 20 trials and at most 1 error in the last 10 of the lesson. */
  isMastered(c) {
    if (c === this.newChar) return false;
    const p = this.prior[c];
    if (!p || p.n < MASTER_MIN_N || p.acc == null || p.acc < MASTER_ACC) return false;
    return this.trials.filter((t) => t.ch === c).slice(-10).filter((t) => !t.ok).length < 2;
  }

  /** Selection weights: the share of mastered characters is kept within MAINTAIN_MIN–MAINTAIN_MAX. */
  mixWeights() {
    const ws = this.chars.map((c) => this.weight(c) ** this.diff);
    const m = this.chars.map((c) => this.isMastered(c));
    let sM = 0, sA = 0;
    ws.forEach((w, i) => { if (m[i]) sM += w; else sA += w; });
    if (sM > 0 && sA > 0) {
      const share = sM / (sM + sA);
      // when making it easier (diff < 1) there may be more mastered characters – success helps
      const easy = Math.max(0, Math.min(1, (1 - this.diff) / (1 - DIFF_MIN)));
      const max = MAINTAIN_MAX + easy * (MAINTAIN_EASY_MAX - MAINTAIN_MAX);
      const goal = Math.min(max, Math.max(MAINTAIN_MIN, share));
      if (goal !== share) {
        const f = (goal * sA) / ((1 - goal) * sM);
        for (let i = 0; i < ws.length; i++) if (m[i]) ws[i] *= f;
      }
    }
    // 0.8.4: cap on the share of the new character
    const k = this.chars.indexOf(this.newChar);
    if (k >= 0 && ws[k] > 0) {
      const rest = ws.reduce((a, b) => a + b, 0) - ws[k];
      if (rest > 0 && ws[k] / (ws[k] + rest) > NEW_SHARE_MAX) ws[k] = (NEW_SHARE_MAX * rest) / (1 - NEW_SHARE_MAX);
    }
    return ws;
  }

  next() {
    const ws = this.mixWeights();
    const total = ws.reduce((a, b) => a + b, 0);
    let r = this.rng() * total;
    for (let i = 0; i < ws.length; i++) {
      r -= ws[i];
      if (r <= 0) return this.chars[i];
    }
    return this.chars[this.chars.length - 1];
  }

  record(ch, ans, ttr, { repeats = 0, timeout = false } = {}) {
    const ok = !timeout && ans === ch;
    this.trials.push({ ch, ans, ok, ttr, repeats, timeout });
    const s = this.stats[ch];
    s.n++;
    if (!ok) s.err++;
    if (ok && ttr !== null) s.ttrs.push(ttr);
    this.regulate();
    return ok;
  }

  get accuracy() {
    return this.trials.length ? this.trials.filter((t) => t.ok).length / this.trials.length : 0;
  }

  /** Accuracy over the last ADVANCE_WINDOW characters, or null if there are too few. */
  recentAccuracy() {
    if (this.trials.length < ADVANCE_WINDOW) return null;
    const w = this.trials.slice(-ADVANCE_WINDOW);
    return w.filter((t) => t.ok).length / w.length;
  }

  /**
   * 0.8.4 (log #1): TTR medians of the two halves of the window. Preferably as a ratio to the long-term reaction to the
   * same character without the new one (the mix and set size do not distort it), otherwise (few data) plain TTR.
   */
  stableTtrs(a, b) {
    const rel = (ts) => ts.filter((t) => t.ok && t.ttr != null && t.ch !== this.newChar && this.prior[t.ch]?.ttr
      && this.prior[t.ch].n >= PRIOR_MIN_N).map((t) => (t.ttr * 1000) / this.prior[t.ch].ttr);
    const ra = rel(a), rb = rel(b);
    if (ra.length >= STABLE_REL_MIN && rb.length >= STABLE_REL_MIN) return [median(ra), median(rb)];
    const raw = (ts) => median(ts.filter((t) => t.ok && t.ttr != null).map((t) => t.ttr));
    return [raw(a), raw(b)];
  }

  /**
   * Koch progression: ≥ 90 % in the last 40 characters AND the newest character ≥ 85 % (at least 8×)
   * AND its median reaction ≤ 1.5× the median of the others. reason = the first unmet condition.
   */
  advanceCheck() {
    const r = { ok: false, reason: null, recent: this.recentAccuracy(), newChar: this.newChar, newN: 0, newAcc: null, newTtr: null, othersTtr: null };
    if (r.recent === null) { r.reason = 'few'; return r; }
    if (r.recent < ADVANCE_ACCURACY) { r.reason = 'acc'; return r; }
    // stable reaction: TTR does not get worse in the second half of the window (otherwise fatigue / uncertainty)
    const win = this.trials.slice(-ADVANCE_WINDOW);
    const half = win.length >> 1;
    const [t1, t2] = this.stableTtrs(win.slice(0, half), win.slice(half));
    r.ttrRatio = t1 && t2 ? Math.round((t2 / t1) * 100) / 100 : null;
    if (r.ttrRatio !== null && r.ttrRatio > TTR_STABLE_RATIO) { r.reason = 'ttrUnstable'; return r; }
    const s = this.newChar ? this.stats[this.newChar] : null;
    if (s) {
      r.newN = s.n;
      if (s.n < NEW_MIN_N) { r.reason = 'newFew'; return r; }
      r.newAcc = (s.n - s.err) / s.n;
      if (r.newAcc < NEW_ACCURACY) { r.reason = 'newAcc'; return r; }
      r.newTtr = median(s.ttrs);
      r.othersTtr = median(this.trials.filter((t) => t.ok && t.ch !== this.newChar && t.ttr != null).map((t) => t.ttr));
      if (r.newTtr !== null && r.othersTtr !== null && r.newTtr > NEW_TTR_RATIO * r.othersTtr) { r.reason = 'newSlow'; return r; }
    }
    r.ok = true;
    return r;
  }

  canAdvance() { return this.advanceCheck().ok; }

  summary() {
    const ok = this.trials.filter((t) => t.ok);
    const perChar = this.chars.map((c) => {
      const s = this.stats[c];
      return { ch: c, n: s.n, acc: s.n ? (s.n - s.err) / s.n : null, ttr: median(s.ttrs) };
    });
    const conf = {};
    for (const t of this.trials) {
      if (!t.ok && !t.timeout) conf[`${t.ch}→${t.ans}`] = (conf[`${t.ch}→${t.ans}`] || 0) + 1;
    }
    const confusions = Object.entries(conf).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ pair: k, n }));
    const advance = this.advanceCheck();
    return {
      trials: this.trials.length,
      correct: ok.length,
      accuracy: this.accuracy,
      medianTtr: median(ok.map((t) => t.ttr)),
      timeouts: this.trials.filter((t) => t.timeout).length,
      perChar,
      confusions,
      advance,
      canAdvance: advance.ok,
      recentAccuracy: advance.recent,
      diff: this.diff,
      diffLog: this.diffLog,
      gapEase: this.gapEase,
      gapLog: this.gapLog,
    };
  }
}

/**
 * Trend of a character: cur and base = {n, acc, ttr}. Returns 'up' | 'down' | 'flat', or null (few data).
 * Used by the lesson result (lesson vs. long-term) and the Statistics card (last 5 lessons vs. earlier ones).
 */
export function trendArrow(cur, base) {
  if (!cur || !base || cur.acc == null || base.acc == null) return null;
  if (cur.n < TREND_MIN_CUR || base.n < TREND_MIN_N) return null;
  const dAcc = cur.acc - base.acc;
  const ratio = cur.ttr && base.ttr ? cur.ttr / base.ttr : 1;
  if (dAcc <= -0.1 || (dAcc < 0.05 && ratio >= 1.2)) return 'down';
  if (dAcc >= 0.1 || (dAcc > -0.05 && ratio <= 0.85)) return 'up';
  return 'flat';
}

/** Edit distance of two codes (dots/dashes) – a measure of how similar they sound. */
export function codeDistance(a, b) {
  const x = MORSE[a] || '', y = MORSE[b] || '';
  let prev = Array.from({ length: y.length + 1 }, (_, j) => j);
  for (let i = 1; i <= x.length; i++) {
    const cur = [i];
    for (let j = 1; j <= y.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x[i - 1] === y[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[y.length];
}

/**
 * Characters the new character is practised against in discrimination: first those it was already confused with
 * (conf = {char: number of confusions in both directions}), then the most similar-sounding, on a tie the later learned.
 * Up to 1/3 of the set (setSize < DISCRIM_SIMILAR_FROM) the most similar characters (code distance ≤ 1) are not set
 * against each other unless the user actually confuses them (Koch, R1).
 */
export function pickContrasts(target, known, conf = {}, max = 2, setSize = KOCH_ORDER.length) {
  let items = known.filter((c) => c !== target)
    .map((c) => ({ c, conf: conf[c] || 0, dist: codeDistance(target, c), idx: KOCH_ORDER.indexOf(c) }));
  if (setSize < DISCRIM_SIMILAR_FROM) {
    const far = items.filter((x) => x.conf > 0 || x.dist > 1);
    if (far.length) items = far;
  }
  return items
    .sort((a, b) => (b.conf - a.conf) || (a.dist - b.dist) || (b.idx - a.idx))
    .slice(0, max)
    .map((x) => x.c);
}

/** Order of discrimination trials: half new characters, half contrasting ones, random, at most 2× the same in a row. */
export function discrimSequence(targets, contrasts, n = DISCRIM_TRIALS, rng = Math.random) {
  const seq = [];
  for (let i = 0; i < n; i++) {
    const fromT = !contrasts.length || i % 2 === 0;
    const list = fromT ? targets : contrasts;
    seq.push(list[Math.floor(i / (contrasts.length ? 2 : 1)) % list.length]);
  }
  const runOk = (s) => s.every((c, i) => i < 2 || !(s[i - 1] === c && s[i - 2] === c));
  for (let k = 0; k < 30; k++) {
    for (let i = seq.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [seq[i], seq[j]] = [seq[j], seq[i]];
    }
    if (runOk(seq)) break;
  }
  return seq;
}
