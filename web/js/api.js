// SPDX-License-Identifier: EUPL-1.2
// Volání serverového API: JSON, CSRF token, srozumitelné chyby.
let csrf = '';
export function setCsrf(token) { csrf = token || ''; }

// auth = nepřihlášen / přihlášení vypršelo. Server posílá 403 + {auth: true} (ne 401 – ten v Chromu ruší heslo
// Basic auth tunelu Pinggy a vyvolá smyčku dotazů na heslo k doméně; viz server/auth.py).
export class ApiError extends Error {
  constructor(message, status, auth = false) { super(message); this.status = status; this.auth = auth || status === 401; }
  get offline() { return this.status === 0; }
}

export async function api(method, path, data) {
  const opts = { method, headers: {}, credentials: 'same-origin', cache: 'no-store' };
  if (data !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(data);
  }
  if (method !== 'GET') opts.headers['X-CSRF-Token'] = csrf;
  let resp;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch (e) {
    throw new ApiError('Server je nedostupný (jsi v domácí síti?).', 0);
  }
  let json = null;
  try { json = await resp.json(); } catch (e) { /* prázdná / ne-JSON odpověď */ }
  if (!resp.ok) {
    const msg = json?.error || (resp.status === 429 ? 'Příliš mnoho požadavků, chvíli počkej.' : `Chyba serveru (${resp.status}).`);
    throw new ApiError(msg, resp.status, json?.auth === true);
  }
  return json;
}

export const deviceKind = () => (matchMedia('(pointer: coarse)').matches ? 'mobil' : 'pc');
