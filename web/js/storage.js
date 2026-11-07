// SPDX-License-Identifier: EUPL-1.2
// User data: the master copy is on the server (SQLite), the browser keeps an offline cache + a queue of unsent changes.
// Lessons are always stored locally first and sent once the server is reachable (they have a UUID → sending is idempotent).
import { api } from './api.js';
import { MIN_WPM } from './drill.js';
import { BLOCK_MAX_MIN } from './coach.js';
import { flushTrace } from './trace.js';

const KEY_USER = 'morse-user';            // last logged-in user (for an offline start)
const KEY_DEVICE = 'morse-device';         // settings of this device only (volume)
const cacheKey = (uid) => `morse-cache-${uid}`;
const LEGACY = ['morse-settings', 'morse-progress', 'morse-m0-settings']; // M0/M1 without an account

export const DEFAULT_SETTINGS = { wpm: 20, fwpm: 15, freq: 600, volume: 0.7, lessonMin: 5, autoSpeed: 1, extraChars: 0, lang: null };
export const DEFAULT_PROGRESS = { level: 2, introduced: [], history: [] };
const SYNCED_SETTINGS = ['wpm', 'fwpm', 'freq', 'lessonMin', 'autoSpeed', 'extraChars', 'lang']; // I18N: language follows the account
// Lesson mode – stored value (lessons, traces): 'znak' = character by character with an answer, 'skluz' = copy behind.
export const MODE_CHAR = 'znak';
export const MODE_COPY = 'skluz';
export const MODE_HEAD = 'hlava'; // 0.10.14: head copy (U6) – listen without typing, then the key data
const HISTORY_MAX = 500;

/** Hard limit of the character speed (R1): older stored settings below 12 WPM are raised. */
function clampSettings() {
  if (!(settings.wpm >= MIN_WPM)) settings.wpm = Math.max(MIN_WPM, Number(settings.wpm) || DEFAULT_SETTINGS.wpm);
  if (settings.fwpm > settings.wpm) settings.fwpm = settings.wpm;
  if (settings.lessonMin > BLOCK_MAX_MIN) settings.lessonMin = BLOCK_MAX_MIN; // block of 5–10 min (R1)
}

function read(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
}

// Shared objects – main.js changes them directly and then calls save*().
export const settings = { ...DEFAULT_SETTINGS };
export const progress = { ...DEFAULT_PROGRESS, introduced: [], history: [] };
// Character statistics from the server (GET /api/stats) – read-only cache, computed by the server from recent lessons.
export const stats = { lessons: 0, chars: {}, at: null };
// Coach from the server (GET /api/coach, M4): archetype, modifiers, preferences, plan, level U1–U6, plateau.
export const coachInfo = { data: null };
export const sync = { canTrain: true, epoch: null, uid: null, dirtySettings: false, dirtyProgress: false, outbox: [], lastSync: null, error: null };
let listeners = [];
export function onDataChange(fn) { listeners.push(fn); }
const notify = () => listeners.forEach((fn) => fn());

/** New questionnaire (or plan) result from the server → cache. */
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

/** Loads the user's cache (without network). */
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

function setStats(st) {
  stats.lessons = st?.lessons || 0;
  stats.chars = st?.chars && typeof st.chars === 'object' ? st.chars : {};
  stats.at = st?.at || null;
}

/** Training was reset (here or on another device) – drop local progress, history and unsent lessons. */
function wipeTraining() {
  setStats(null);
  progress.level = DEFAULT_PROGRESS.level;
  progress.introduced = [];
  progress.history = [];
  sync.outbox = [];
  sync.dirtyProgress = false;
}

/** Reset of one's own training (confirmed by password). Settings stay. */
export async function resetTraining(password) {
  const { epoch } = await api('POST', '/training/reset', { password });
  wipeTraining();
  sync.epoch = epoch;
  persist();
  notify();
}

/** Logout: deletes the user's data from this device (shared computer). */
export function forgetUser() {
  if (sync.uid != null) { localStorage.removeItem(cacheKey(sync.uid)); localStorage.removeItem(`morse-trace-q-${sync.uid}`); }
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

/** Stores a lesson result (locally at once, on the server with the next sync). */
export function addLesson(entry) {
  const h = { id: uuid(), ...entry };
  const { detail, ...compact } = h; // per-character detail only goes to the server, the local history stays small
  progress.history.push(compact);
  if (progress.history.length > HISTORY_MAX) progress.history = progress.history.slice(-HISTORY_MAX);
  sync.outbox.push(h);
  saveProgress();
  return h;
}

/** M1 data (without an account) in this browser – merged into the first account that logs in here. */
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

/** Sends changes and fetches the current state from the server. Returns info about an M1 data import (or null). */
export function syncNow() {
  if (!syncing) syncing = doSync().finally(() => { syncing = null; });
  return syncing;
}

async function doSync() {
  if (sync.uid == null) return null;
  const uid = sync.uid;
  try {
    // 1) send (in batches of at most 200 lessons)
    while (sync.outbox.length) {
      const batch = sync.outbox.slice(0, 200);
      const { saved } = await api('POST', '/lessons', { lessons: batch, epoch: sync.epoch });
      const ok = new Set(saved);
      // rejected (invalid) lessons are removed from the queue too, otherwise they would be sent forever
      const sent = new Set(batch.map((x) => x.id));
      sync.outbox = sync.outbox.filter((x) => !sent.has(x.id));
      if (ok.size !== sent.size) console.warn('Server rejected some lessons');
    }
    // V1: debug trace of lessons (only for enabled accounts) – its error must not stop the sync
    try { await flushTrace(); } catch (e) { if (e.auth) throw e; }
    // the flag is cleared before sending (a change while waiting sets it again), restored on error
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
    // 2) fetch
    const d = await api('GET', '/data');
    if (sync.uid !== uid) return null; // logged out meanwhile
    if (sync.epoch !== null && d.epoch !== sync.epoch) wipeTraining(); // reset from another device
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
      } catch (e) { /* statistics are optional, the old cache stays */ }
      try {
        const co = await api('GET', '/coach');
        if (sync.uid === uid) {
          // M6: the server already wrote the pace change into the settings – take it over (a pending manual change wins)
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
      } catch (e) { /* the plan is optional, the old cache stays */ }
    }
    sync.lastSync = new Date().toISOString();
    sync.error = null;
  } catch (e) {
    if (e.status === 409) { // training reset elsewhere → drop the old data and fetch again
      wipeTraining();
      sync.epoch = null;
      return doSync();
    }
    // on error the changes are sent again next time
    sync.error = e.message;
    persist();
    throw e;
  }
  persist();
  notify();
  return null;
}

async function importLegacy(legacy, server) {
  // settings only if the account has none yet; progress = higher level, union of characters, lessons are added
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
