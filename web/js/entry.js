// SPDX-License-Identifier: EUPL-1.2
// Z-14 (0.10.16): entry test for those who already know CW (returning and active operators) – pure logic without DOM.
// Every character of the main programme is played ENTRY_REPS times in random order (never twice in a row), answered on
// the keyboard without feedback. Known = every repetition correct within ENTRY_TTR_MAX ms. The suggested number of
// characters = the longest run of known characters from the start of the Koch order. Python port: tests/entry.py.
export const ENTRY_REPS = 2;
export const ENTRY_TTR_MAX = 2000; // ms after the end of the character
export const ENTRY_MIN_LEVEL = 2;  // never below the start (K M)

/** Order of the test: each character ENTRY_REPS times, shuffled, no character twice in a row. */
export function entrySequence(chars, rng = Math.random) {
  const pool = chars.flatMap((c) => Array(ENTRY_REPS).fill(c));
  const out = [];
  while (pool.length) {
    const ok = pool.map((c, i) => i).filter((i) => pool[i] !== out.at(-1));
    const pickFrom = ok.length ? ok : pool.map((c, i) => i);
    const i = pickFrom[Math.floor(rng() * pickFrom.length)];
    out.push(pool.splice(i, 1)[0]);
  }
  return out;
}

/**
 * trials = [{ch, ans (null = timeout), ttr}] in Koch order chars → {known [], unsure [], level, perChar [{ch, n, acc, ttr}]}.
 * level = how many characters from the start of chars are all known (at least ENTRY_MIN_LEVEL).
 */
export function entryResult(chars, trials) {
  const per = new Map(chars.map((c) => [c, []]));
  for (const tr of trials) per.get(tr.ch)?.push(tr);
  const known = [];
  const unsure = [];
  const perChar = [];
  for (const c of chars) {
    const ts = per.get(c);
    const okTs = ts.filter((x) => x.ans === c);
    const good = ts.length >= ENTRY_REPS && okTs.length === ts.length && okTs.every((x) => x.ttr != null && x.ttr <= ENTRY_TTR_MAX);
    (good ? known : unsure).push(c);
    if (ts.length) {
      const r = okTs.map((x) => x.ttr).filter((x) => x != null).sort((a, b) => a - b);
      perChar.push({ ch: c, n: ts.length, acc: okTs.length / ts.length, ttr: r.length ? r[(r.length - 1) >> 1] : null });
    }
  }
  let level = 0;
  while (level < chars.length && known.includes(chars[level])) level++;
  return { known, unsure, level: Math.max(ENTRY_MIN_LEVEL, level), perChar };
}
