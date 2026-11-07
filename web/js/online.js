// SPDX-License-Identifier: EUPL-1.2
// 0.9.6: number of users online right now – a subscript badge on the user icon. Polls /api/online while the page is
// visible; an older server without the endpoint (404) or offline → the badge just stays hidden.
import { api } from './api.js';
import { t } from './i18n.js';

const POLL_MS = 60000; // the server counts a user as online for 180 s after the last poll
let timer = null;
let running = false;

const $ = (sel) => document.querySelector(sel);

function render(n) {
  const el = $('#user-online');
  if (!el) return;
  el.hidden = !(n > 0);
  el.textContent = n > 0 ? String(n) : '';
  if (n > 0) el.title = t('nav.online', { n });
}

async function poll() {
  if (!running || document.hidden) return;
  try {
    const r = await api('GET', '/online');
    render(running ? r?.online : 0);
  } catch (e) {
    render(0);
  }
}

export function startOnline() {
  if (running) return;
  running = true;
  poll();
  timer = setInterval(poll, POLL_MS);
}

export function stopOnline() {
  running = false;
  clearInterval(timer);
  timer = null;
  render(0);
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
