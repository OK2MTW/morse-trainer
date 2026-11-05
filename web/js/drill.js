// SPDX-License-Identifier: EUPL-1.2
// Logika trenéra (bez DOM): výběr znaků, záznam odpovědí, vyhodnocení, Kochův postup, rozlišování.
// !!! Python port v tests/trainer.py musí zůstat shodný (konstanty kontroluje tests/test_trainer.py).
import { KOCH_ORDER, MORSE } from './charset.js';

export const ADVANCE_WINDOW = 40;     // posledních N znaků pro rozhodnutí o postupu
export const ADVANCE_ACCURACY = 0.9;  // Kochův práh 90 %
export const NEW_MIN_N = 8;           // nejnovější znak musí v lekci zaznít aspoň N×
export const NEW_ACCURACY = 0.85;     // … s úspěšností aspoň 85 %
export const NEW_TTR_RATIO = 1.5;     // … a mediánem reakce nejvýš 1,5× medián ostatních znaků
export const PRIOR_N = 3;             // váha dlouhodobé statistiky ve výběru znaků (pseudo-pokusy)
export const PRIOR_MIN_N = 5;         // dlouhodobou statistiku znaku bereme od N pokusů
export const DEFAULT_ERR = 0.3;       // odhad chybovosti znaku bez historie
export const DISCRIM_TRIALS = 12;     // pokusy rozlišování po seznámení s novým znakem
export const TREND_MIN_N = 10;        // trend až z N pokusů ve srovnávacím období
export const TREND_MIN_CUR = 5;       // … a aspoň N v hodnoceném období
// M4 (závěry R1)
export const MIN_WPM = 12;            // tvrdá mez rychlosti znaku (Koch ≥ 10 WPM, rezerva)
export const DISCRIM_SIMILAR_FROM = 17; // nejpodobnější páry (S/H, U/V, D/B) v rozlišování až od ~1/3 sady
export const MAINTAIN_MIN = 0.15;     // podíl zvládnutých znaků v mixu (udržování) – dolní mez
export const MAINTAIN_MAX = 0.2;      // … horní mez (přeučování se nevyplácí)
export const MASTER_MIN_N = 20;       // zvládnutý znak: dlouhodobě aspoň N pokusů
export const MASTER_ACC = 0.9;        // … s úspěšností aspoň 90 % a v lekci nejvýš 1 chyba z posledních 10
export const SCATTER_MIN_CHARS = 4;   // nový znak nikdy 2× za sebou (od N znaků v sadě)
// Regulace obtížnosti v lekci (smyčka a): cíl ~85 %, pásmo 80–90 % (Wilson 2019)
export const BAND_LO = 0.8;
export const BAND_HI = 0.9;
export const DIFF_WINDOW = 20;        // úspěšnost posledních N znaků
export const DIFF_EVERY = 5;          // upravit nejčastěji po N znacích
export const DIFF_STEP = 0.15;        // krok exponentu vah
export const DIFF_MIN = 0.4;          // ploché váhy = lehčí (víc známých znaků)
export const DIFF_MAX = 2.5;          // ostré váhy = těžší (víc slabých a nového znaku)
export const MAINTAIN_EASY_MAX = 0.3; // při nejlehčím nastavení smí zvládnuté znaky tvořit až 30 %
// Postup (smyčka b): k 90 % i stabilní reakce
export const TTR_STABLE_RATIO = 1.25; // medián TTR 2. poloviny okna nejvýš 1,25× 1. poloviny
export const STABLE_REL_MIN = 5;     // 0.8.4: TTR vůči stejnému znaku (bez nového), když má každá polovina aspoň N pokusů
// 0.8.4 (deník #4, #5): vyváženější mix – nový znak nepřeválcuje opakování, slabé a zaměňované znaky častěji
export const NEW_SHARE_MAX = 0.3;    // nový znak nejvýš 30 % vah (dřív prakticky každý 2. znak)
export const CONF_BONUS = 0.25;      // váha navíc za každou záměnu znaku (oběma směry, dlouhodobá statistika) …
export const CONF_CAP = 4;           // … započítá se nejvýš N záměn
// M6: poslední záchrana v lekci – když mix už ulehčit nejde (diff = DIFF_MIN) a úspěšnost je pod 75 %,
// prodlouží se mezery (Farnsworth) o GAP_EASE_STEP WPM, nejvýš GAP_EASE_MAX kroky, jen v této lekci (R1 kap. 1)
export const GAP_EASE_ACC = 0.75;
export const GAP_BACK_ACC = 0.85;    // od 85 % se mezery vracejí o krok zpět
export const GAP_EASE_MAX = 2;
export const GAP_EASE_STEP = 2;      // WPM efektivní rychlosti na krok
export const GAP_EVERY = 10;         // nejčastěji po N znacích
export const FW_MIN = 5;             // nejdelší mezery (shodně se server/coach.py)

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
   * @param {string[]} chars  aktuální sada znaků
   * @param {string|null} newChar  nejnovější znak (chodí častěji, hlídá se při postupu)
   * @param {{rng?: Function, prior?: Object}} opts  prior = dlouhodobá statistika {ch: {n, acc, ttr}} ze serveru
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
    this.diff = 1;          // exponent vah: > 1 těžší, < 1 lehčí
    this.diffAt = 0;        // počet pokusů při poslední úpravě
    this.diffLog = [];      // [pokus, diff] – změny pro detail lekce
    this.gapEase = 0;       // M6: počet kroků prodloužení mezer v lekci
    this.gapAt = 0;
    this.gapLog = [];       // [pokus, gapEase]
    this.exclude = new Set(); // dočasně vynechané znaky (rozcvička jen známými znaky)
    // 0.8.4: záměny z dlouhodobé statistiky oběma směry (W→J zvýší W i J)
    this.confN = Object.fromEntries(chars.map((c) => [c, 0]));
    for (const [c, p] of Object.entries(this.prior)) {
      for (const x of p?.conf || []) {
        if (c in this.confN) this.confN[c] += x.n || 0;
        if (x.ans in this.confN) this.confN[x.ans] += x.n || 0;
      }
    }
  }

  /** Rozcvička: vynechat znaky (jen když zbydou aspoň 2). Prázdný seznam = konec vynechávání. */
  setExclude(list) {
    const rest = this.chars.filter((c) => !list.includes(c));
    this.exclude = new Set(rest.length >= 2 ? list : []);
  }

  /** Smyčka a: úspěšnost posledních DIFF_WINDOW znaků držet v pásmu 80–90 %. */
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
    // M6: mezery až když mix už ulehčit nejde
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

  /** Efektivní rychlost mezer v lekci (WPM) pro nastavené fwpm. */
  lessonFwpm(fwpm) {
    return this.gapEase ? Math.max(FW_MIN, Math.min(fwpm, fwpm - GAP_EASE_STEP * this.gapEase)) : fwpm;
  }

  /** Dlouhodobá chybovost znaku (nebo výchozí odhad). */
  priorErr(c) {
    const p = this.prior[c];
    return p && p.n >= PRIOR_MIN_N && p.acc != null ? 1 - p.acc : DEFAULT_ERR;
  }

  /** Váha znaku: chybovost a pomalá reakce zvyšují četnost. Začíná z dlouhodobé statistiky. */
  weight(c) {
    if (this.exclude.has(c)) return 0;
    const s = this.stats[c];
    const recent = this.trials.filter((t) => t.ch === c).slice(-10);
    const errs = recent.filter((t) => !t.ok).length;
    const err = (errs + PRIOR_N * this.priorErr(c)) / (recent.length + PRIOR_N);
    // 0.8.4: pomalost proti starým znakům – rychlý (předvídatelný) nový znak by srovnání zkreslil
    const all = median(this.trials.filter((t) => t.ok && t.ttr != null && t.ch !== this.newChar).map((t) => t.ttr));
    const mine = median(s.ttrs.slice(-10));
    let slow = 1;
    if (all && mine) slow = mine / all;
    else if (this.priorTtr && this.prior[c]?.ttr && this.prior[c].n >= PRIOR_MIN_N) slow = this.prior[c].ttr / this.priorTtr;
    slow = Math.min(2, Math.max(0.5, slow));
    let w = 1 + 4 * err + 1.5 * (slow - 1) + CONF_BONUS * Math.min(CONF_CAP, this.confN[c] || 0);
    if (c === this.newChar) {
      w *= 1.8;
      // nový znak rozptýlit mezi známé – nikdy dvakrát za sebou
      if (this.chars.length >= SCATTER_MIN_CHARS && this.trials.at(-1)?.ch === c) w = 0;
    }
    // stejný znak nejvýš 2× za sebou
    const last2 = this.trials.slice(-2).map((t) => t.ch);
    if (last2.length === 2 && last2[0] === c && last2[1] === c) w = 0;
    return Math.max(0, w);
  }

  /** Zvládnutý znak (jen udržování): dlouhodobě ≥ 90 % z ≥ 20 pokusů a v lekci nejvýš 1 chyba z posledních 10. */
  isMastered(c) {
    if (c === this.newChar) return false;
    const p = this.prior[c];
    if (!p || p.n < MASTER_MIN_N || p.acc == null || p.acc < MASTER_ACC) return false;
    return this.trials.filter((t) => t.ch === c).slice(-10).filter((t) => !t.ok).length < 2;
  }

  /** Váhy výběru: podíl zvládnutých znaků se drží v pásmu MAINTAIN_MIN–MAINTAIN_MAX. */
  mixWeights() {
    const ws = this.chars.map((c) => this.weight(c) ** this.diff);
    const m = this.chars.map((c) => this.isMastered(c));
    let sM = 0, sA = 0;
    ws.forEach((w, i) => { if (m[i]) sM += w; else sA += w; });
    if (sM > 0 && sA > 0) {
      const share = sM / (sM + sA);
      // při ulehčování (diff < 1) smí být zvládnutých znaků víc – úspěch pomáhá
      const easy = Math.max(0, Math.min(1, (1 - this.diff) / (1 - DIFF_MIN)));
      const max = MAINTAIN_MAX + easy * (MAINTAIN_EASY_MAX - MAINTAIN_MAX);
      const goal = Math.min(max, Math.max(MAINTAIN_MIN, share));
      if (goal !== share) {
        const f = (goal * sA) / ((1 - goal) * sM);
        for (let i = 0; i < ws.length; i++) if (m[i]) ws[i] *= f;
      }
    }
    // 0.8.4: strop podílu nového znaku
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

  /** Úspěšnost v posledních ADVANCE_WINDOW znacích, nebo null pokud jich je málo. */
  recentAccuracy() {
    if (this.trials.length < ADVANCE_WINDOW) return null;
    const w = this.trials.slice(-ADVANCE_WINDOW);
    return w.filter((t) => t.ok).length / w.length;
  }

  /**
   * 0.8.4 (deník #1): mediány TTR dvou polovin okna. Přednostně jako poměr k dlouhodobé reakci na stejný znak
   * bez nového znaku (mix a velikost sady nezkreslí), jinak (málo dat) prosté TTR.
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
   * Kochův postup: ≥ 90 % v posledních 40 znacích A nejnovější znak ≥ 85 % (aspoň 8×)
   * A jeho medián reakce ≤ 1,5× medián ostatních. reason = první nesplněná podmínka.
   */
  advanceCheck() {
    const r = { ok: false, reason: null, recent: this.recentAccuracy(), newChar: this.newChar, newN: 0, newAcc: null, newTtr: null, othersTtr: null };
    if (r.recent === null) { r.reason = 'few'; return r; }
    if (r.recent < ADVANCE_ACCURACY) { r.reason = 'acc'; return r; }
    // stabilní reakce: v druhé polovině okna se TTR nezhoršuje (jinak únava / nejistota)
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
 * Trend znaku: cur a base = {n, acc, ttr}. Vrací 'up' | 'down' | 'flat', nebo null (málo dat).
 * Používá výsledek lekce (lekce vs. dlouhodobě) i karta Statistika (posledních 5 lekcí vs. předchozí).
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

/** Editační vzdálenost dvou kódů (tečky/čárky) – míra zvukové podobnosti. */
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
 * Znaky, se kterými se nový znak procvičí v rozlišování: nejdřív ty, se kterými se už zaměňoval
 * (conf = {znak: počet záměn oběma směry}), pak zvukově nejpodobnější, při shodě později naučený.
 * Do 1/3 sady (setSize < DISCRIM_SIMILAR_FROM) se nejpodobnější znaky (vzdálenost kódu ≤ 1) nestaví proti sobě,
 * pokud je uživatel skutečně nezaměňuje (Koch, R1).
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

/** Pořadí pokusů rozlišování: polovina nové znaky, polovina kontrastní, náhodně, nejvýš 2× stejný za sebou. */
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
