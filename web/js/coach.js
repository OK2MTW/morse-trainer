// SPDX-License-Identifier: EUPL-1.2
// Trenér nad lekcemi (M4, bez DOM): potvrzení postupu, zátěž a sezení, dotazník → archetyp, kalibrace, úrovně, plato.
// !!! Python port v tests/coach.py musí zůstat shodný (konstanty a tabulky čte regexem, hlídá tests/test_coach.py).

// ---- potvrzení postupu v dalším sezení (R1: upevnění spánkem) ----
export const CONFIRM_GAP_H = 3;       // další sezení = aspoň 3 h od první lekce s nejnovějším znakem
export const CONFIRM_FROM_LEVEL = 5;  // první 3 přidané znaky (kalibrace, Koch: 4–5 znaků za 30–60 min) bez čekání

/**
 * Smí se přidat další znak? Postup v lekci (advanceCheck) musí platit v jiném sezení, než kdy byl nejnovější
 * znak přidán. history = [{at, level}] včetně právě dokončené lekce, now = ms.
 * Vrací {ok, reason: null | 'confirm', firstAt, waitH}.
 */
export function confirmGate(history, level, now) {
  if (level < CONFIRM_FROM_LEVEL) return { ok: true, reason: null, firstAt: null, waitH: 0 };
  const ats = history.filter((h) => h.level === level).map((h) => Date.parse(h.at)).filter((t) => !Number.isNaN(t));
  const firstAt = ats.length ? Math.min(...ats) : now;
  const ageH = (now - firstAt) / 3600000;
  if (ageH >= CONFIRM_GAP_H) return { ok: true, reason: null, firstAt, waitH: 0 };
  return { ok: false, reason: 'confirm', firstAt, waitH: Math.round((CONFIRM_GAP_H - ageH) * 10) / 10 };
}

// ---- zátěž a sezení (R1 kap. 3) ----
export const BLOCK_MAX_MIN = 10;      // lekce = blok 5–10 min (delší nastavení se zkrátí)
export const SESSION_BREAK_MIN = 20;  // pauza ≥ 20 min ukončí sezení
export const SESSION_END_MIN = 30;    // po 30 min sezení navrhnout konec
export const DAY_WARN_MIN = 60;       // nad 60 min denně upozornit (nezakazovat)
export const WARMUP_S = 90;           // rozcvička 1–2 min na začátku sezení = měření zapamatování
export const FATIGUE_TTR = 1.25;      // únava: medián TTR +25 % proti začátku …
export const FATIGUE_ACC_DROP = 0.1;  // … nebo úspěšnost o 10 p. b. nižší (plná detekce v M5)

/**
 * Zátěž z historie lekcí [{at (konec lekce, ISO), durS}]. now a dayStart (místní půlnoc) v ms.
 * Vrací {sessionMin, dayMin, gapH (od poslední lekce, null = žádná), newSession, suggestEnd, dayWarn}.
 */
export function sessionLoad(history, now, dayStart) {
  const ls = history.map((h) => ({ end: Date.parse(h.at), dur: (h.durS || 0) * 1000 }))
    .filter((x) => !Number.isNaN(x.end) && x.end <= now).sort((a, b) => a.end - b.end);
  let dayMs = 0;
  for (const x of ls) if (x.end >= dayStart) dayMs += Math.min(x.dur, x.end - dayStart);
  const last = ls.at(-1);
  const gapH = last ? (now - last.end) / 3600000 : null;
  const brk = SESSION_BREAK_MIN * 60000;
  let sesMs = 0;
  if (last && now - last.end < brk) {
    sesMs = last.dur;
    for (let i = ls.length - 2; i >= 0; i--) {
      if (ls[i + 1].end - ls[i + 1].dur - ls[i].end >= brk) break;
      sesMs += ls[i].dur;
    }
  }
  const sessionMin = Math.round(sesMs / 6000) / 10;
  const dayMin = Math.round(dayMs / 6000) / 10;
  return {
    sessionMin, dayMin, gapH: gapH === null ? null : Math.round(gapH * 10) / 10,
    newSession: sesMs === 0, suggestEnd: sessionMin >= SESSION_END_MIN, dayWarn: dayMin > DAY_WARN_MIN,
  };
}

/** Rozcvička: souhrn prvních pokusů sezení [{ok, ttr}] → {n, acc, ttr, gapH} pro detail lekce (nebo null). */
export function warmupStats(trials, gapH) {
  if (!trials.length) return null;
  const ok = trials.filter((t) => t.ok && t.ttr != null).map((t) => t.ttr).sort((a, b) => a - b);
  const m = ok.length >> 1;
  const ttr = !ok.length ? null : ok.length % 2 ? ok[m] : Math.round((ok[m - 1] + ok[m]) / 2);
  return {
    n: trials.length, acc: Math.round((trials.filter((t) => t.ok).length / trials.length) * 1000) / 1000,
    ttr, gapH: gapH == null ? null : Math.round(gapH * 10) / 10,
  };
}

/**
 * Příprava detekce únavy (M5): base a cur = {acc, ttr} (začátek sezení vs. posledních ~20 odpovědí).
 * Vrací {tired, ttrUp (poměr), accDrop (p. b. jako podíl)} – zda signál trvá > 1 min, řeší až M5.
 */
export function fatigueSignal(base, cur) {
  if (!base || !cur || base.acc == null || cur.acc == null) return { tired: false, ttrUp: null, accDrop: null };
  const ttrUp = base.ttr && cur.ttr ? Math.round((cur.ttr / base.ttr) * 100) / 100 : null;
  const accDrop = Math.round((base.acc - cur.acc) * 1000) / 1000;
  return { tired: (ttrUp !== null && ttrUp >= FATIGUE_TTR) || accDrop >= FATIGUE_ACC_DROP - 1e-9, ttrUp, accDrop };
}

// ---- průběžná detekce únavy v lekci (M5, R1 kap. 3) ----
export const FATIGUE_BASE_N = 30;      // základ = prvních 30 pokusů sezení (bez rozcvičky)
export const FATIGUE_WIN_N = 20;       // aktuální stav = posledních 20 pokusů
export const FATIGUE_HOLD_S = 60;      // signál musí trvat > 1 min čistého času lekce
export const FATIGUE_ACC_FLOOR = 0.8;  // pokles úspěšnosti platí jen pod pásmem 80–90 % (regulace obtížnosti hýbe úspěšností v pásmu)
export const FATIGUE_SNOOZE_S = 180;   // po „pokračovat“ další návrh nejdřív za 3 min
export const REWARM_PAUSE_MIN = 3;     // pauza v lekci ≥ 3 min → krátká rozcvička
export const REWARM_S = 30;            // … 30 s jen známými znaky, do únavy se nepočítá

export const FATIGUE_REF_MIN_N = 5;   // 0.8.4: referenční reakce znaku z dlouhodobé statistiky od N pokusů
export const FATIGUE_REL_MIN = 8;     // … a relativní TTR v okně/základu aspoň z N pokusů (jinak bez TTR signálu)

/**
 * 0.8.4 (deník #1): TTR pokusu jako poměr k dlouhodobé reakci na STEJNÝ znak (v promile).
 * Mix znaků (rychlý nový znak, velikost sady) tak netvoří falešnou únavu. Nový znak se nepočítá
 * (zpomalení = učení, ne únava). ref = null → původní TTR v ms.
 */
function trialTtr(t, ref, newChar) {
  if (!t.ok || t.ttr == null) return null;
  if (!ref) return t.ttr;
  if (t.ch === newChar || !ref[t.ch]) return null;
  return Math.round((t.ttr * 1000) / ref[t.ch]);
}

function partStats(ts, ref = null, newChar = null) {
  const ok = ts.map((t) => trialTtr(t, ref, newChar)).filter((x) => x !== null).sort((a, b) => a - b);
  const m = ok.length >> 1;
  let ttr = !ok.length ? null : ok.length % 2 ? ok[m] : Math.round((ok[m - 1] + ok[m]) / 2);
  if (ref && ok.length < FATIGUE_REL_MIN) ttr = null;
  return { acc: ts.filter((t) => t.ok).length / ts.length, ttr, n: ts.length, ...(ref ? { rel: true } : {}) };
}

/** Referenční reakce znaků z dlouhodobé statistiky {ch: {n, ttr}} → {ch: ttr} nebo null (nováček). */
export function fatigueRef(prior) {
  const ref = {};
  for (const [c, p] of Object.entries(prior || {})) if (p && p.ttr && p.n >= FATIGUE_REF_MIN_N) ref[c] = p.ttr;
  return Object.keys(ref).length ? ref : null;
}

/**
 * Hlídání únavy během sezení. base = základ z dřívější lekce téhož sezení ({acc, ttr, n}) nebo null.
 * add() po každém pokusu (activeS = čistý čas lekce v s, count = false pro rozcvičku) vrací
 * {propose, kind ('ttr'|'acc'|null), ttrUp, accDrop}. reset() po pauze, snooze() po „pokračovat“.
 */
export class FatigueMonitor {
  /** opts = {ref (fatigueRef), newChar}; základ z jiného režimu (ms × poměr) se nepřebírá. */
  constructor(base = null, { ref = null, newChar = null } = {}) {
    this.ref = ref;
    this.newChar = newChar;
    this.base = base && base.n >= FATIGUE_BASE_N && !!base.rel === !!ref ? base : null;
    this.baseTrials = [];
    this.win = [];
    this.since = null;     // od kdy (activeS) signál trvá
    this.snoozeUntil = 0;
    this.last = { tired: false, held: false, ttrUp: null, accDrop: null };
  }

  reset() { this.win = []; this.since = null; }

  snooze(activeS) { this.snoozeUntil = activeS + FATIGUE_SNOOZE_S; this.since = null; }

  add(trial, activeS, count = true) {
    const none = { propose: false, kind: null, ttrUp: null, accDrop: null };
    if (!count) return none;
    if (!this.base) {
      this.baseTrials.push(trial);
      if (this.baseTrials.length >= FATIGUE_BASE_N) this.base = partStats(this.baseTrials, this.ref, this.newChar);
      return none;
    }
    this.win.push(trial);
    if (this.win.length > FATIGUE_WIN_N) this.win.shift();
    if (this.win.length < FATIGUE_WIN_N) { this.since = null; return none; }
    const cur = partStats(this.win, this.ref, this.newChar);
    const f = fatigueSignal(this.base, cur);
    const ttrTired = f.ttrUp !== null && f.ttrUp >= FATIGUE_TTR;
    const accTired = f.accDrop >= FATIGUE_ACC_DROP - 1e-9 && cur.acc < FATIGUE_ACC_FLOOR - 1e-9;
    this.last = { tired: ttrTired || accTired, held: false, ttrUp: f.ttrUp, accDrop: f.accDrop };
    if (!this.last.tired) { this.since = null; return none; }
    if (this.since === null) this.since = activeS;
    this.last.held = activeS - this.since > FATIGUE_HOLD_S; // 0.8.4: závěrečná hláška jen při trvajícím signálu
    const propose = this.last.held && activeS >= this.snoozeUntil;
    return { propose, kind: ttrTired ? 'ttr' : 'acc', ttrUp: f.ttrUp, accDrop: f.accDrop };
  }
}
