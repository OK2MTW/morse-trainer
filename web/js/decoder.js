// SPDX-License-Identifier: EUPL-1.2
// VK D3 (0.11.3, docs/spec-klic.md A-11, A-13): adaptive decoder of keyed tones – pure logic, ported to
// tests/decoder.py (tests check the constants and shared vectors, the simulation of an operator's hand is there).
// Times come from the input events / the audio clock in ms (not from the sound) → the output latency of a phone or
// BT headphones does not enter decoding or evaluation.
//
// Marks: running estimates of the dot and dash length (moving average from a starting estimate taken from the data
// itself – initialDot; the set speed only as a fallback), threshold =
// geometric mean; the ratio of the estimates is kept within RATIO_LO–HI. Elements of an automatic keyer (iambic,
// bug dots) are known – they only update the estimates. Straight key and bug dashes are classified by length, i.e.
// as the other station hears them (a short bug dash reads as a dot).
// 0.12.2 (validation #31): the dot/dash and gap thresholds come first from the neighbourhood of each tone (DEC_WIN on
// each side, two groups in the log domain – markThreshold, gapThresholds): the rhythm is learned from all the data
// around, not only from what the decoder has already accepted (the running gap estimates locked themselves and a hand
// with longer gaps inside characters read as T/E only). The running estimates below are the fallback and the output.
// Gaps: estimates of the gap inside a character (g1) and between characters (g3), threshold = geometric mean;
// a word gap from WORD_GAP × g3 (≈ 7/3 – the middle between 3 and 7 units). An error sign (≥ FIX_DOTS dots, HH)
// drops the word in progress (or the previous one right after a word gap) and counts as a fix, not as an error.

export const DEC_ALPHA = 0.25;        // moving average weight (≈ the last 8 elements)
export const DEC_RATIO_LO = 2;        // dash:dot estimates kept within 2–4.5
export const DEC_RATIO_HI = 4.5;
export const DEC_GAP_IN_LO = 0.6;     // gap inside a character: 0.6–1.6 × dot
export const DEC_GAP_IN_HI = 1.6;
export const DEC_CHAR_GAP_LO = 1.8;   // gap between characters: ≥ 1.8 × the gap inside, ≤ 4.5 × dot
export const DEC_CHAR_GAP_HI = 4.5;
export const DEC_WORD_GAP = 1.53;     // word gap threshold = 1.53 × gap between characters (√(7/3))
export const DEC_FIX_DOTS = 7;        // error sign: at least 7 dots (0.16.1, Martin 2026-11-12)
export const DEC_INIT_N = 24;         // the starting estimate of the dot from the first 24 tones …
export const DEC_SPLIT = 1.8;         // … split into dots and dashes at a ratio of neighbouring lengths ≥ 1.8
// 0.12.2 (validation #31): the rhythm from the neighbourhood – DEC_WIN tones / gaps on each side
export const DEC_WIN = 16;
export const DEC_GAP_SPLIT = 1.3;     // gaps inside / between characters: medians of the two groups differ ≥ 1.3
export const DEC_WORD_SPLIT = 1.4;    // gaps between characters / words: ≥ 1.6
export const DEC_IN_MAX = 1.6;        // the lower group can be gaps inside characters when < 1.6 × the dot/dash threshold
export const DEC_WORD_MID = 4;        // no clear split by ratio: a word gap ≥ 4 × the dot/dash threshold (≈ 7 units)
export const DEC_IN_ONE = 1.3;        // one group of gaps only: inside characters when < 1.3 × the threshold
// 0.14.0 (A-11, A-13): the stream of a HW keyer – machine timing (dash = 3 dots, gap inside a character = 1 dot,
// ±1 ms of USB); only the gaps between characters and words are made by a human
export const DEC_MACH_SPLIT = 2;      // dot/dash threshold = 2 × dot; a gap < 2 × dot is inside a character
export const DEC_MACH_WIN = 8;        // the dot from 2 × DEC_MACH_WIN earlier tones … (the speed may change on the HW)
export const DEC_MACH_LOOK = 6;       // … and at most 6 tones ahead (0.15.4: a decision is final 6 tones later)
export const DEC_MACH_WORD = 5;       // gaps between characters / words without two groups: a word from 5 dots …
                                      // … unless the device remembers the hand's threshold (0.16.3, opts.word)
export const DEC_MACH_WORD_LO = 5;    // a learned word threshold kept within 5–9 dots (0.16.3: Martin's hand – gaps
export const DEC_MACH_WORD_HI = 9;    // between characters up to 7, words from 9 dots; the evaluation keeps the 3/7 norm)
export const DEC_MACH_GAPS = 24;      // learned from the last 24 human gaps before the gap (0.15.4: only earlier ones) …
export const DEC_MACH_MIN = 6;        // … at least 6 of them, else DEC_MACH_WORD
export const DEC_MACH_SEP = 1.3;      // the two groups of human gaps (around 3 and 7 dots) apart at least 1.3×
export const DEC_MACH_SD = 0.15;      // the spread of human gaps (log) taken as at least 0.15
export const DEC_MACH_IN_N = 3;       // the gap inside from at least 3 neighbouring gaps …
export const DEC_MACH_IN_LO = 0.5;    // … kept within 0.5–1.5 × the tone dot (the shift of late events, innerGap)
export const DEC_MACH_IN_HI = 1.5;

const DOT = '.';
const DASH = '-';

const median = (arr) => {
  const a = [...arr].sort((x, y) => x - y);
  const n = a.length;
  return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
};

/**
 * Starting estimate of the dot (ms) from the first DEC_INIT_N tones, so that the set speed does not have to match.
 * Known elements decide directly; otherwise the lengths of tones split into two groups with the least spread (log
 * domain) whose medians differ ≥ DEC_SPLIT; one group only (e.g. EISH, TMO) → the shortest gaps (≈ 1 unit inside a
 * character) tell whether those are dots or dashes. Nothing to go by → the set speed.
 */
export function initialDot(tones, wpm) {
  const head = tones.slice(0, DEC_INIT_N);
  const known = head.filter((tn) => tn.el).map((tn) => (tn.el === DOT ? tn.end - tn.start : (tn.end - tn.start) / 3));
  if (known.length) return median(known);
  const lens = head.map((tn) => Math.max(1, tn.end - tn.start)).sort((x, y) => x - y);
  if (!lens.length) return 1200 / wpm;
  // two groups with the least spread in the log domain (Otsu); accepted when their medians differ ≥ DEC_SPLIT
  const lg = lens.map(Math.log);
  let best = null;
  let at = null;
  for (let i = 1; i < lg.length; i++) {
    const a = lg.slice(0, i);
    const b = lg.slice(i);
    const ma = a.reduce((s, x) => s + x, 0) / a.length;
    const mb = b.reduce((s, x) => s + x, 0) / b.length;
    const v = a.reduce((s, x) => s + (x - ma) ** 2, 0) + b.reduce((s, x) => s + (x - mb) ** 2, 0);
    if (best === null || v < best) { best = v; at = i; }
  }
  if (at !== null && median(lens.slice(at)) >= DEC_SPLIT * median(lens.slice(0, at))) {
    return (median(lens.slice(0, at)) + median(lens.slice(at)) / 3) / 2;
  }
  const m = median(lens);
  const gaps = [];
  for (let i = 1; i < head.length; i++) gaps.push(head[i].start - head[i - 1].end);
  gaps.sort((x, y) => x - y);
  if (gaps.length) {
    const g = gaps.length < 3 ? gaps[0] : median(gaps.slice(0, Math.max(1, Math.floor(gaps.length / 3))));
    return m < 2 * g ? m : m / 3;
  }
  return m < 2 * (1200 / wpm) ? m : m / 3;
}

/** Values split into two groups with the least spread in the log domain (Otsu, prefix sums) → [lower, upper]. */
function split(vals) {
  const a = vals.map((v) => Math.max(1, v)).sort((x, y) => x - y);
  const n = a.length;
  if (n < 2) return null;
  const s1 = [0];
  const s2 = [0];
  for (const v of a) { const x = Math.log(v); s1.push(s1.at(-1) + x); s2.push(s2.at(-1) + x * x); }
  const sse = (i, j) => s2[j] - s2[i] - (s1[j] - s1[i]) ** 2 / (j - i);
  let best = null;
  let at = 1;
  for (let i = 1; i < n; i++) {
    const v = sse(0, i) + sse(i, n);
    if (best === null || v < best) { best = v; at = i; }
  }
  return [a.slice(0, at), a.slice(at)];
}

/** Medians [lower, upper] of two groups when they differ ≥ ratio, otherwise null. */
function apart(grp, ratio) {
  if (!grp) return null;
  const lo = median(grp[0]);
  const hi = median(grp[1]);
  return hi >= ratio * lo ? [lo, hi] : null;
}

/** Dot/dash threshold (ms) from the lengths of neighbouring tones, null = one group only (e.g. EISH). */
export function markThreshold(lens) {
  const m = apart(split(lens), DEC_SPLIT);
  return m ? Math.sqrt(m[0] * m[1]) : null;
}

/**
 * [inside/between characters, between characters/words] thresholds in ms from the neighbouring gaps, null = too few
 * gaps (the running estimates decide). Top down: gaps inside characters against the rest, then the rest split into
 * gaps between characters and words by their own ratio (a hand may keep long gaps between characters against its
 * tones – Farnsworth-like). mid = the dot/dash threshold from the tone lengths (≈ 1.7 units) only tells whether a
 * group can be gaps inside characters (< DEC_IN_MAX × mid; otherwise e.g. E T E) and, when the gaps between
 * characters and words cannot be told apart by their ratio, whether the long group is words (≥ DEC_WORD_MID × mid).
 */
export function gapThresholds(gaps, mid) {
  if (gaps.length < 2) return null;
  const grp = split(gaps);
  const m = apart(grp, DEC_GAP_SPLIT);
  if (!m) {
    // one group only: gaps inside characters when clearly short, otherwise between characters (E T E)
    const md = median(gaps);
    const t1 = md < DEC_IN_ONE * mid ? md * DEC_GAP_SPLIT : md / DEC_GAP_SPLIT;
    return [t1, Math.max(DEC_WORD_MID * mid, t1 * DEC_WORD_GAP)];
  }
  const [a, b] = m;
  if (a >= DEC_IN_MAX * mid) return [a / DEC_GAP_SPLIT, Math.sqrt(a * b)]; // no gaps inside characters
  const mb = apart(split(grp[1]), DEC_WORD_SPLIT);
  if (mb) return [Math.sqrt(a * mb[0]), Math.sqrt(mb[0] * mb[1])];         // inside | between | words
  // the upper group is one kind: between characters, or words far apart (then the lower group holds both the gaps
  // inside and between characters)
  const ma = apart(split(grp[0]), DEC_WORD_SPLIT);
  if (ma && b >= DEC_WORD_MID * mid && b >= DEC_WORD_SPLIT * ma[1]) {
    return [Math.sqrt(ma[0] * ma[1]), Math.sqrt(ma[1] * b)];
  }
  return [Math.sqrt(a * b), Math.max(b * DEC_WORD_GAP, DEC_WORD_MID * mid)];
}

/**
 * Dot length (ms) of a machine stream from neighbouring tone lengths and gaps. Two groups of lengths (dots and
 * dashes, ratio 3) → the median of the shorter one. One group only (e.g. EISH, TMO): a gap shorter than half the
 * length can only be a gap inside a character (= 1 dot) → dashes; otherwise the hint (the last known dot) decides.
 */
export function machineDot(lens, gaps, hint) {
  const m = apart(split(lens), DEC_MACH_SPLIT);
  if (m) return m[0];
  if (!lens.length) return hint;
  const md = median(lens);
  if (gaps.length && Math.min(...gaps) < md / DEC_MACH_SPLIT) return md / 3;
  return md < DEC_MACH_SPLIT * hint ? md : md / 3;
}

/**
 * 0.15.4: the gap inside a character the keyer made (ms) from neighbouring gaps < DEC_MACH_SPLIT dots – it is 1 dot
 * on the key, but a late key down / up event (USB, browser) makes tones longer and gaps shorter by the same time.
 * Fewer than DEC_MACH_IN_N such gaps → u (no correction); kept within DEC_MACH_IN_LO–HI × u.
 */
export function innerGap(gaps, u) {
  const g = gaps.filter((x) => x < DEC_MACH_SPLIT * u);
  if (g.length < DEC_MACH_IN_N) return u;
  return Math.min(DEC_MACH_IN_HI * u, Math.max(DEC_MACH_IN_LO * u, median(g)));
}

/**
 * Tones of a machine stream with known elements: {…tone, el, u} (u = the local dot in ms). hint = dot in ms.
 * 0.15.4: the dot of a tone from earlier tones and at most DEC_MACH_LOOK tones ahead – decoding the growing record
 * again and again gives the same result for everything older (an erased word does not come back, validation B).
 */
export function machineTones(tones, hint) {
  const lens = tones.map((tn) => tn.end - tn.start);
  const gms = tones.slice(1).map((tn, i) => tn.start - tones[i].end);
  const n = 2 * DEC_MACH_WIN + 1;
  let u = hint;
  return tones.map((tn, i) => {
    const m1 = Math.min(lens.length, i + DEC_MACH_LOOK + 1);
    const m0 = Math.max(0, m1 - n);
    u = machineDot(lens.slice(m0, m1), gms.slice(m0, m1 - 1), u);
    return { ...tn, el: lens[i] < DEC_MACH_SPLIT * u ? DOT : DASH, u, g: innerGap(gms.slice(m0, m1 - 1), u) };
  });
}

const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const sqDev = (a, m) => a.reduce((x, y) => x + (y - m) ** 2, 0);

/**
 * Threshold between characters / words (in dots) from earlier human gaps of a machine stream (in dots,
 * ≥ DEC_MACH_SPLIT): two groups in the log domain (k-means started at 3 and 7 dots), the threshold in the middle
 * between them, shifted by how many gaps each group has (Bayes with a common spread), kept within
 * DEC_MACH_WORD_LO–HI (0.15.4); fewer than DEC_MACH_MIN gaps or no two clear groups → `start` (0.16.3: the threshold
 * this device learned from the hand earlier, else DEC_MACH_WORD; null = nothing learned → null).
 */
export function machineWordGap(units, start = DEC_MACH_WORD) {
  const fb = start === null ? null : Math.min(DEC_MACH_WORD_HI, Math.max(DEC_MACH_WORD_LO, start));
  if (units.length < DEC_MACH_MIN) return fb;
  const h = units.map(Math.log);
  let a = Math.log(3);
  let b = Math.log(7);
  let A = [];
  let B = [];
  for (let k = 0; k < 15; k++) {
    A = h.filter((x) => Math.abs(x - a) <= Math.abs(x - b));
    B = h.filter((x) => Math.abs(x - a) > Math.abs(x - b));
    if (A.length) a = mean(A);
    if (B.length) b = mean(B);
  }
  if (A.length < 2 || !B.length || b - a < Math.log(DEC_MACH_SEP)) return fb;
  const s2 = Math.max((sqDev(A, a) + sqDev(B, b)) / h.length, DEC_MACH_SD ** 2);
  const w = Math.exp((a + b) / 2 + (s2 * Math.log(A.length / B.length)) / (b - a));
  return Math.min(DEC_MACH_WORD_HI, Math.max(DEC_MACH_WORD_LO, w));
}

/**
 * 0.16.3 (Martin: "adapt it to me for now, the evaluation always against the norm"): the word threshold learned
 * from the human gaps of a decoding, or null (too few gaps / no two groups). The pages keep it per device
 * (WORD_STORE) and pass it as opts.word, so the next record / over starts with the hand's threshold, not 5 dots.
 */
export function learnedWordGap(dec) {
  const h = (dec?.units || []).filter((x) => x !== null && x >= DEC_MACH_SPLIT);
  return machineWordGap(h.slice(-DEC_MACH_GAPS), null);
}

const WORD_STORE = 'morse.dec.word';

/** The word threshold this device learned earlier (dots), or undefined. */
export function loadWordHint() {
  try {
    const w = Number(localStorage.getItem(WORD_STORE));
    return w >= DEC_MACH_WORD_LO && w <= DEC_MACH_WORD_HI ? w : undefined;
  } catch (e) { return undefined; }
}

/** Remembers the threshold learned from this decoding of the user's own keying (nothing learned → unchanged). */
export function saveWordHint(dec) {
  const w = learnedWordGap(dec);
  if (w === null) return;
  try { localStorage.setItem(WORD_STORE, w.toFixed(2)); } catch (e) { /* private mode */ }
}

/** Kind of a gap of a machine stream: inside a character (< DEC_MACH_SPLIT dots, the keyer kept running), between
 * characters (< word dots) or words. u = the local dot in ms. */
export function machineGapKind(ms, u, word) {
  if (ms < DEC_MACH_SPLIT * u) return 0;
  return ms < word * u ? 1 : 2;
}

class DecoderState {
  constructor(u) {
    this.dot = u; this.dash = 3 * u; this.g1 = u; this.g3 = 3 * u;
    this.nMark = 0; this.nGap = 0;
  }

  // warm-up: the prior from the set speed counts as one observation, then the moving average
  alpha(n) { return Math.max(DEC_ALPHA, 1 / (n + 2)); }

  mark(ms, el) {
    if (!el) el = ms < Math.sqrt(this.dot * this.dash) ? DOT : DASH;
    const a = this.alpha(this.nMark);
    this.nMark += 1;
    if (el === DOT) this.dot += a * (ms - this.dot);
    else this.dash += a * (ms - this.dash);
    const mid = Math.sqrt(this.dot * this.dash);
    const r = this.dash / this.dot;
    if (r < DEC_RATIO_LO || r > DEC_RATIO_HI) {
      const half = Math.sqrt(Math.min(DEC_RATIO_HI, Math.max(DEC_RATIO_LO, r)));
      this.dot = mid / half; this.dash = mid * half;
    }
    return el;
  }

  mid() { return Math.sqrt(this.dot * this.dash); }

  /**
   * 0 = inside a character, 1 = between characters, 2 = between words (kind given = decided from the neighbouring
   * gaps, only updates the estimates).
   */
  gap(ms, kind = null) {
    if (kind === null) kind = ms < Math.sqrt(this.g1 * this.g3) ? 0 : (ms < this.g3 * DEC_WORD_GAP ? 1 : 2);
    if (kind === 0) {
      this.g1 += this.alpha(this.nGap) * (ms - this.g1);
      this.nGap += 1;
    } else if (kind === 1) {
      this.g3 += DEC_ALPHA * (ms - this.g3);
    }
    this.g1 = Math.min(DEC_GAP_IN_HI * this.dot, Math.max(DEC_GAP_IN_LO * this.dot, this.g1));
    this.g3 = Math.min(DEC_CHAR_GAP_HI * this.dot, Math.max(DEC_CHAR_GAP_LO * this.g1, this.g3));
    return kind;
  }

  unit() { return (this.dot + this.dash / 3) / 2; }
}

// 1.1 K2: a gap model of the hand (Bell 1977: probabilities of gap classes instead of a threshold). Machine stream
// only: a gap < DEC_MACH_SPLIT dots is inside a character (the keyer makes it); the human gaps are a mixture of two
// log-normal classes – between characters / between words. Prior = the norm 3/7 with pseudocounts (cold start: a few
// gaps already move it), learned by EM (MAP) over the whole over plus what was learned in the earlier overs of the
// session (the model of the other station's hand). Every gap gets the probability of its class. Python port:
// tests/decoder.py GapModel (reads these constants).
export const DEC_GM_CHAR = 3;         // prior means (dots) between characters …
export const DEC_GM_WORD = 7;         // … and between words
export const DEC_GM_SD = 0.25;        // prior spread (log)
export const DEC_GM_SD_MIN = 0.1;     // learned spread at least
export const DEC_GM_NPRIOR = 3;           // pseudocounts of the prior per class
export const DEC_GM_KEEP = 40;        // learned counts carried to the next over at most (both classes)
export const DEC_GM_SEP = 1.25;       // the two class means apart at least 1.25×
export const DEC_GM_ITER = 15;
export const DEC_GM_W_WORD = 0.28;    // prior share of word gaps among the human gaps …
export const DEC_GM_W_N = 20;         // … worth 20 gaps
export const DEC_GM_WIN = 6;          // the tempo of the hand from ±6 neighbouring human gaps …
export const DEC_GM_SHRINK = 2;       // … shrunk towards the mean tempo (2 gaps' worth)
export const DEC_GM_MIN = 6;          // the EM starts from a split of the data with at least 6 human gaps

/** Two-class log-normal mixture of human gaps (in dots). prior = learned() of an earlier over or null (= norm). */
export class GapModel {
  constructor(prior = null) {
    if (prior) {
      this.m0 = [...prior.m]; this.s0 = [...prior.s]; this.n0 = prior.n.map((n) => Math.max(1, n));
    } else {
      this.m0 = [Math.log(DEC_GM_CHAR), Math.log(DEC_GM_WORD)];
      this.s0 = [DEC_GM_SD, DEC_GM_SD]; this.n0 = [DEC_GM_NPRIOR, DEC_GM_NPRIOR];
    }
    this.m = [...this.m0]; this.s = [...this.s0]; this.w = [0.75, 0.25];
    this.nk = [0, 0]; this.hs = []; this.off = [];
  }

  resp(h) {
    const p = [0, 1].map((c) => this.w[c] / this.s[c] * Math.exp(-0.5 * ((h - this.m[c]) / this.s[c]) ** 2));
    const t = p[0] + p[1];
    if (!(t > 0)) return Math.abs(h - this.m[0]) < Math.abs(h - this.m[1]) ? [1, 0] : [0, 1];
    return [p[0] / t, p[1] / t];
  }

  // EM from a split of the data, not from the prior (from 3/7 a slow hand's gaps between characters around 6–8 dots
  // pulled the word class down – a local optimum): Otsu – the split with the largest between-class variance
  start(hs) {
    if (hs.length < DEC_GM_MIN) return;
    const h = [...hs].sort((a, b) => a - b);
    const n = h.length;
    const tot = h.reduce((a, b) => a + b, 0);
    let best = -1, k = 0, acc = 0;
    for (let i = 1; i < n; i++) {
      acc += h[i - 1];
      const a = acc / i, b = (tot - acc) / (n - i);
      const v = i * (n - i) * (b - a) ** 2;
      if (v > best) { best = v; k = i; }
    }
    const a = h.slice(0, k).reduce((x, y) => x + y, 0) / k;
    const b = h.slice(k).reduce((x, y) => x + y, 0) / (n - k);
    if (b - a >= Math.log(DEC_GM_SEP)) { this.m = [a, b]; this.w = [k / n, (n - k) / n]; }
  }

  /**
   * EM over the human gaps of an over (time order) with a slowly changing tempo of the hand: every gap has an offset
   * (log) = the smoothed residual of its neighbours (±DEC_GM_WIN gaps), shrunk towards 0 (the hand drifts during a
   * session – globally the classes overlap, locally not).
   */
  fit(xs) {
    const hs = xs.map((x) => Math.log(x));
    const n = hs.length;
    this.hs = hs; this.off = new Array(n).fill(0);
    this.start(hs);
    const reach = 3 * DEC_GM_WIN;
    const sep = Math.log(DEC_GM_SEP);
    for (let it = 0; it < (n ? DEC_GM_ITER : 0); it++) {
      const zs = hs.map((h, i) => h - this.off[i]);
      const rs = zs.map((z) => this.resp(z));
      let vs = 0, ns = 0;
      for (const c of [0, 1]) {
        let nk = 0, sz = 0;
        rs.forEach((r, i) => { nk += r[c]; sz += r[c] * zs[i]; });
        const tot = this.n0[c] + nk;
        const m = (this.n0[c] * this.m0[c] + sz) / tot;
        // the spread has its own prior and is common to both classes (a wide word class took the slow gaps between
        // characters – self-reinforcing)
        vs += this.n0[c] * this.s0[c] ** 2;
        rs.forEach((r, i) => { vs += r[c] * (zs[i] - m) ** 2; });
        ns += tot;
        this.m[c] = m; this.nk[c] = nk;
      }
      const sd = Math.max(DEC_GM_SD_MIN, Math.sqrt(vs / ns));
      this.s = [sd, sd];
      if (this.m[1] - this.m[0] < sep) {
        const mid = (this.m[0] + this.m[1]) / 2;
        this.m = [mid - sep / 2, mid + sep / 2];
      }
      // the share of word gaps has its own prior (a text has ~1 word gap per 3–4 gaps between characters)
      const pw = [1 - DEC_GM_W_WORD, DEC_GM_W_WORD];
      const t = DEC_GM_W_N + this.nk[0] + this.nk[1];
      this.w = [0, 1].map((c) => (DEC_GM_W_N * pw[c] + this.nk[c]) / t);
      if (n >= DEC_GM_MIN && it >= 2) {
        const res = hs.map((h, i) => h - (rs[i][0] * this.m[0] + rs[i][1] * this.m[1]));
        const off = [];
        for (let i = 0; i < n; i++) {
          let a = 0, b = DEC_GM_SHRINK;
          for (let j = Math.max(0, i - reach); j < Math.min(n, i + reach + 1); j++) {
            const k = Math.exp(-0.5 * ((i - j) / DEC_GM_WIN) ** 2);
            a += k * res[j]; b += k;
          }
          off.push(a / b);
        }
        this.off = off;
      }
    }
    return this;
  }

  /** P(word gap) of every human gap of the fitted over (with its local tempo). */
  wordProbs() { return this.hs.map((h, i) => this.resp(h - this.off[i])[1]); }

  /** P(word gap | x dots) for a human gap at the mean tempo. */
  wordProb(x) { return this.resp(Math.log(x))[1]; }

  /** The model for the next over: means, spreads and counts (capped in proportion – the hand may change). */
  learned() {
    const n = [0, 1].map((c) => this.n0[c] + this.nk[c]);
    const k = Math.min(1, DEC_GM_KEEP / (n[0] + n[1]));
    return { m: [...this.m], s: [...this.s], n: n.map((v) => k * v) };
  }
}

/** Gaps of a machine stream (output of machineTones) in local dots, as decodeTones computes them; null first. */
export function machineUnits(tones) {
  return tones.map((tn, i) => {
    if (!i) return null;
    const pv = tones[i - 1];
    const tu = (tn.u + pv.u) / 2;
    const g = (tn.g + pv.g) / 2;
    const u = (tu + g) / 2;
    return (tn.start - pv.end + (tu - g) / 2) / u;
  });
}

/**
 * 1.1 K2: the gap classes of one over from the gap model → {kinds, conf, gm}. kinds[i] = 0/1/2 (null first),
 * conf[i] = the probability of the chosen class.
 */
export function modelGaps(units, prior = null) {
  const gm = new GapModel(prior).fit(units.slice(1).filter((x) => x >= DEC_MACH_SPLIT));
  const probs = gm.wordProbs();
  let k = 0;
  const kinds = [null];
  const conf = [null];
  for (const x of units.slice(1)) {
    if (x < DEC_MACH_SPLIT) { kinds.push(0); conf.push(1); continue; }
    const p = probs[k++];
    kinds.push(p >= 0.5 ? 2 : 1);
    conf.push(Math.max(p, 1 - p));
  }
  return { kinds, conf, gm };
}

/**
 * tones = [{start, end, el?}] in ms, time order; el = known element (automatic keyer), missing/null = classify by
 * length. morse = {char: code}. opts.machine = a stream of a HW keyer (0.14.0): elements and gaps inside characters
 * by machine timing (machineTones, opts.dot = the hint of the dot in ms, else from wpm). Returns {text, codes,
 * chars: [{ch, code, i0, i1}], marks, gaps (null for the first tone), fixes, dot, dash, g1, g3, wpm, tones} – the
 * estimates at the end, wpm from the unit estimate, tones = the input (machine: with el and u).
 * Machine stream (0.15.4, diagnostics): units = each gap in dots, words = the word threshold in dots it was judged
 * by (null for the first tone; empty arrays otherwise). opts.model (1.1 K2): conf = the probability of the class of
 * each gap, gm = the fitted GapModel (gm.learned() → opts.gapPrior of the next over); null without the model.
 */
export function decodeTones(tones, wpm, morse, opts = {}) {
  const machine = !!opts.machine;
  if (machine) tones = machineTones(tones, opts.dot || 1200 / wpm);
  // 1.1 K2: opts.model = the gaps of a machine stream from the gap model of the whole over (opts.gapPrior = learned()
  // of the earlier overs) – for reading a finished over; the live reading keeps the threshold of earlier gaps
  const gm = machine && opts.model ? modelGaps(machineUnits(tones), opts.gapPrior || null) : null;
  const byCode = {};
  for (const [ch, code] of Object.entries(morse)) if (!(code in byCode)) byCode[code] = ch;
  const st = new DecoderState(initialDot(tones, wpm));
  const chars = [];
  const marks = [];
  const gaps = [];
  const fixRe = new RegExp(`^\\.{${DEC_FIX_DOTS},}$`);
  let fixes = 0;
  let code = '';
  let i0 = 0;

  const flush = (i1) => {
    if (!code) return;
    if (fixRe.test(code)) {
      fixes += 1;
      // error sign: drops the word in progress, or the previous word right after a word gap
      while (chars.length && chars.at(-1).ch === ' ') chars.pop();
      while (chars.length && chars.at(-1).ch !== ' ') chars.pop();
    } else {
      chars.push({ ch: byCode[code] ?? '*', code, i0, i1 });
    }
    code = '';
  };

  // the rhythm of the hand from the neighbourhood (DEC_WIN tones / gaps on each side), see the header
  const lens = tones.map((tn) => tn.end - tn.start);
  const gms = tones.slice(1).map((tn, i) => tn.start - tones[i].end);
  // machine stream: the threshold between characters and words from earlier human gaps (in dots – the speed may change)
  const human = [];
  const units = [];
  const words = [];
  let prevEnd = null;
  tones.forEach((tn, i) => {
    if (prevEnd === null) {
      gaps.push(null);
      if (machine) { units.push(null); words.push(null); }
    } else {
      // a window of a fixed size (at the start and the end shifted inwards → the same amount of context)
      const g0 = Math.min(Math.max(0, i - 1 - DEC_WIN), Math.max(0, gms.length - 2 * DEC_WIN - 1));
      const near = gms.slice(g0, g0 + 2 * DEC_WIN + 1);
      const ms = tn.start - prevEnd;
      let kind;
      if (machine) {
        // a late event shifts every edge alike: the true dot = (tone dot + gap inside) / 2, a gap + half the difference
        const tu = (tn.u + tones[i - 1].u) / 2;
        const g = (tn.g + tones[i - 1].g) / 2;
        const u = (tu + g) / 2;
        const x = (ms + (tu - g) / 2) / u;
        const word = machineWordGap(human.slice(-DEC_MACH_GAPS), opts.word || DEC_MACH_WORD);
        kind = st.gap(ms, gm ? gm.kinds[i] : machineGapKind(x, 1, word));
        units.push(x);
        words.push(word);
        if (x >= DEC_MACH_SPLIT) human.push(x);
      } else {
        const thr = gapThresholds(near, st.mid());
        kind = st.gap(ms, thr === null ? null : (ms < thr[0] ? 0 : (ms < thr[1] ? 1 : 2)));
      }
      gaps.push(kind);
      if (kind) {
        flush(i - 1);
        i0 = i;
        if (kind === 2 && chars.length && chars.at(-1).ch !== ' ') chars.push({ ch: ' ', code: ' ', i0: i, i1: i - 1 });
      }
    }
    let el = tn.el || null;
    if (!el) {
      const m0 = Math.min(Math.max(0, i - DEC_WIN), Math.max(0, lens.length - 2 * DEC_WIN - 1));
      const thr = markThreshold(lens.slice(m0, m0 + 2 * DEC_WIN + 1));
      if (thr !== null) el = lens[i] < thr ? DOT : DASH;
    }
    el = st.mark(lens[i], el);
    marks.push(el);
    code += el;
    prevEnd = tn.end;
  });
  flush(tones.length - 1);
  while (chars.length && chars.at(-1).ch === ' ') chars.pop();
  return {
    text: chars.map((c) => c.ch).join(''),
    codes: chars.map((c) => c.code),
    chars, marks, gaps, fixes, units, words,
    dot: st.dot, dash: st.dash, g1: st.g1, g3: st.g3, wpm: 1200 / st.unit(), tones,
    conf: gm ? gm.conf : null, gm: gm ? gm.gm : null,
  };
}

// 0.15.4: diagnostics of the key page ("How the decoder reads") – the last words of a machine stream gap by gap
export const DEC_DIAG_WORDS = 3;      // the last 3 words
export const DEC_DIAG_NEAR = 1.15;    // a gap within 15 % of a threshold is marked as close

const near = (x, thr) => Math.abs(Math.log(x / thr)) < Math.log(DEC_DIAG_NEAR);

/**
 * Characters of the last nWords words of a decoded machine stream (decodeTones with opts.machine) with their gaps in
 * dots: [{code, ch (null = no character, '' = the error sign), before (the gap before in dots, null at the start),
 * kind (0/1/2 of that gap), word (the word threshold it was judged by), close (before is near a threshold), inMax
 * (the longest gap inside, dots), inClose}] and {dot (ms), wpm, split, word (the last threshold)}; null without data.
 */
export function gapDiagnostics(dec, morse, nWords = DEC_DIAG_WORDS) {
  const { tones, gaps, units, words } = dec;
  if (!tones.length || units.length !== tones.length) return null;
  const byCode = {};
  for (const [ch, code] of Object.entries(morse)) if (!(code in byCode)) byCode[code] = ch;
  let start = 0;
  let seen = 0;
  for (let i = gaps.length - 1; i > 0; i--) {
    if (gaps[i] === 2 && ++seen >= nWords) { start = i; break; }
  }
  const rows = [];
  let row = null;
  for (let i = start; i < tones.length; i++) {
    if (i === start || gaps[i] > 0) {
      row = {
        code: '', ch: null, before: i === start && i === 0 ? null : units[i], kind: i === 0 ? null : gaps[i],
        word: words[i], close: false, inMax: null, inClose: false,
      };
      if (row.before !== null) row.close = near(row.before, DEC_MACH_SPLIT) || near(row.before, row.word);
      rows.push(row);
    } else {
      row.inMax = Math.max(row.inMax ?? 0, units[i]);
      row.inClose = near(row.inMax, DEC_MACH_SPLIT);
    }
    row.code += tones[i].el;
  }
  const fix = new RegExp(`^\\.{${DEC_FIX_DOTS},}$`);
  for (const r of rows) r.ch = fix.test(r.code) ? '' : (byCode[r.code] ?? null);
  const last = tones.at(-1);
  const dot = (last.u + last.g) / 2;
  return { rows, dot, wpm: 1200 / dot, split: DEC_MACH_SPLIT, word: words.filter((w) => w !== null).at(-1) ?? DEC_MACH_WORD };
}
