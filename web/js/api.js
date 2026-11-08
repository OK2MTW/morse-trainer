// SPDX-License-Identifier: EUPL-1.2
// Server API calls: JSON, CSRF token, understandable errors. Sends the UI language (X-Lang) so that server texts match.
import { t, lang } from './i18n.js';

let csrf = '';
export function setCsrf(token) { csrf = token || ''; }

// auth = not logged in / login expired. The server sends 403 + {auth: true} (not 401 – in Chrome that drops the
// Basic auth password of the Pinggy tunnel and causes a loop of password prompts for the domain; see server/auth.py).
export class ApiError extends Error {
  constructor(message, status, auth = false, busy = false) {
    super(message); this.status = status; this.auth = auth || status === 401; this.busy = busy;
  }
  get offline() { return this.status === 0; }
}

// Z-19 (0.10.19): the server is full (503 + busy from the app, 429 + busy from an nginx limit) → no requests until
// busyUntil; the wait grows with every refusal (30 s → 5 min) and is spread randomly so that refused clients do not
// come back together. Lessons wait in the queue (offline training). Requests the user starts by hand pass.
export const BUSY_STEPS_S = [30, 60, 120, 300];
const GATE_FREE = new Set(['/login', '/register', '/invite/check', '/password/reset', '/logout', '/logout-all',
  '/client-errors']);
const busy = { until: 0, step: 0, timer: null, msg: '', onEnd: null };

/** Called once the wait is over (account.js: one background sync attempt). */
export function setBusyEndHandler(fn) { busy.onEnd = fn; }
export const serverBusy = () => Date.now() < busy.until;

/** Pure: the wait in seconds after the step-th refusal (rnd 0–1, ±25 %); never shorter than the server asks. */
export function busyWait(step, retryS, rnd) {
  const base = BUSY_STEPS_S[Math.min(step, BUSY_STEPS_S.length - 1)];
  return Math.max(base, Number(retryS) || 0) * (0.75 + 0.5 * rnd);
}

function noteBusy(retryS, msg) {
  const wait = busyWait(busy.step, retryS, Math.random());
  busy.step += 1;
  busy.until = Date.now() + wait * 1000;
  busy.msg = msg;
  clearTimeout(busy.timer);
  busy.timer = setTimeout(() => { busy.timer = null; if (busy.onEnd) busy.onEnd(); }, wait * 1000 + 50);
}

export async function api(method, path, data) {
  if (serverBusy() && !GATE_FREE.has(path)) throw new ApiError(busy.msg, 503, false, true);
  const opts = { method, headers: { 'X-Lang': lang }, credentials: 'same-origin', cache: 'no-store' };
  if (data !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(data);
  }
  if (method !== 'GET') opts.headers['X-CSRF-Token'] = csrf;
  let resp;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch (e) {
    throw new ApiError(t('api.offline'), 0);
  }
  let json = null;
  try { json = await resp.json(); } catch (e) { /* empty / non-JSON response */ }
  if (!resp.ok) {
    const msg = json?.error || (resp.status === 429 ? t('api.tooMany') : t('api.serverError', { status: resp.status }));
    const isBusy = json?.busy === true && (resp.status === 503 || resp.status === 429);
    // 0.13.2: a limit hit by the CW room only slows the room down (cwroomui / cwchannel), never pauses the whole app
    if (isBusy && !path.startsWith('/cw/')) noteBusy(json.retry ?? resp.headers.get('Retry-After'), msg);
    throw new ApiError(msg, resp.status, json?.auth === true, isBusy);
  }
  if (busy.step) { busy.step = 0; busy.until = 0; clearTimeout(busy.timer); busy.timer = null; } // room again
  return json;
}

/** 0.13.1: a fire-and-forget POST that survives closing the page (fetch keepalive, with the CSRF token). */
export function beacon(path, data = {}) {
  if (!csrf) return;
  try {
    fetch(`/api${path}`, {
      method: 'POST', keepalive: true, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'X-Lang': lang },
      body: JSON.stringify(data),
    }).catch(() => {});
  } catch (e) { /* the page is going away – nothing to do */ }
}

// Device kind – stored value (lessons, sessions): 'mobil' = touch phone/tablet, 'pc' = computer.
export const DEVICE_MOBILE = 'mobil';
export const DEVICE_PC = 'pc';
export const deviceKind = () => (matchMedia('(pointer: coarse)').matches ? DEVICE_MOBILE : DEVICE_PC);
