// SPDX-License-Identifier: EUPL-1.2
// V1: debug trace of the training – only for accounts where the administrator enables it (server.admin debug NICK on).
// During a lesson it collects events [ms from the start, type, data] and sends them with the sync after the lesson.
// It also captures application (JS) errors – since 0.9.4 for every account. Nothing personal – only the course of training and the technical state of audio/app.
import { api } from './api.js';

const Q_MAX = 40;            // at most lessons in the queue (older ones are dropped)
const EV_MAX = 20000;        // at most events in one lesson
const ERR_MAX = 20;
const qKey = (uid) => `morse-trace-q-${uid}`;
const ERR_KEY = 'morse-trace-err';

let enabled = false;
let uid = null;
let cur = null;              // lesson record in progress
let ctxHooked = null;

const read = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage full – the record is dropped */ } };

/** After login / loading the user (user.debug from the server). */
export function setTraceUser(user) {
  enabled = !!user?.debug;
  uid = user?.id ?? null;
  if (!enabled && uid != null) localStorage.removeItem(qKey(uid));
}
export const traceOn = () => enabled;

/** Start of a lesson. meta = settings, character set, audio state… A record in progress is stored as aborted. */
export function traceBegin(kind, meta) {
  if (!enabled) return;
  if (cur) traceEnd(null, { aborted: true });
  cur = { kind, at: new Date().toISOString(), t0: performance.now(), meta, ev: [] };
}

/** Event during a lesson (nothing happens without an open record). */
export function tr(type, data) {
  if (!cur || cur.ev.length >= EV_MAX) return;
  const ms = Math.round(performance.now() - cur.t0);
  cur.ev.push(data === undefined ? [ms, type] : [ms, type, data]);
}

/** End of a lesson: lessonId = id of the stored lesson (null = the lesson was not stored). */
export function traceEnd(lessonId, extra) {
  if (!cur || uid == null) { cur = null; return; }
  const item = {
    lesson_id: lessonId || null, kind: cur.kind, at: cur.at,
    data: { meta: cur.meta, ev: cur.ev, ...(extra ? { end: extra } : {}), durMs: Math.round(performance.now() - cur.t0) },
  };
  cur = null;
  const q = read(qKey(uid), []);
  q.push(item);
  write(qKey(uid), q.slice(-Q_MAX));
}

/** Audio context state – changes (suspended/running/interrupted) are written to the record. */
export function traceAudio(ctx) {
  if (!ctx || ctxHooked === ctx) return;
  ctxHooked = ctx;
  ctx.addEventListener?.('statechange', () => tr('audio', ctx.state));
}

export function audioMeta(player) {
  const ctx = player.ctx;
  return ctx ? { state: ctx.state, ...player.latencyInfo() } : null;
}

/** Sends the queue (called by the sync). Network errors do not matter – retried next time. */
export async function flushTrace() {
  if (uid == null) return;
  const errs = read(ERR_KEY, []);
  if (errs.length) { // 0.9.4: application errors from every account (validation Z-05)
    const r = await api('POST', '/client-errors', { errors: errs });
    localStorage.removeItem(ERR_KEY);
    if (r.debug === false && enabled) { setTraceUser(null); return; }
  }
  if (!enabled) return;
  const key = qKey(uid);
  let q = read(key, []);
  while (q.length) {
    try {
      const r = await api('POST', '/trace', q[0]);
      if (r.debug === false) { enabled = false; localStorage.removeItem(key); return; }
    } catch (e) {
      if (e.offline || e.auth || e.status === 403) throw e;
      // invalid / too large record – drop it so that it does not block the queue
    }
    q = read(key, []).slice(1);
    write(key, q);
  }
}

// ---------- global events during a lesson ----------
document.addEventListener('visibilitychange', () => tr('vis', document.visibilityState));
window.addEventListener('online', () => tr('net', 'online'));
window.addEventListener('offline', () => tr('net', 'offline'));
// 0.9.7 (Z-06): the app saves a running lesson first (beforeHide) → the trace is linked to the saved lesson
let beforeHide = null;
export function setBeforeHide(fn) { beforeHide = fn; }
window.addEventListener('pagehide', () => {
  tr('pagehide');
  try { beforeHide?.(); } catch (e) { /* never block leaving the page */ }
  if (cur) traceEnd(null, { aborted: 'pagehide' });
});

// ---------- application errors ----------
// #25: the app version goes with every error – read from the service worker cache name (morse-v<VERSION>-<hash>)
let appVer = '';
try {
  globalThis.caches?.keys().then((ks) => {
    const v = ks.map((k) => /^morse-v(.+)-[0-9a-f]+$/.exec(k)?.[1]).filter(Boolean);
    if (v.length) appVer = v.at(-1);
  }).catch(() => {});
} catch (e) { /* no Cache API (http, private mode) */ }

function noteError(msg, src, line, stack) {
  const errs = read(ERR_KEY, []);
  if (errs.length >= ERR_MAX) return;
  errs.push({
    at: new Date().toISOString(), msg: String(msg).slice(0, 300), src: String(src || '').slice(0, 300),
    line: String(line || ''), stack: String(stack || '').slice(0, 2000), ver: appVer, view: document.querySelector('.view:not([hidden])')?.id || '',
    ua: navigator.userAgent.slice(0, 300),
  });
  write(ERR_KEY, errs);
  tr('error', String(msg).slice(0, 200));
}
window.addEventListener('error', (e) => noteError(e.message, e.filename, `${e.lineno}:${e.colno}`, e.error?.stack));
window.addEventListener('unhandledrejection', (e) => noteError(`Promise: ${e.reason?.message || e.reason}`, '', '', e.reason?.stack));
