// SPDX-License-Identifier: EUPL-1.2
// 0.13.1 – CW room 1:1: the list of users with status (like a chat app), "Knock Knock", accept / decline / hang up,
// blocking. The server keeps the room in memory (server/cwroom.py) and is polled with short requests: every 1 s
// while the page is open and visible (no long polling – it would hold a server thread). Leaving the page = `leave`.
import { t } from './i18n.js';
import { api, beacon, ApiError, serverBusy } from './api.js';
import { knockSound as playKnock } from './cwbell.js';

const $ = (s) => document.querySelector(s);
const POLL_MS = 1000;
const POLL_SLOW_MS = 3000;   // after 429 / a network error
// statuses from the server (stored codes) in the order of the list
const STATUS_ORDER = ['room', 'linked', 'app', 'off'];
const STATUS_ROOM = 'room';

/**
 * player (audio.js, for the knock sound), ensureAudio, onAuth (login expired),
 * link = optional hooks of the channel (0.13.2): onState(state, ctx), onStop().
 */
export function initCwRoom({ player, ensureAudio, onAuth, link = null }) {
  const st = {
    running: false, timer: null, data: null, knocksHeard: new Set(), error: '',
  };

  const knockSound = () => playKnock(player);

  // ---------- polling ----------
  function schedule(ms) {
    clearTimeout(st.timer);
    if (st.running) st.timer = setTimeout(poll, ms);
  }

  async function poll() {
    if (!st.running) return;
    if (document.hidden) { schedule(POLL_MS); return; }
    if (serverBusy()) { st.error = t('cw.serverBusy'); renderAll(); schedule(POLL_SLOW_MS); return; }
    let next = POLL_MS;
    try {
      const q = link?.query ? link.query() : '';
      const sent = performance.now();
      st.data = await api('GET', `/cw/state${q}`);
      st.error = '';
      if (link?.onState) next = link.onState(st.data, { sent, now: performance.now() }) || POLL_MS;
    } catch (e) {
      if (e instanceof ApiError && e.auth) { stop(); onAuth?.(); return; }
      if (e instanceof ApiError && e.status === 404) { st.error = t('cw.needsUpdate'); next = POLL_SLOW_MS * 10; } else {
        st.error = e.offline ? t('cw.offline') : e.message;
        next = POLL_SLOW_MS;
      }
    }
    renderAll();
    schedule(next);
  }

  /** Called by the channel (0.13.2) to poll sooner, e.g. while receiving. */
  function pollSoon(ms) { if (st.running) schedule(ms); }

  // ---------- actions ----------
  async function act(path, data) {
    try {
      await api('POST', path, data);
    } catch (e) {
      if (e instanceof ApiError && e.auth) { stop(); onAuth?.(); return; }
      st.error = e.message;
    }
    poll();
  }

  // ---------- rendering ----------
  function renderAll() {
    const d = st.data;
    $('#cw-error').textContent = st.error;
    $('#cw-error').hidden = !st.error;
    const access = d?.access;
    $('#cw-noaccess').hidden = !d || access;
    $('#cw-room').hidden = !access;
    if (!d) return;
    if (!access) {
      $('#cw-noaccess-text').textContent = t(`cw.noAccess.${d.reason}`);
      return;
    }
    renderNotice(d.notice);
    renderLink(d);
    renderUsers(d);
    renderBlocked(d.blocked || []);
  }

  function showNotice(text, ms = 12000) {
    const el = $('#cw-notice');
    el.textContent = text;
    el.hidden = false;
    clearTimeout(showNotice.timer);
    showNotice.timer = setTimeout(() => { el.hidden = true; }, ms);
  }

  function renderNotice(n) {
    if (n) showNotice(t(`cw.notice.${n.kind}`, { nick: n.nick }));
  }

  function renderLink(d) {
    const box = $('#cw-link');
    box.hidden = !d.link;
    if (!d.link) return;
    const s = d.link.s;
    $('#cw-link-who').textContent = t('cw.linkedWith', { nick: d.link.nick });
    $('#cw-link-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  function btn(text, onClick, cls) {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = text;
    if (cls) b.className = cls;
    b.addEventListener('click', onClick);
    return b;
  }

  function rowHint(u, linked, knocking) {
    let key = 'cw.rowNotInRoom';
    if (u.status === 'linked') key = 'cw.rowLinked';
    else if (linked) key = 'cw.rowSelfLinked';
    else if (knocking) key = 'cw.rowKnocking';
    showNotice(t(key, { nick: u.nick }));
  }

  function renderUsers(d) {
    const ul = $('#cw-users');
    // 0.13.4: rebuild only on a change – a rebuild every second ate clicks (press and release on different elements)
    const sig = JSON.stringify([d.users, !!d.link, document.documentElement.lang]);
    if (sig === st.usersSig && ul.childElementCount) return;
    st.usersSig = sig;
    ul.textContent = '';
    // the virtual operator: a fixed entry at the top, not active yet
    const vo = document.createElement('li');
    vo.className = 'cw-user vo';
    vo.append(dot('vo'), label(t('cw.vo'), t('cw.voSoon')));
    ul.append(vo);

    const heard = new Set();
    const rank = (u) => (u.knockIn ? -1 : STATUS_ORDER.indexOf(u.status));
    const users = [...d.users].sort((a, b) => rank(a) - rank(b) || a.nick.localeCompare(b.nick));
    const linked = !!d.link;
    const knocking = users.some((u) => u.knockOut);
    for (const u of users) {
      const li = document.createElement('li');
      li.className = `cw-user st-${u.status}${u.knockIn ? ' knock' : ''}`;
      const sub = u.knockIn ? t('cw.knockIn') : (u.knockOut ? t('cw.knocking') : t(`cw.status.${u.status}`));
      li.append(dot(u.status), label(u.coach ? `${u.nick} · ${t('cw.coach')}` : u.nick, sub));
      const acts = document.createElement('span');
      acts.className = 'cw-acts';
      if (u.knockIn) {
        heard.add(u.id);
        acts.append(btn(t('cw.accept'), () => act('/cw/answer', { from: u.id, accept: true })),
          btn(t('cw.decline'), () => act('/cw/answer', { from: u.id, accept: false })));
      } else if (u.knockOut) {
        acts.append(btn(t('cw.cancelKnock'), () => act('/cw/knock/cancel')));
      } else if ((u.reach ?? u.status === STATUS_ROOM) && !linked && !knocking) {   // 0.13.6: also the app elsewhere
        const knock = async () => { await ensureAudio(); act('/cw/knock', { to: u.id }); };
        acts.append(btn(t('cw.knock'), knock));
        li.classList.add('can-knock');
        li.addEventListener('click', (e) => { if (!e.target.closest('button')) knock(); });
      }
      if (!li.classList.contains('can-knock') && !u.knockIn && !u.knockOut) {
        // 0.13.4: a click on someone who cannot be called now says why (it used to do nothing)
        li.addEventListener('click', (e) => { if (!e.target.closest('button')) rowHint(u, linked, knocking); });
      }
      if (!u.coach) {
        acts.append(btn('⋯', () => {
          if (confirm(t('cw.blockConfirm', { nick: u.nick }))) act('/cw/block', { id: u.id, on: true });
        }, 'cw-more'));
        acts.lastChild.title = t('cw.block');
        acts.lastChild.setAttribute('aria-label', t('cw.blockNick', { nick: u.nick }));
      }
      li.append(acts);
      ul.append(li);
    }
    if (!users.length) {
      const li = document.createElement('li');
      li.className = 'cw-user empty';
      li.textContent = t('cw.nobody');
      ul.append(li);
    }
    // a new knock → sound (once per knock)
    if ([...heard].some((id) => !st.knocksHeard.has(id))) knockSound();
    st.knocksHeard = heard;
  }

  function dot(status) {
    const s = document.createElement('span');
    s.className = `cw-dot ${status}`;
    s.setAttribute('aria-hidden', 'true');
    return s;
  }

  function label(main, sub) {
    const s = document.createElement('span');
    s.className = 'cw-name';
    s.textContent = main;
    const small = document.createElement('small');
    small.textContent = sub;
    s.append(small);
    return s;
  }

  function renderBlocked(list) {
    $('#cw-blocked-box').hidden = !list.length;
    $('#cw-blocked-sum').textContent = t('cw.blocked', { n: list.length });
    const ul = $('#cw-blocked');
    ul.textContent = '';
    for (const b of list) {
      const li = document.createElement('li');
      li.append(document.createTextNode(`${b.nick} `), btn(t('cw.unblock'), () => act('/cw/block', { id: b.id, on: false })));
      ul.append(li);
    }
  }

  $('#cw-hangup').addEventListener('click', () => {
    if (confirm(t('cw.hangupConfirm'))) act('/cw/hangup');
  });

  // ---------- lifecycle ----------
  function render() {
    if (!st.running) {
      st.running = true;
      st.knocksHeard = new Set();
      st.usersSig = '';
      ensureAudio();
    }
    renderAll();
    poll();
  }

  function stop() {
    if (!st.running) return;
    st.running = false;
    clearTimeout(st.timer);
    link?.onStop?.();
    beacon('/cw/leave');
    st.data = null;
  }

  // closing / reloading the page = leaving the room (ends a connection)
  window.addEventListener('pagehide', () => { if (st.running) { link?.onStop?.(); beacon('/cw/leave'); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && st.running) poll(); });

  return { render, stop, pollSoon, get data() { return st.data; } };
}
