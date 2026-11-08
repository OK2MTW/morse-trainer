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
export const DEC_FIX_DOTS = 7;        // error sign: at least 7 dots
export const DEC_INIT_N = 24;         // the starting estimate of the dot from the first 24 tones …
export const DEC_SPLIT = 1.8;         // … split into dots and dashes at a ratio of neighbouring lengths ≥ 1.8
// 0.12.2 (validation #31): the rhythm from the neighbourhood – DEC_WIN tones / gaps on each side
export const DEC_WIN = 16;
export const DEC_GAP_SPLIT = 1.3;     // gaps inside / between characters: medians of the two groups differ ≥ 1.3
export const DEC_WORD_SPLIT = 1.4;    // gaps between characters / words: ≥ 1.6
export const DEC_IN_MAX = 1.6;        // the lower group can be gaps inside characters when < 1.6 × the dot/dash threshold
export const DEC_WORD_MID = 4;        // no clear split by ratio: a word gap ≥ 4 × the dot/dash threshold (≈ 7 units)
export const DEC_IN_ONE = 1.3;        // one group of gaps only: inside characters when < 1.3 × the threshold

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

/**
 * tones = [{start, end, el?}] in ms, time order; el = known element (automatic keyer), missing/null = classify by
 * length. morse = {char: code}. Returns {text, codes, chars: [{ch, code, i0, i1}], marks, gaps (null for the first
 * tone), fixes, dot, dash, g1, g3, wpm} – the estimates at the end, wpm from the unit estimate.
 */
export function decodeTones(tones, wpm, morse) {
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
  let prevEnd = null;
  tones.forEach((tn, i) => {
    if (prevEnd === null) {
      gaps.push(null);
    } else {
      // a window of a fixed size (at the start and the end shifted inwards → the same amount of context)
      const g0 = Math.min(Math.max(0, i - 1 - DEC_WIN), Math.max(0, gms.length - 2 * DEC_WIN - 1));
      const thr = gapThresholds(gms.slice(g0, g0 + 2 * DEC_WIN + 1), st.mid());
      const ms = tn.start - prevEnd;
      const kind = st.gap(ms, thr === null ? null : (ms < thr[0] ? 0 : (ms < thr[1] ? 1 : 2)));
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
    chars, marks, gaps, fixes,
    dot: st.dot, dash: st.dash, g1: st.g1, g3: st.g3, wpm: 1200 / st.unit(),
  };
}
