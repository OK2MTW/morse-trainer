// SPDX-License-Identifier: EUPL-1.2
// 0.13.6 – CW room "doorbell": outside the room tab the app asks every 5 s who is knocking (/api/cw/knocks, memory only
// at the server, ~1 ms). A knock = a pulsing mark on the CW tab, the tab title says who, and the knock sound – but never
// in the middle of a lesson or a sound page (quiet()), the sound would spoil the reaction times there.
import { t } from './i18n.js';
import { api, ApiError } from './api.js';

const BELL_MS = 5000;          // the server keeps the user reachable for 15 s after the last ask
const BELL_SLOW_MS = 15000;    // after an error / offline
const BELL_NONE_MS = 60000;    // no access to the room (switched off / children's room off)
const BELL_OLD_MS = 600000;    // an older server without the endpoint

/** Two pairs of short knocks on wood ("knock knock … knock knock") – also used by the room itself. */
export function knockSound(player) {
  if (!player.ready) return;
  const ctx = player.ctx;
  const t0 = ctx.currentTime + 0.03;
  for (const at of [0, 0.17, 0.55, 0.72]) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(190, t0 + at);
    osc.frequency.exponentialRampToValueAtTime(90, t0 + at + 0.08);
    g.gain.setValueAtTime(0.0001, t0 + at);
    g.gain.exponentialRampToValueAtTime(0.6 * (player.settings?.volume ?? 0.6), t0 + at + 0.005);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.09);
    osc.connect(g).connect(ctx.destination);
    osc.start(t0 + at);
    osc.stop(t0 + at + 0.1);
  }
}

/** player (audio.js), quiet() = true while a lesson / sound page is open (mark only, no sound). */
export function initCwBell({ player, quiet }) {
  const st = { running: false, timer: null, heard: new Set() };

  function render(knocks) {
    const tab = document.querySelector('.tabs [data-go="cw"]');
    if (!tab) return;
    const on = knocks.length > 0;
    tab.classList.toggle('knocking', on);
    if (on) tab.title = t('cw.bellTitle', { nick: knocks.map((k) => k.nick).join(', ') });
    else tab.removeAttribute('title');
  }

  function schedule(ms) {
    clearTimeout(st.timer);
    if (st.running) st.timer = setTimeout(poll, ms);
  }

  async function poll() {
    if (!st.running) return;
    if (document.hidden) { schedule(BELL_MS); return; }
    let next = BELL_MS;
    try {
      const r = await api('GET', '/cw/knocks');
      if (!st.running) return;
      const knocks = r?.access ? (r.knocks || []) : [];
      if (!r?.access) next = BELL_NONE_MS;
      const ids = new Set(knocks.map((k) => k.id));
      if ([...ids].some((id) => !st.heard.has(id)) && !quiet()) knockSound(player);
      st.heard = ids;
      render(knocks);
    } catch (e) {
      if (e instanceof ApiError && e.auth) { stop(); return; }
      next = e instanceof ApiError && e.status === 404 ? BELL_OLD_MS : BELL_SLOW_MS;
    }
    schedule(next);
  }

  function start() {
    if (st.running) return;
    st.running = true;
    st.heard = new Set();
    poll();
  }

  function stop() {
    st.running = false;
    clearTimeout(st.timer);
    render([]);
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden && st.running) poll(); });
  return { start, stop };
}
