// SPDX-License-Identifier: EUPL-1.2
// Coach over lessons (M4, no DOM): confirmation of advancing, load and sessions, questionnaire → archetype, calibration, levels, plateau.
// !!! The Python port in tests/coach.py must stay identical (it reads constants and tables by regex, checked by tests/test_coach.py).

// ---- confirming progress in the next session (R1: consolidation by sleep) ----
export const CONFIRM_GAP_H = 3;       // next session = at least 3 h after the first lesson with the newest character
export const CONFIRM_FROM_LEVEL = 5;  // the first 3 added characters (calibration, Koch: 4–5 characters in 30–60 min) without waiting

/**
 * May the next character be added? Advancing in a lesson (advanceCheck) must hold in a different session than the one
 * where the newest character was added. history = [{at, level}] including the lesson just finished, now = ms.
 * Returns {ok, reason: null | 'confirm', firstAt, waitH}.
 */
export function confirmGate(history, level, now) {
  if (level < CONFIRM_FROM_LEVEL) return { ok: true, reason: null, firstAt: null, waitH: 0 };
  const ats = history.filter((h) => h.level === level).map((h) => Date.parse(h.at)).filter((t) => !Number.isNaN(t));
  const firstAt = ats.length ? Math.min(...ats) : now;
  const ageH = (now - firstAt) / 3600000;
  if (ageH >= CONFIRM_GAP_H) return { ok: true, reason: null, firstAt, waitH: 0 };
  return { ok: false, reason: 'confirm', firstAt, waitH: Math.round((CONFIRM_GAP_H - ageH) * 10) / 10 };
}

// ---- load and sessions (R1 ch. 3) ----
export const BLOCK_MAX_MIN = 10;      // lesson = a block of 5–10 min (a longer setting is shortened)
export const SESSION_BREAK_MIN = 20;  // a break ≥ 20 min ends the session
export const SESSION_END_MIN = 30;    // suggest stopping after a 30 min session
export const DAY_WARN_MIN = 60;       // warn above 60 min a day (do not forbid)
export const WARMUP_S = 90;           // warm-up of 1–2 min at the start of a session = retention measurement
export const FATIGUE_TTR = 1.25;      // fatigue: median TTR +25 % compared with the start …
export const FATIGUE_ACC_DROP = 0.1;  // … or accuracy 10 points lower (full detection in M5)

/**
 * Load from the lesson history [{at (end of the lesson, ISO), durS}]. now and dayStart (local midnight) in ms.
 * Returns {sessionMin, dayMin, gapH (since the last lesson, null = none), newSession, suggestEnd, dayWarn}.
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

/** Warm-up: summary of the first trials of a session [{ok, ttr}] → {n, acc, ttr, gapH} for the lesson detail (or null). */
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
 * Fatigue detection groundwork (M5): base and cur = {acc, ttr} (start of the session vs. the last ~20 answers).
 * Returns {tired, ttrUp (ratio), accDrop (points as a fraction)} – whether the signal lasts > 1 min is handled in M5.
 */
export function fatigueSignal(base, cur) {
  if (!base || !cur || base.acc == null || cur.acc == null) return { tired: false, ttrUp: null, accDrop: null };
  const ttrUp = base.ttr && cur.ttr ? Math.round((cur.ttr / base.ttr) * 100) / 100 : null;
  const accDrop = Math.round((base.acc - cur.acc) * 1000) / 1000;
  return { tired: (ttrUp !== null && ttrUp >= FATIGUE_TTR) || accDrop >= FATIGUE_ACC_DROP - 1e-9, ttrUp, accDrop };
}

// ---- continuous fatigue detection in a lesson (M5, R1 ch. 3) ----
export const FATIGUE_BASE_N = 30;      // baseline = the first 30 trials of the session (without the warm-up)
export const FATIGUE_WIN_N = 20;       // current state = the last 20 trials
export const FATIGUE_HOLD_S = 60;      // the signal must last > 1 min of net lesson time
export const FATIGUE_ACC_FLOOR = 0.8;  // an accuracy drop only counts below the 80–90 % band (difficulty control moves accuracy within the band)
export const FATIGUE_SNOOZE_S = 180;   // after "continue" the next proposal at the earliest in 3 min
export const REWARM_PAUSE_MIN = 3;     // a break in a lesson ≥ 3 min → a short warm-up
export const REWARM_S = 30;            // … 30 s of known characters only, not counted for fatigue

export const FATIGUE_REF_MIN_N = 5;   // 0.8.4: reference reaction of a character from long-term statistics from N trials
export const FATIGUE_REL_MIN = 8;     // … and relative TTR in the window/baseline from at least N trials (otherwise no TTR signal)

/**
 * 0.8.4 (log #1): TTR of a trial as a ratio to the long-term reaction to the SAME character (per mille).
 * The character mix (a fast new character, set size) thus does not create false fatigue. The new character does not
 * count (slowing down = learning, not fatigue). ref = null → the original TTR in ms.
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

/**
 * 0.9.8 (validation #17, Z-17): pace of the whole lesson against the user's long-term reaction to the same characters.
 * Median of TTR / reference over correct answers after the warm-up; the newest character counts too once it has its own
 * reference (it already reflects the learning phase). Returns the ratio, or null with fewer than SLOW_DAY_MIN_N trials.
 * Backtest 2026-11-06 (Martin): very tired evenings 1.29 / 1.32, normal mornings 0.98 / 1.07.
 */
export const SLOW_DAY = 1.2;
export const SLOW_DAY_MIN_N = 30;
export function lessonPace(trials, ref, newChar = null) {
  if (!ref) return null;
  const r = trials.filter((t) => t.ok && t.ttr != null && t.ch !== newChar && ref[t.ch])
    .map((t) => t.ttr / ref[t.ch]).sort((a, b) => a - b);
  if (r.length < SLOW_DAY_MIN_N) return null;
  const m = r.length >> 1;
  return r.length % 2 ? r[m] : (r[m - 1] + r[m]) / 2;
}

/**
 * 0.10.5 (Z-17, validation #17) – SHADOW MODE: fatigue against the user's long-term reaction during a lesson.
 * The session-start baseline of FatigueMonitor cannot see fatigue that is there from the start, and its 20-trial window
 * jumps. PaceWatch compares the last PACE_WIN_N counted trials with the long-term reaction to the same characters
 * (window median of TTR / ref ≥ PACE_ON switches the signal on, it lasts until it drops below PACE_OFF) and counts
 * lapses (a wrong answer or a reaction ≥ LAPSE_X × the usual one; ≥ LAPSE_N of the last LAPSE_WIN_N switch it on too).
 * A signal lasting > PACE_HOLD_S would be a pause proposal. Backtest 2026-11-07 (5 traced lessons of the owner): tired
 * evenings at 3.6 / 4.9 min, normal mornings never (max 1.17, 3 lapses). Owner's decision 2026-11-07: shadow only –
 * written to the debug trace, no proposal; switched on after evaluation of more evenings.
 */
export const PACE_WIN_N = 40;
export const PACE_MIN_REL = 20;  // window median only from ≥ 20 relative reactions
export const PACE_ON = 1.3;
export const PACE_OFF = 1.15;
export const LAPSE_X = 2;
export const LAPSE_WIN_N = 20;
export const LAPSE_N = 6;
export const PACE_HOLD_S = 60;

export class PaceWatch {
  /** ref = fatigueRef(prior); without it (beginner) the watch stays silent. */
  constructor(ref) {
    this.ref = ref || null;
    this.events = []; // {t, med, lapses} – would-be proposals
    this.max = { med: null, lapses: 0 };
    this.reset();
  }

  /** After a pause (and after a would-be proposal) the measurement starts anew. */
  reset() { this.win = []; this.since = null; this.on = false; }

  _rel(t) { return t.ok && t.ttr != null && this.ref[t.ch] ? t.ttr / this.ref[t.ch] : null; }

  /** After each trial (count = false in the warm-up). Returns {propose, med, lapses}. */
  add(trial, activeS, count = true) {
    const none = { propose: false, med: null, lapses: 0 };
    if (!this.ref || !count) return none;
    this.win.push(trial);
    if (this.win.length > Math.max(PACE_WIN_N, LAPSE_WIN_N)) this.win.shift();
    const rs = this.win.slice(-PACE_WIN_N).map((t) => this._rel(t)).filter((x) => x !== null).sort((a, b) => a - b);
    const m = rs.length >> 1;
    const med = rs.length < PACE_MIN_REL ? null : rs.length % 2 ? rs[m] : (rs[m - 1] + rs[m]) / 2;
    const last = this.win.slice(-LAPSE_WIN_N);
    const lapses = last.filter((t) => { const r = this._rel(t); return !t.ok || (r !== null && r >= LAPSE_X); }).length;
    if (med !== null && med > (this.max.med ?? 0)) this.max.med = med;
    if (last.length >= LAPSE_WIN_N && lapses > this.max.lapses) this.max.lapses = lapses;
    const sigOn = (med !== null && med >= PACE_ON) || (last.length >= LAPSE_WIN_N && lapses >= LAPSE_N);
    if (!this.on && sigOn) { this.on = true; this.since = activeS; }
    else if (this.on && !sigOn && !(med !== null && med >= PACE_OFF)) { this.on = false; this.since = null; }
    const propose = this.on && activeS - this.since > PACE_HOLD_S;
    if (propose) { this.events.push({ t: activeS, med, lapses }); this.reset(); }
    return { propose, med, lapses };
  }
}

/** Reference reactions of characters from long-term statistics {ch: {n, ttr}} → {ch: ttr} or null (beginner). */
export function fatigueRef(prior) {
  const ref = {};
  for (const [c, p] of Object.entries(prior || {})) if (p && p.ttr && p.n >= FATIGUE_REF_MIN_N) ref[c] = p.ttr;
  return Object.keys(ref).length ? ref : null;
}

/**
 * Fatigue watch during a session. base = baseline from an earlier lesson of the same session ({acc, ttr, n}) or null.
 * add() after each trial (activeS = net lesson time in s, count = false for the warm-up) returns
 * {propose, kind ('ttr'|'acc'|null), ttrUp, accDrop}. reset() after a pause, snooze() after "continue".
 */
export class FatigueMonitor {
  /** opts = {ref (fatigueRef), newChar}; a baseline from another mode (ms × ratio) is not taken over. */
  constructor(base = null, { ref = null, newChar = null } = {}) {
    this.ref = ref;
    this.newChar = newChar;
    this.base = base && base.n >= FATIGUE_BASE_N && !!base.rel === !!ref ? base : null;
    this.baseTrials = [];
    this.win = [];
    this.since = null;     // since when (activeS) the signal lasts
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
    this.last.held = activeS - this.since > FATIGUE_HOLD_S; // 0.8.4: the final message only with a lasting signal
    const propose = this.last.held && activeS >= this.snoozeUntil;
    return { propose, kind: ttrTired ? 'ttr' : 'acc', ttrUp: f.ttrUp, accDrop: f.accDrop };
  }
}
