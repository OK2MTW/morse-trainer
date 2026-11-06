// SPDX-License-Identifier: EUPL-1.2
// Content of a copy-behind lesson (M7): a registry of generators by content kind. Items only from mastered characters.
// M8 (U4): abbreviations and Q codes, generated call signs, long words, a mix. U5 adds QSO – just extend GENERATORS.
// Python port: tests/content.py.
import { WORDS, WORDS_LONG } from './words.js';
import { ABBR } from './abbr.js';

export const GROUP_MIN = 2;          // groups of 2–3 characters (ladder steps 1–2)
export const GROUP_MAX = 3;
export const SHARE_LETTERS = 0.7;    // groups: letters 70 %, digits 20 %, punctuation 10 %
export const SHARE_DIGITS = 0.2;
export const PSEUDO_MIN = 2;         // pseudo-words of 2–5 characters (steps 3–4), letters only
export const PSEUDO_MAX = 5;
export const WORDS_MIN = 30;         // fewer available words → fill up with pseudo-words
export const ABBR_MIN = 15;          // M8: fewer available abbreviations → fill up with words
export const LONG_MIN = 20;          // M8: fewer long words → fill up with short ones
export const CALL_SLASH = 0.1;       // M8: call sign with /P or /M
export const MIX_WORDS = 0.5;        // M8 mix: words 50 % (half short, half long), abbreviations 30 %, call signs 20 %
export const MIX_ABBR = 0.3;
// Call sign format prefix–digit–suffix (L = letter, D = digit) – generated, no list of stations.
export const CALL_PREFIXES = ['L', 'LL', 'LL', 'DL'];
export const CALL_SUFFIX = [1, 2, 2, 3, 3, 3];
// Pseudo-word templates: C = consonant, V = vowel (easily "pronounceable" units for whole-word recognition, ICR).
export const PSEUDO_TEMPLATES = ['CV', 'VC', 'CVC', 'VCV', 'CVCV', 'CVCC', 'CCVC', 'VCVC', 'CVCVC', 'CCVCC'];

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const DIGITS = '0123456789';
const VOWELS = 'AEIOU';

const pick = (arr, rng) => arr[Math.floor(rng() * arr.length)];

/** Splits mastered characters into letters, digits and punctuation. */
export function pools(chars) {
  return {
    L: chars.filter((c) => LETTERS.includes(c)),
    D: chars.filter((c) => DIGITS.includes(c)),
    P: chars.filter((c) => !LETTERS.includes(c) && !DIGITS.includes(c)),
  };
}

/** A random group of 2–3 characters; character kind by shares (when a kind is missing, the others are used). */
export function group(chars, rng) {
  const p = pools(chars);
  const len = GROUP_MIN + Math.floor(rng() * (GROUP_MAX - GROUP_MIN + 1));
  let out = '';
  for (let i = 0; i < len; i++) {
    const r = rng();
    let pool = r < SHARE_LETTERS ? p.L : r < SHARE_LETTERS + SHARE_DIGITS ? p.D : p.P;
    if (!pool.length) pool = p.L.length ? p.L : chars;
    out += pick(pool, rng);
  }
  return out;
}

/** A pseudo-word by template; without vowels or consonants just random letters. */
export function pseudo(chars, rng) {
  const L = pools(chars).L;
  const V = L.filter((c) => VOWELS.includes(c));
  const K = L.filter((c) => !VOWELS.includes(c));
  if (!L.length) return group(chars, rng);
  const tpl = pick(PSEUDO_TEMPLATES, rng);
  let out = '';
  for (const x of tpl) {
    const pool = x === 'V' ? V : K;
    out += pick(pool.length ? pool : L, rng);
  }
  return out;
}

/** Words from mastered letters only. */
export function wordsFor(chars) {
  const set = new Set(chars);
  return WORDS.filter((w) => [...w].every((c) => set.has(c)));
}

export function word(chars, rng, avail = wordsFor(chars)) {
  if (avail.length >= WORDS_MIN || (avail.length && rng() < avail.length / WORDS_MIN)) return pick(avail, rng);
  return pseudo(chars, rng);
}

/** Only the list items made of mastered characters. */
export const listFor = (list, chars) => { const set = new Set(chars); return list.filter((w) => [...w].every((c) => set.has(c))); };

/** A list item when there are enough (otherwise with a probability by count), else the substitute fb(). */
function fromList(avail, min, rng, fb) {
  if (avail.length >= min || (avail.length && rng() < avail.length / min)) return pick(avail, rng);
  return fb();
}

export function abbr(chars, rng, avail = listFor(ABBR, chars)) { return fromList(avail, ABBR_MIN, rng, () => word(chars, rng)); }

export function longWord(chars, rng, avail = listFor(WORDS_LONG, chars)) { return fromList(avail, LONG_MIN, rng, () => word(chars, rng)); }

/** Call sign prefix–digit–suffix from mastered characters; the prefix does not start with Q (Q codes). Without digits → a word. */
export function call(chars, rng) {
  const p = pools(chars);
  const first = p.L.filter((c) => c !== 'Q');
  if (!p.D.length || !first.length) return word(chars, rng);
  let out = '';
  for (const x of pick(CALL_PREFIXES, rng)) out += x === 'D' ? pick(p.D, rng) : pick(out ? p.L : first, rng);
  out += pick(p.D, rng);
  const n = pick(CALL_SUFFIX, rng);
  for (let i = 0; i < n; i++) out += pick(p.L, rng);
  const sl = ['P', 'M'].filter((c) => p.L.includes(c));
  if (chars.includes('/') && sl.length && rng() < CALL_SLASH) out += `/${pick(sl, rng)}`;
  return out;
}

/** Mix for U4 (preparation for QSOs): words, abbreviations and Q codes, call signs. */
export function mixed(chars, rng) {
  const r = rng();
  if (r < MIX_WORDS / 2) return word(chars, rng);
  if (r < MIX_WORDS) return longWord(chars, rng);
  if (r < MIX_WORDS + MIX_ABBR) return abbr(chars, rng);
  return call(chars, rng);
}

export const GENERATORS = {
  groups: (chars, n, rng) => Array.from({ length: n }, () => group(chars, rng)),
  pseudo: (chars, n, rng) => Array.from({ length: n }, () => pseudo(chars, rng)),
  words: (chars, n, rng) => { const av = wordsFor(chars); return Array.from({ length: n }, () => word(chars, rng, av)); },
  abbr: (chars, n, rng) => Array.from({ length: n }, () => abbr(chars, rng)),
  calls: (chars, n, rng) => Array.from({ length: n }, () => call(chars, rng)),
  long: (chars, n, rng) => Array.from({ length: n }, () => longWord(chars, rng)),
  mix: (chars, n, rng) => Array.from({ length: n }, () => mixed(chars, rng)),
};

/** n items of the given kind from mastered characters. Neighbouring items do not repeat. */
export function makeItems(content, chars, n, rng = Math.random) {
  const gen = GENERATORS[content] || GENERATORS.groups;
  const out = [];
  for (let guard = 0; out.length < n && guard < n * 10; guard++) {
    const [it] = gen(chars, 1, rng);
    if (it && it !== out.at(-1)) out.push(it);
  }
  return out;
}
