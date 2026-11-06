// SPDX-License-Identifier: EUPL-1.2
// Server API calls: JSON, CSRF token, understandable errors. Sends the UI language (X-Lang) so that server texts match.
import { t, lang } from './i18n.js';

let csrf = '';
export function setCsrf(token) { csrf = token || ''; }

// auth = not logged in / login expired. The server sends 403 + {auth: true} (not 401 – in Chrome that drops the
// Basic auth password of the Pinggy tunnel and causes a loop of password prompts for the domain; see server/auth.py).
export class ApiError extends Error {
  constructor(message, status, auth = false) { super(message); this.status = status; this.auth = auth || status === 401; }
  get offline() { return this.status === 0; }
}

export async function api(method, path, data) {
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
    throw new ApiError(msg, resp.status, json?.auth === true);
  }
  return json;
}

// Device kind – stored value (lessons, sessions): 'mobil' = touch phone/tablet, 'pc' = computer.
export const DEVICE_MOBILE = 'mobil';
export const DEVICE_PC = 'pc';
export const deviceKind = () => (matchMedia('(pointer: coarse)').matches ? DEVICE_MOBILE : DEVICE_PC);
