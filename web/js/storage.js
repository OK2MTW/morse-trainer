// SPDX-License-Identifier: EUPL-1.2
// Data uživatele: hlavní kopie na serveru (SQLite), v prohlížeči offline cache + fronta neodeslaných změn.
// Lekce se ukládají vždy nejdřív lokálně a odešlou se, až je server dostupný (mají UUID → odeslání je idempotentní).
import { api } from './api.js';
import { MIN_WPM } from './drill.js';
import { BLOCK_MAX_MIN } from './coach.js';

const KEY_USER = 'morse-user';            // naposledy přihlášený uživatel (kvůli offline startu)
const KEY_DEVICE = 'morse-device';         // nastavení jen pro toto zařízení (hlasitost)
const cacheKey = (uid) => `morse-cache-${uid}`;
const LEGACY = ['morse-settings', 'morse-progress', 'morse-m0-settings']; // M0/M1 bez účtu

export const DEFAULT_SETTINGS = { wpm: 20, fwpm: 15, freq: 600, volume: 0.7, lessonMin: 5, autoSpeed: 1 };
export const DEFAULT_PROGRESS = { level: 2, introduced: [], history: [] };
const SYNCED_SETTINGS = ['wpm', 'fwpm', 'freq', 'lessonMin', 'autoSpeed'];
const HISTORY_MAX = 500;

/** Tvrdá mez rychlosti znaku (R1): starší uložené nastavení pod 12 WPM se zvedne. */
function clampSettings() {
  if (!(settings.wpm >= MIN_WPM)) settings.wpm = Math.max(MIN_WPM, Number(settings.wpm) || DEFAULT_SETTINGS.wpm);
  if (settings.fwpm > settings.wpm) settings.fwpm = settings.wpm;
  if (settings.lessonMin > BLOCK_MAX_MIN) settings.lessonMin = BLOCK_MAX_MIN; // blok 5–10 min (R1)
}

function read(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
}

// Sdílené objekty – main.js je mění přímo a pak volá save*().
export const settings = { ...DEFAULT_SETTINGS };
export const progress = { ...DEFAULT_PROGRESS, introduced: [], history: [] };
// Statistika znaků ze serveru (GET /api/stats) – jen čtená cache, počítá ji server z posledních lekcí.
export const stats = { lessons: 0, chars: {}, at: null };
// Trenér ze serveru (GET /api/coach, M4): archetyp, modifikátory, preference, plán, úroveň U1–U6, plato.
export const coachInfo = { data: null };
export const sync = { canTrain: true, epoch: null, uid: null, dirtySettings: false, dirtyProgress: false, outbox: [], lastSync: null, error: null };
let listeners = [];
export function onDataChange(fn) { listeners.push(fn); }
const notify = () => listeners.forEach((fn) => fn());

/** Nový výsledek dotazníku (nebo plánu) ze serveru → cache. */
export function setCoachInfo(d) { coachInfo.data = d; persist(); notify(); }

export const cachedUser = () => read(KEY_USER);
export function rememberUser(user) { write(KEY_USER, user); }

function persist() {
  if (sync.uid == null) return;
  write(cacheKey(sync.uid), {
    settings: Object.fromEntries(SYNCED_SETTINGS.map((k) => [k, settings[k]])),
    progress: { level: progress.level, introduced: progress.introduced, history: progress.history },
    dirtySettings: sync.dirtySettings, dirtyProgress: sync.dirtyProgress, outbox: sync.outbox, lastSync: sync.lastSync,
    epoch: sync.epoch, stats, coach: coachInfo.data,
  });
}

/** Načte cache uživatele (bez sítě). */
export function openUser(uid) {
  sync.uid = uid;
  const c = read(cacheKey(uid)) || {};
  const dev = read(KEY_DEVICE) || {};
  Object.assign(settings, DEFAULT_SETTINGS, c.settings || {}, dev.volume ? { volume: dev.volume } : {});
  clampSettings();
  const p = c.progress || {};
  progress.level = p.level || DEFAULT_PROGRESS.level;
  progress.introduced = Array.isArray(p.introduced) ? p.introduced : [];
  progress.history = Array.isArray(p.history) ? p.history : [];
  sync.dirtySettings = !!c.dirtySettings;
  sync.dirtyProgress = !!c.dirtyProgress;
  sync.outbox = Array.isArray(c.outbox) ? c.outbox : [];
  sync.lastSync = c.lastSync || null;
  sync.epoch = Number.isInteger(c.epoch) ? c.epoch : null;
  sync.error = null;
  setStats(c.stats);
  coachInfo.data = c.coach && typeof c.coach === 'object' ? c.coach : null;
}

/** Výcvik byl resetován (zde nebo na jiném zařízení) – zahodit lokální pokrok, historii i neodeslané lekce. */
function setStats(st) {
  stats.lessons = st?.lessons || 0;
  stats.chars = st?.chars && typeof st.chars === 'object' ? st.chars : {};
  stats.at = st?.at || null;
}

function wipeTraining() {
  setStats(null);
  progress.level = DEFAULT_PROGRESS.level;
  progress.introduced = [];
  progress.history = [];
  sync.outbox = [];
  sync.dirtyProgress = false;
}

/** Reset vlastního výcviku (potvrzeno heslem). Nastavení zůstává. */
export async function resetTraining(password) {
  const { epoch } = await api('POST', '/training/reset', { password });
  wipeTraining();
  sync.epoch = epoch;
  persist();
  notify();
}

/** Odhlášení: smaže data uživatele z tohoto zařízení (sdílený počítač). */
export function forgetUser() {
  if (sync.uid != null) localStorage.removeItem(cacheKey(sync.uid));
  localStorage.removeItem(KEY_USER);
  sync.uid = null;
  sync.outbox = [];
  setStats(null);
}

export function saveSettings() {
  write(KEY_DEVICE, { volume: settings.volume });
  sync.dirtySettings = true;
  persist();
  scheduleSync();
}

export function saveProgress() {
  sync.dirtyProgress = true;
  persist();
  scheduleSync();
}

const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
  : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join(''));

/** Uloží výsledek lekce (lokálně ihned, na server při nejbližší synchronizaci). */
export function addLesson(entry) {
  const h = { id: uuid(), ...entry };
  const { detail, ...compact } = h; // detail po znacích jen na server, lokální historie zůstane malá
  progress.history.push(compact);
  if (progress.history.length > HISTORY_MAX) progress.history = progress.history.slice(-HISTORY_MAX);
  sync.outbox.push(h);
  saveProgress();
  return h;
}

/** Data z M1 (bez účtu) v tomto prohlížeči – sloučí se do účtu, který se tu přihlásí jako první. */
function legacyData() {
  const p = read('morse-progress');
  if (!p || (!(p.history?.length) && !(p.level > 2))) return null;
  return { settings: read('morse-settings') || read('morse-m0-settings') || {}, progress: p };
}

let syncTimer = null;
let syncing = null;
function scheduleSync(ms = 1500) {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => { syncNow().catch(() => {}); }, ms);
}

/** Odešle změny a stáhne aktuální stav ze serveru. Vrací info o převodu M1 dat (nebo null). */
export function syncNow() {
  if (!syncing) syncing = doSync().finally(() => { syncing = null; });
  return syncing;
}

async function doSync() {
  if (sync.uid == null) return null;
  const uid = sync.uid;
  try {
    // 1) odeslat (po dávkách max. 200 lekcí)
    while (sync.outbox.length) {
      const batch = sync.outbox.slice(0, 200);
      const { saved } = await api('POST', '/lessons', { lessons: batch, epoch: sync.epoch });
      const ok = new Set(saved);
      // i odmítnuté (neplatné) lekce z fronty vyřadíme, jinak by se posílaly donekonečna
      const sent = new Set(batch.map((x) => x.id));
      sync.outbox = sync.outbox.filter((x) => !sent.has(x.id));
      if (ok.size !== sent.size) console.warn('Server odmítl některé lekce');
    }
    // příznak shodíme před odesláním (změna během čekání ho znovu nastaví), při chybě vrátíme
    if (sync.dirtySettings) {
      sync.dirtySettings = false;
      try {
        await api('PUT', '/settings', { settings: Object.fromEntries(SYNCED_SETTINGS.map((k) => [k, settings[k]])) });
      } catch (e) { sync.dirtySettings = true; throw e; }
    }
    if (sync.dirtyProgress) {
      sync.dirtyProgress = false;
      try {
        await api('PUT', '/progress', { level: progress.level, introduced: progress.introduced, epoch: sync.epoch });
      } catch (e) { sync.dirtyProgress = true; throw e; }
    }
    // 2) stáhnout
    const d = await api('GET', '/data');
    if (sync.uid !== uid) return null; // mezitím odhlášen
    if (sync.epoch !== null && d.epoch !== sync.epoch) wipeTraining(); // reset z jiného zařízení
    sync.epoch = d.epoch;
    const legacy = legacyData();
    if (legacy && sync.canTrain) return await importLegacy(legacy, d);
    if (d.settings && !sync.dirtySettings) { Object.assign(settings, d.settings); clampSettings(); }
    if (d.progress && !sync.dirtyProgress) {
      progress.level = d.progress.level;
      progress.introduced = d.progress.introduced;
    }
    const pending = sync.outbox;
    const ids = new Set(d.lessons.map((x) => x.id));
    progress.history = [...d.lessons, ...pending.filter((x) => !ids.has(x.id)).map(({ detail, ...x }) => x)]
      .sort((a, b) => (a.at < b.at ? -1 : 1)).slice(-HISTORY_MAX);
    if (sync.canTrain) {
      try {
        const st = await api('GET', '/stats');
        if (sync.uid === uid) setStats({ ...st, at: new Date().toISOString() });
      } catch (e) { /* statistika není nutná, zůstane stará cache */ }
      try {
        const co = await api('GET', '/coach');
        if (sync.uid === uid) {
          // M6: změnu tempa server už zapsal do nastavení – převzít ji (ruční změna čekající na odeslání má přednost)
          const ch = co.speed?.change;
          if (ch?.applied && !sync.dirtySettings) {
            settings.wpm = ch.to.wpm;
            settings.fwpm = ch.to.fwpm;
            clampSettings();
            co.speedNotice = { text: ch.text, why: ch.why, at: new Date().toISOString() };
          } else {
            co.speedNotice = coachInfo.data?.speedNotice || null;
          }
          coachInfo.data = co;
        }
      } catch (e) { /* plán není nutný, zůstane stará cache */ }
    }
    sync.lastSync = new Date().toISOString();
    sync.error = null;
  } catch (e) {
    if (e.status === 409) { // výcvik resetován jinde → zahodit staré a stáhnout znovu
      wipeTraining();
      sync.epoch = null;
      return doSync();
    }
    // při chybě se změny pošlou příště znovu
    sync.error = e.message;
    persist();
    throw e;
  }
  persist();
  notify();
  return null;
}

async function importLegacy(legacy, server) {
  // nastavení jen pokud účet ještě žádné nemá; pokrok = vyšší úroveň, sjednocené znaky, lekce se přidají
  if (!server.settings) {
    for (const k of SYNCED_SETTINGS) if (typeof legacy.settings[k] === 'number') settings[k] = legacy.settings[k];
    if (typeof legacy.settings.volume === 'number') settings.volume = legacy.settings.volume;
    clampSettings();
    write(KEY_DEVICE, { volume: settings.volume });
    sync.dirtySettings = true;
  }
  const lp = legacy.progress;
  progress.level = Math.max(lp.level || 2, server.progress?.level || 2);
  progress.introduced = [...new Set([...(server.progress?.introduced || []), ...(lp.introduced || [])])];
  const hist = (lp.history || []).map((h) => ({ id: uuid(), device: null, ...h }));
  progress.history = [...server.lessons, ...hist].sort((a, b) => (a.at < b.at ? -1 : 1)).slice(-HISTORY_MAX);
  sync.outbox = [...hist, ...sync.outbox];
  sync.dirtyProgress = true;
  persist();
  for (const k of LEGACY) localStorage.removeItem(k);
  await doSync();
  return { lessons: hist.length, level: progress.level };
}
