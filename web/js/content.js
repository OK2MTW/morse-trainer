// SPDX-License-Identifier: EUPL-1.2
// Obsah lekce ve skluzu (M7): registr generátorů podle druhu obsahu. Položky jen ze zvládnutých znaků.
// M8 (U4): zkratky a Q-kódy, generované volací znaky, dlouhá slova, směs. U5 přidá QSO – stačí doplnit GENERATORS.
// Python port: tests/content.py.
import { WORDS, WORDS_LONG } from './words.js';
import { ABBR } from './abbr.js';

export const GROUP_MIN = 2;          // skupiny 2–3 znaky (krok 1–2 žebříku)
export const GROUP_MAX = 3;
export const SHARE_LETTERS = 0.7;    // skupiny: písmena 70 %, číslice 20 %, interpunkce 10 %
export const SHARE_DIGITS = 0.2;
export const PSEUDO_MIN = 2;         // pseudoslova 2–5 znaků (krok 3–4), jen písmena
export const PSEUDO_MAX = 5;
export const WORDS_MIN = 30;         // méně dostupných slov → doplnit pseudoslovy
export const ABBR_MIN = 15;          // M8: méně dostupných zkratek → doplnit slovy
export const LONG_MIN = 20;          // M8: méně dlouhých slov → doplnit krátkými
export const CALL_SLASH = 0.1;       // M8: volací znak s /P nebo /M
export const MIX_WORDS = 0.5;        // M8 směs: slova 50 % (půl krátká, půl dlouhá), zkratky 30 %, volací znaky 20 %
export const MIX_ABBR = 0.3;
// Formát volacího znaku prefix–číslice–sufix (L = písmeno, D = číslice) – generuje se, žádný seznam stanic.
export const CALL_PREFIXES = ['L', 'LL', 'LL', 'DL'];
export const CALL_SUFFIX = [1, 2, 2, 3, 3, 3];
// Šablony pseudoslov: C = souhláska, V = samohláska (snadno „vyslovitelné“ celky pro rozpoznání slovem, ICR).
export const PSEUDO_TEMPLATES = ['CV', 'VC', 'CVC', 'VCV', 'CVCV', 'CVCC', 'CCVC', 'VCVC', 'CVCVC', 'CCVCC'];

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const DIGITS = '0123456789';
const VOWELS = 'AEIOU';

const pick = (arr, rng) => arr[Math.floor(rng() * arr.length)];

/** Rozdělí zvládnuté znaky na písmena, číslice a interpunkci. */
export function pools(chars) {
  return {
    L: chars.filter((c) => LETTERS.includes(c)),
    D: chars.filter((c) => DIGITS.includes(c)),
    P: chars.filter((c) => !LETTERS.includes(c) && !DIGITS.includes(c)),
  };
}

/** Náhodná skupina 2–3 znaků; druh znaku podle podílů (když druh chybí, bere se z ostatních). */
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

/** Pseudoslovo podle šablony; bez samohlásek nebo souhlásek jen náhodná písmena. */
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

/** Slova jen ze zvládnutých písmen. */
export function wordsFor(chars) {
  const set = new Set(chars);
  return WORDS.filter((w) => [...w].every((c) => set.has(c)));
}

export function word(chars, rng, avail = wordsFor(chars)) {
  if (avail.length >= WORDS_MIN || (avail.length && rng() < avail.length / WORDS_MIN)) return pick(avail, rng);
  return pseudo(chars, rng);
}

/** Ze seznamu jen položky ze zvládnutých znaků. */
export const listFor = (list, chars) => { const set = new Set(chars); return list.filter((w) => [...w].every((c) => set.has(c))); };

/** Položka seznamu, když je jich dost (jinak s pravděpodobností podle počtu), jinak náhrada fb(). */
function fromList(avail, min, rng, fb) {
  if (avail.length >= min || (avail.length && rng() < avail.length / min)) return pick(avail, rng);
  return fb();
}

export function abbr(chars, rng, avail = listFor(ABBR, chars)) { return fromList(avail, ABBR_MIN, rng, () => word(chars, rng)); }

export function longWord(chars, rng, avail = listFor(WORDS_LONG, chars)) { return fromList(avail, LONG_MIN, rng, () => word(chars, rng)); }

/** Volací znak prefix–číslice–sufix ze zvládnutých znaků; prefix nezačíná Q (Q-kódy). Bez číslic → slovo. */
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

/** Směs pro U4 (příprava na QSO): slova, zkratky a Q-kódy, volací znaky. */
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

/** n položek daného druhu ze zvládnutých znaků. Sousední položky se neopakují. */
export function makeItems(content, chars, n, rng = Math.random) {
  const gen = GENERATORS[content] || GENERATORS.groups;
  const out = [];
  for (let guard = 0; out.length < n && guard < n * 10; guard++) {
    const [it] = gen(chars, 1, rng);
    if (it && it !== out.at(-1)) out.push(it);
  }
  return out;
}
