// SPDX-License-Identifier: EUPL-1.2
// Příjem ve skluzu (M7, M8) – čistá logika bez DOM: zarovnání napsaného textu k vyslanému, skluz (ve znacích
// i slovech), výsledky slov, únava po řádcích. Python port: tests/copy.py (testy hlídají shodu konstant).
// Návrh: docs/requirements.md „Návrh M7“ a „Návrh M8“.

export const ROUND_ITEMS = 6;        // položek (skupin/slov) v jednom řádku
export const ROUND_TAIL_MS = 3000;   // řádek končí 3 s po posledním tónu (nejméně 2× mezera mezi slovy)
export const COPY_MIN_CHARS = 60;    // sezení se hodnotí od 60 vyslaných znaků (shodně se server/coach.py)
// M8: únava ve skluzu – vyhodnocení po řádku (řádek je přirozená zastávka, proud se nepřerušuje)
export const FAT_BASE_ROUNDS = 3;    // základ = první 3 řádky lekce
export const FAT_WIN_ROUNDS = 2;     // aktuální stav = poslední 2 řádky
export const FAT_ACC_DROP = 0.1;     // úspěšnost o ≥ 10 p. b. nižší …
export const FAT_ACC_FLOOR = 0.8;    // … a pod 80 % (jako FatigueMonitor v M5)
export const FAT_MISS_UP = 0.1;      // nebo podíl chybějících znaků o ≥ 10 p. b. vyšší (ztráta proudu)
export const FAT_HOLD_S = 60;        // signál musí trvat > 1 min čistého času
export const FAT_SNOOZE_S = 180;     // po „pokračovat“ další návrh nejdřív za 3 min

// Pořadí při shodné ceně cesty zpět: správně > záměna > chybí > navíc (deterministické hodnocení).
/**
 * Zarovná napsané znaky k vyslaným (Levenshtein). sent, typed = pole znaků (bez mezer).
 * Vrací operace [{op: 'ok'|'sub'|'del'|'ins', s: index vyslaného|null, t: index napsaného|null}] v pořadí textu.
 * 'del' = vyslaný znak chybí v zápisu, 'ins' = napsaný znak navíc.
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

/** Počty operací, úspěšnost po zarovnání a záměny {`S→H`: n}. */
export function score(ops, sent, typed) {
  const c = { ok: 0, sub: 0, del: 0, ins: 0 };
  const conf = {};
  for (const o of ops) {
    c[o.op]++;
    if (o.op === 'sub') {
      const k = `${sent[o.s]}→${typed[o.t]}`;
      conf[k] = (conf[k] || 0) + 1;
    }
  }
  const den = sent.length + c.ins;
  return { ...c, n: sent.length, acc: den ? c.ok / den : null, conf };
}

export function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const h = s.length >> 1;
  return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
}

/** Percentil p (0–1), nejbližší hodnota zdola (bez interpolace – stejné v Pythonu). */
export function percentile(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

/**
 * Skluz pro spárované znaky (ok i záměna). ends[i] = konec tónu vyslaného znaku i (ms, performance.now),
 * times[j] = čas stisku napsaného znaku j. Vrací [{s, ms, ch}] – ms za koncem znaku, ch = kolik dalších
 * vyslaných znaků už dozvučelo.
 */
export function lagSamples(ops, ends, times, wordOf = null) {
  // M8: wordOf (slovo každého vyslaného znaku) → i skluz ve slovech: kolik dalších slov už dozvučelo
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

/** Souhrn skluzu: medián/p90 v ms a znacích, max. znaků, drift (poslední třetina − první, ve znacích). */
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
 * Výsledky slov: words = pole slov (řetězce), ops nad spojenými znaky. Slovo je správně, když jsou správně
 * všechny jeho znaky a uvnitř slova nic navíc. Vrací pole true/false.
 */
export function wordResults(words, ops) {
  const wordOf = [];
  words.forEach((wd, k) => { for (let i = 0; i < wd.length; i++) wordOf.push(k); });
  const ok = words.map(() => true);
  // slovo dalšího vyslaného znaku za každou operací (odzadu)
  const nextWord = new Array(ops.length).fill(-1);
  for (let k = ops.length - 1, nw = -1; k >= 0; k--) {
    nextWord[k] = nw;
    if (ops[k].s !== null) nw = wordOf[ops[k].s];
  }
  let lastWord = -1;
  ops.forEach((o, k) => {
    if (o.s !== null) {
      lastWord = wordOf[o.s];
      if (o.op !== 'ok') ok[lastWord] = false;
    } else if (lastWord >= 0 && nextWord[k] === lastWord) {
      ok[lastWord] = false; // navíc uvnitř slova (na hranici slov se nepočítá ani jednomu)
    }
  });
  return ok;
}

/**
 * Řádek → vstupy pro hodnocení. chars = [{ch, w, end}] z playStream, typed = [{ch, t}] (bez mezer).
 * Vrací {ops, sc, lags, words(ok[])} – použije se po řádku i pro průběžné značky slov.
 */
export function evaluate(words, chars, typed) {
  const sent = chars.map((c) => c.ch);
  const tch = typed.map((x) => x.ch);
  const ops = align(sent, tch);
  return {
    ops, sc: score(ops, sent, tch),
    lags: lagSamples(ops, chars.map((c) => c.end), typed.map((x) => x.t), chars.map((c) => c.w)),
    words: wordResults(words, ops),
  };
}

/** Souhrn lekce z řádků [{words, chars, typed, ev}] → detail.copy (bez kroku a obsahu – doplní volající). */
export function lessonSummary(rounds) {
  const c = { ok: 0, sub: 0, del: 0, ins: 0, n: 0 };
  const conf = {};
  const lags = [];
  let wn = 0;
  let wok = 0;
  for (const r of rounds) {
    for (const k of ['ok', 'sub', 'del', 'ins', 'n']) c[k] += r.ev.sc[k];
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

// ---------- únava ve skluzu (M8) ----------
function roundStats(list) {
  let ok = 0; let n = 0; let ins = 0; let del = 0;
  for (const x of list) { ok += x.ok; n += x.n; ins += x.ins; del += x.del; }
  return { acc: n + ins ? ok / (n + ins) : 0, miss: n ? del / n : 0, n };
}

/**
 * Hlídání únavy v lekci ve skluzu – po každém řádku add(sc, startS, endS): sc = skóre řádku {ok, n, ins, del},
 * startS/endS = čistý čas lekce na začátku a konci řádku. Vrací {propose, kind ('acc'|'miss'|null), accDrop, missUp}.
 * Skluz se jako únava nebere (v U4 je delší skluz cílem). reset() po pauze, snooze() po „pokračovat“.
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
    if (this.since === null) this.since = this.win[0].startS; // signál platí za celé okno
    const propose = endS - this.since > FAT_HOLD_S && endS >= this.snoozeUntil;
    return { propose, kind: accTired ? 'acc' : 'miss', accDrop, missUp };
  }
}
