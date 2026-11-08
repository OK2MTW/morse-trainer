// SPDX-License-Identifier: EUPL-1.2
// 0.13.2 – CW room channel: keying with the shared keyer (keyer.js, settings of the key page), batches to the server,
// taking the channel by the first key down, playing the other station on the band (band.js LiveBand) with the reserve
// of cwlink.js, the TX / RX / free label and the measured delay. Half duplex like on the air: while the other station
// holds the channel (or its over still sounds here) the key is blocked.
import { t, fmtNum } from './i18n.js';
import { api, ApiError } from './api.js';
import { Keyer, manualSide, KEYER_WPM_MIN, KEYER_WPM_MAX } from './keyer.js';
import { loadKeyConfig, saveKeyConfig, KEY_UI_TYPES } from './keyerui.js';
import { LiveBand, bandParams } from './band.js';
import { decodeTones } from './decoder.js';
import { MORSE } from './charset.js';
import { TxOver, RxPlayout, BATCH_MS, BATCH_SLOW_MS, POLL_MS, POLL_RX_MS, POLL_TX_MS } from './cwlink.js';

const $ = (s) => document.querySelector(s);
const STORE = 'morse-cw';
// the band of the room: always at least weak noise (only quieter, never off), interference by own choice
const NOISE_LEVELS = { min: 0.08, mid: 0.2, max: 0.4 };
const CW_PRESETS = ['clean', 'qsb', 'flutter', 'qrn', 'qrm', 'evening'];
const PREFS_DEFAULT = { noise: 'min', preset: 'clean', showTx: true, showRx: false };
const LOG_MAX = 30;          // transcript lines kept
const PEER_OFFSET_HZ = 50;   // the other station sounds 50 Hz above the own sidetone
const LOOK_MS = 12;          // as keyerui.js
const START_S = 0.003;
const BUSY_NOTE_MS = 2500;
const AHEAD_MS = 50;         // automatic elements are known a moment before they sound
const CHANNEL_RX = 'rx';

function loadPrefs() {
  try {
    const p = { ...PREFS_DEFAULT, ...(JSON.parse(localStorage.getItem(STORE)) || {}) };
    if (!(p.noise in NOISE_LEVELS)) p.noise = PREFS_DEFAULT.noise;
    if (!CW_PRESETS.includes(p.preset)) p.preset = PREFS_DEFAULT.preset;
    p.showTx = p.showTx !== false;
    p.showRx = p.showRx === true;
    return p;
  } catch (e) { return { ...PREFS_DEFAULT }; }
}
function savePrefs(p) { try { localStorage.setItem(STORE, JSON.stringify(p)); } catch (e) { /* private mode */ } }

/** pollSoon(ms) asks the room (cwroomui.js) for an earlier poll. Returns the hooks of the room. */
export function initCwChannel({ player, ensureAudio, pollSoon }) {
  const prefs = loadPrefs();
  let cfg = loadKeyConfig();
  let keyer = new Keyer(cfg);
  const C = {
    on: false, peer: null, band: new LiveBand(player), rx: new RxPlayout(), tx: null, txTimer: null,
    flushing: false, batchMs: BATCH_MS, channel: 'free', peerIds: [], chainEnd: 0, timer: null, manual: null,
    keys: new Set(), held: { dot: false, dash: false }, sent: { dot: false, dash: false }, doneTimer: null,
    busyNote: 0, txTones: [], rxEls: new Map(), lines: [], peerNick: '',
  };

  const toCtx = (ms) => player.ctx.currentTime + (ms - performance.now()) / 1000;
  const audioToEventMs = (s) => performance.now() + (s - player.ctx.currentTime) * 1000;
  const keyDown = () => C.manual !== null || keyer.down.dot || keyer.down.dash || keyer.busy;

  /** The other station holds the channel or its over still sounds here. */
  function blocked() {
    if (C.tx) return false;
    if (C.rx.busy(performance.now())) return true;
    return C.channel === CHANNEL_RX && C.peerIds.some((id) => id > C.rx.lastId);
  }

  // ---------- sending ----------
  function startTimer() {
    clearTimeout(C.txTimer);
    const tick = () => {
      flush();
      C.txTimer = C.tx ? setTimeout(tick, C.batchMs) : null;
    };
    C.txTimer = setTimeout(tick, C.batchMs);
  }

  function ensureOver(ts) {
    if (C.tx) return;
    C.tx = new TxOver(ts);
    renderTrx();
    sendStart(C.tx);
    startTimer();
  }

  async function sendStart(o) {
    o.inflight = true;
    const els = o.batch(performance.now() + AHEAD_MS);
    try {
      const r = await api('POST', '/cw/tx', { start: true, els, done: C.rx.lastId });
      if (C.tx === o) o.id = r.over;
    } catch (e) {
      if (C.tx !== o) return;
      if (e instanceof ApiError && e.status === 409) { lostChannel(); return; }   // channelBusy / notLinked
      if (e instanceof ApiError && e.status === 429) C.batchMs = BATCH_SLOW_MS;
      o.sent = 0;   // retried by the next flush
    } finally { o.inflight = false; }
  }

  async function flush() {
    const o = C.tx;
    if (!o || C.flushing) return;
    if (!o.id) { if (!o.inflight) sendStart(o); return; }
    const now = performance.now();
    let els = o.batch(now + AHEAD_MS);
    const end = o.silent(now, keyer.unit, keyDown());
    if (end) els = els.concat(o.rest());
    if (!els.length && !end) return;
    C.flushing = true;
    try {
      const r = await api('POST', '/cw/tx', { over: o.id, els, end });
      if ((end || r.ended) && C.tx === o) endLocal();
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) C.batchMs = BATCH_SLOW_MS;
      if (C.tx === o) {
        if (e instanceof ApiError && e.status === 409) endLocal();   // the connection has ended meanwhile
        else o.sent -= els.length;                                  // try again with the next batch
      }
    } finally {
      C.flushing = false;
    }
  }

  function endLocal() {
    C.tx = null;
    closeTxLine();
    clearTimeout(C.txTimer);
    C.txTimer = null;
    renderTrx();
    pollSoon(0);
  }

  /** An element of the own over (event ms). A very long over continues as a new one (server limit 2 min). */
  function txElement(start, end, el = null) {
    if (C.tx && C.tx.tooLong(start)) {
      const o = C.tx;
      const els = o.rest();
      C.tx = null;
      closeTxLine();
      if (o.id) api('POST', '/cw/tx', { over: o.id, els, end: true }).catch(() => {});
    }
    const fresh = !C.tx;
    if (fresh) { C.tx = new TxOver(start); C.txTones = []; }
    C.tx.add(start, end);
    C.txTones.push({ start, end, el });
    renderLog();
    if (fresh) { renderTrx(); sendStart(C.tx); startTimer(); }   // the first element goes with the start
  }

  /** Lost the race for the channel: silence the sidetone, release the key, wait for the other station. */
  function lostChannel() {
    player.sidetoneOff();
    releaseAll();
    C.tx = null;
    C.txTones = [];   // lost the race: nothing of it went out
    clearTimeout(C.txTimer);
    C.txTimer = null;
    C.channel = CHANNEL_RX;
    C.peerIds = [C.rx.lastId + 1];
    noteBusy();
    pollSoon(0);
  }

  function noteBusy() {
    C.busyNote = performance.now() + BUSY_NOTE_MS;
    renderTrx();
    setTimeout(renderTrx, BUSY_NOTE_MS + 50);
  }

  // ---------- keyer (the same driving as keyerui.js) ----------
  function startElement(el, at) {
    const dur = keyer.elementMs(el) / 1000;
    if (cfg.sidetone) player.sidetoneElement(at, at + dur);
    const start = audioToEventMs(at);
    txElement(start, start + dur * 1000, el);
    C.chainEnd = at + dur + keyer.unit / 1000;
    clearTimeout(C.timer);
    C.timer = setTimeout(decide, Math.max(0, (C.chainEnd - player.ctx.currentTime) * 1000 - LOOK_MS));
  }

  function decide() {
    C.timer = null;
    if (!C.on) return;
    const el = keyer.next();
    if (el) startElement(el, Math.max(C.chainEnd, player.ctx.currentTime + START_S));
  }

  function manualKey(down, ts) {
    if (down) {
      if (C.manual !== null) return;
      C.manual = ts;
      ensureOver(ts);   // the first key down takes the channel at once
      if (cfg.sidetone) player.sidetoneKey(true);
    } else if (C.manual !== null) {
      if (cfg.sidetone) player.sidetoneKey(false);
      const s = C.manual;
      C.manual = null;
      if (C.tx) { C.tx.add(s, Math.max(s, ts)); C.txTones.push({ start: s, end: Math.max(s, ts), el: null }); renderLog(); }
    }
  }

  function input(side, down, ts) {
    if (!C.on || !player.ready) return;
    if (down && blocked()) { noteBusy(); return; }
    const s = cfg.swap ? (side === 'dot' ? 'dash' : 'dot') : side;
    const man = manualSide(cfg.type);
    if (s === man) { manualKey(down, ts); return; }
    if (cfg.type === 'straight') return;
    if (down) { if (keyer.press(s)) decide(); } else keyer.release(s);
  }

  function releaseAll() {
    clearTimeout(C.timer);
    C.timer = null;
    keyer.releaseAll();
    if (C.manual !== null) manualKey(false, performance.now());
    for (const b of document.querySelectorAll('.cw-paddles .key-paddle')) b.classList.remove('down');
    C.held = { dot: false, dash: false };
    C.sent = { dot: false, dash: false };
    C.keys.clear();
  }

  // ---------- receiving ----------
  function onState(d, tm) {
    if (!d.access || !d.link) { if (C.on) close(); return POLL_MS; }
    if (!C.on || C.peer !== d.link.id) open(d.link);
    C.channel = d.channel;
    C.peerIds = (d.rx || []).map((o) => o.id);
    const rtt = Math.max(0, tm.now - tm.sent);
    for (const item of d.rx || []) {
      if (item.id <= C.rx.lastId) continue;
      const cur = C.rx.cur;
      const have = cur && cur.id === item.id ? cur.n : 0;
      if (item.from > have) continue;   // a gap (should not happen) – wait for the next poll
      const els = item.els.slice(have - item.from);
      const out = C.rx.receive(item.id, els, item.end, tm.now, Number.isFinite(item.t) ? item.t : null, rtt);
      if (!C.rxEls.has(item.id)) C.rxEls.set(item.id, []);
      C.rxEls.get(item.id).push(...els);
      if (C.band.keyGain) for (const [a, b] of out) C.band.keyElement(toCtx(a), toCtx(b));
    }
    collectRx();
    watchPlayout();
    renderTrx();
    return C.tx ? POLL_TX_MS : POLL_RX_MS;
  }

  /** When the current over has ended at the sender: finish it once its last element has sounded (→ `done`). */
  function watchPlayout() {
    clearTimeout(C.doneTimer);
    const o = C.rx.cur;
    if (!o || !o.end) return;
    const wait = Math.max(0, o.lastEnd - performance.now());
    C.doneTimer = setTimeout(() => {
      if (C.rx.cur !== o) return;
      C.rx.finish();
      collectRx();
      renderTrx();
      pollSoon(0);   // report `done` → the channel is free for both sooner
    }, wait + 20);
  }

  // ---------- connection ----------
  async function startBand() {
    if (!C.on) return;
    if (!player.ready && !(await ensureAudio())) return;   // started by the first tap / key press instead
    if (!C.on) return;
    const base = bandParams(prefs.preset);
    C.band.start(bandParams(prefs.preset, {
      freq: (player.settings.freq || 600) + PEER_OFFSET_HZ,
      noise: Math.max(NOISE_LEVELS[prefs.noise], base.noise || 0),
    }));
  }

  function open(link) {
    if (C.on) close();
    C.on = true;
    C.peer = link.id;
    C.peerNick = link.nick;
    C.rx = new RxPlayout();
    C.lines = [];
    C.txTones = [];
    C.rxEls = new Map();
    C.batchMs = BATCH_MS;
    cfg = loadKeyConfig();
    keyer = new Keyer(cfg);
    renderControls();
    startBand();
  }

  function close() {
    C.on = false;
    C.peer = null;
    releaseAll();
    player.sidetoneOff();
    C.band.stop();
    C.tx = null;
    clearTimeout(C.txTimer);
    clearTimeout(C.doneTimer);
    C.txTimer = null;
    C.rx = new RxPlayout();
    C.channel = 'free';
    C.peerIds = [];
  }

  // ---------- transcripts (0.13.3) ----------
  const decode = (tones) => (tones.length ? decodeTones(tones, keyer.wpm, MORSE).text.trim() : '');

  function pushLine(dir, text) {
    if (!text) return;
    C.lines.push({ dir, text });
    if (C.lines.length > LOG_MAX) C.lines.shift();
  }

  function closeTxLine() {
    pushLine('tx', decode(C.txTones));
    C.txTones = [];
    renderLog();
  }

  /** Overs of the other station that have sounded to the end → one transcript line each. */
  function collectRx() {
    let added = false;
    for (const [id, els] of C.rxEls) {
      if (id > C.rx.lastId) continue;
      pushLine('rx', decode(els.map(([a, b]) => ({ start: a, end: b }))));
      C.rxEls.delete(id);
      added = true;
    }
    if (added) renderLog();
  }

  function renderLog() {
    const ul = $('#cw-log');
    if (!ul || !C.on) return;
    ul.textContent = '';
    const lines = C.lines.filter((l) => (l.dir === 'tx' ? prefs.showTx : prefs.showRx));
    if (prefs.showTx && C.tx && C.txTones.length) lines.push({ dir: 'tx', text: `${decode(C.txTones)}…`, live: true });
    for (const l of lines.slice(-12)) {
      const li = document.createElement('li');
      li.className = `cw-line ${l.dir}${l.live ? ' live' : ''}`;
      const who = document.createElement('b');
      who.textContent = l.dir === 'tx' ? t('cw.logMe') : C.peerNick;
      li.append(who, ` ${l.text}`);
      ul.append(li);
    }
    ul.hidden = !lines.length;
  }

  // ---------- rendering ----------
  function renderTrx() {
    const el = $('#cw-trx');
    if (!el || !C.on) return;
    const now = performance.now();
    const st = C.tx ? 'tx' : (blocked() ? 'rx' : 'free');
    el.className = `cw-trx ${st}`;
    el.textContent = t(`cw.trx.${st}`);
    $('#cw-busy').hidden = now > C.busyNote;
    for (const b of document.querySelectorAll('.cw-paddles .key-paddle')) b.classList.toggle('locked', st === 'rx');
    const d = C.rx.avgDelay();
    $('#cw-delay').textContent = d === null ? '' : t('cw.delay', { s: fmtNum(d / 1000, 1) });
  }

  function renderControls() {
    const type = $('#cw-key-type');
    if (!type.options.length) {
      for (const k of KEY_UI_TYPES) type.add(new Option(t(`key.type.${k}`), k));
      for (const k of Object.keys(NOISE_LEVELS)) $('#cw-noise').add(new Option(t(`cw.noise.${k}`), k));
      for (const k of CW_PRESETS) $('#cw-preset').add(new Option(k === 'clean' ? t('cw.presetNone') : t(`band.preset.${k}`), k));
    }
    type.value = KEY_UI_TYPES.includes(cfg.type) ? cfg.type : KEY_UI_TYPES[0];
    $('#cw-key-wpm').min = KEYER_WPM_MIN;
    $('#cw-key-wpm').max = KEYER_WPM_MAX;
    $('#cw-key-wpm').value = cfg.wpm;
    $('#cw-noise').value = prefs.noise;
    $('#cw-preset').value = prefs.preset;
    $('#cw-show-tx').checked = prefs.showTx;
    $('#cw-show-rx').checked = prefs.showRx;
    renderLog();
    $('#cw-dash').hidden = cfg.type === 'straight';   // the straight key has one contact
    renderTrx();
  }

  function applyKey() {
    releaseAll();
    saveKeyConfig(cfg);
    keyer = new Keyer(cfg);
    $('#cw-dash').hidden = cfg.type === 'straight';
  }
  $('#cw-key-type').addEventListener('change', (e) => { cfg.type = e.target.value; applyKey(); });
  $('#cw-key-wpm').addEventListener('change', (e) => {
    const v = Math.round(Number(e.target.value));
    cfg.wpm = Math.min(KEYER_WPM_MAX, Math.max(KEYER_WPM_MIN, Number.isFinite(v) ? v : cfg.wpm));
    e.target.value = cfg.wpm;
    applyKey();
  });
  for (const id of ['#cw-noise', '#cw-preset']) {
    $(id).addEventListener('change', () => {
      prefs.noise = $('#cw-noise').value;
      prefs.preset = $('#cw-preset').value;
      savePrefs(prefs);
      if (C.on) startBand();
    });
  }

  for (const id of ['#cw-show-tx', '#cw-show-rx']) {
    $(id).addEventListener('change', () => {
      prefs.showTx = $('#cw-show-tx').checked;
      prefs.showRx = $('#cw-show-rx').checked;
      savePrefs(prefs);
      renderLog();
    });
  }

  // on-screen paddles (Pointer Events, multitouch for squeezing) – as on the key page
  for (const [id, side] of [['#cw-dot', 'dot'], ['#cw-dash', 'dash']]) {
    const b = $(id);
    const up = (e) => {
      if (!C.held[side]) return;
      C.held[side] = false;
      b.classList.remove('down');
      if (C.sent[side]) { C.sent[side] = false; input(side, false, e.timeStamp); }
    };
    b.addEventListener('pointerdown', async (e) => {
      e.preventDefault();
      try { b.setPointerCapture(e.pointerId); } catch (err) { /* not supported */ }
      if (C.held[side]) return;
      C.held[side] = true;
      b.classList.add('down');
      const ts = e.timeStamp;
      if (!player.ready) { await ensureAudio(); if (C.on && !C.band.keyGain) startBand(); }
      if (!C.held[side] || C.sent[side]) return;
      C.sent[side] = true;
      input(side, true, ts);
    });
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('lostpointercapture', up);
    b.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  window.addEventListener('blur', () => { if (C.on) releaseAll(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && C.on) releaseAll(); });

  return {
    query() {
      const q = C.rx.query();
      return `?over=${q.over}&n=${q.n}&done=${q.done}`;
    },
    onState,
    onStop() { if (C.on) close(); },
    /** keydown / keyup in the room; true = handled (the caller prevents the default – Ctrl shortcuts). */
    onKey(e, down) {
      if (!C.on) return false;
      const side = e.code === cfg.dot ? 'dot' : (e.code === cfg.dash ? 'dash' : null);
      if (!side) return false;
      // own autorepeat filter (validation #33, see keyerui.js)
      if (down) {
        if (C.keys.has(e.code)) return true;
        C.keys.add(e.code);
      } else {
        if (!C.keys.has(e.code)) return true;
        C.keys.delete(e.code);
        if (!e.ctrlKey) {
          for (const code of [...C.keys]) {
            if (code.startsWith('Control')) {
              C.keys.delete(code);
              input(code === cfg.dot ? 'dot' : 'dash', false, e.timeStamp);
            }
          }
        }
      }
      if (down && !player.ready) {
        ensureAudio().then(() => { if (C.on && !C.band.keyGain) startBand(); });
        return true;
      }
      input(side, down, e.timeStamp);
      return true;
    },
  };
}
