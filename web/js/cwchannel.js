// SPDX-License-Identifier: EUPL-1.2
// 0.13.2 – CW room channel: keying with the HW key (0.15.3: the stream of the HW keyer only, settings of the key
// page), batches to the server,
// taking the channel by the first key down, playing the other station on the band (band.js LiveBand) with the reserve
// of cwlink.js, the TX / RX / free label and the measured delay. Half duplex like on the air: while the other station
// holds the channel (or its over still sounds here) the key is blocked.
import { t, fmtNum } from './i18n.js';
import { api, ApiError } from './api.js';
import { loadKeyConfig, HW_WPM } from './keyerui.js';
import { KeyInput, hwState } from './keyinput.js';
import { LiveBand, bandParams } from './band.js';
import { decodeTones, loadWordHint, saveWordHint } from './decoder.js';
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
const BUSY_NOTE_MS = 2500;
const AHEAD_MS = 50;         // elements are sent once they have started (+ this margin)
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
  const C = {
    on: false, peer: null, band: new LiveBand(player), rx: new RxPlayout(), tx: null, txTimer: null,
    flushing: false, batchMs: BATCH_MS, channel: 'free', peerIds: [], manual: null,
    input: new KeyInput(cfg), doneTimer: null, busyNote: 0, txTones: [], rxEls: new Map(), lines: [], peerNick: '',
    dot: 1200 / HW_WPM,   // the measured dot of the own key (ms) – the end of an over is a silence of 7 dots
  };

  const toCtx = (ms) => player.ctx.currentTime + (ms - performance.now()) / 1000;
  const keyDown = () => C.manual !== null;
  // 0.14.2 (spec A-16): a HW keyer – the stream goes out as it is, the key plays the sidetone
  const sidetoneOn = () => cfg.hwSidetone;

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
    const end = o.silent(now, C.dot, keyDown());
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
  function txElement(start, end) {
    if (C.tx && C.tx.tooLong(start)) {
      const o = C.tx;
      const els = o.rest();
      C.tx = null;
      closeTxLine();
      if (o.id) api('POST', '/cw/tx', { over: o.id, els, end: true }).catch(() => {});
    }
    const fresh = !C.tx;
    if (fresh) { C.tx = new TxOver(start); C.txTones = []; C.wordHint = loadWordHint(); }
    C.tx.add(start, end);
    C.txTones.push({ start, end, el: null });
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

  // ---------- keying (HW stream) ----------
  function manualKey(down, ts) {
    if (down) {
      if (C.manual !== null) return;
      C.manual = ts;
      ensureOver(ts);   // the first key down takes the channel at once
      if (sidetoneOn() && player.ready) player.sidetoneKey(true);
    } else if (C.manual !== null) {
      if (sidetoneOn() && player.ready) player.sidetoneKey(false);
      const s = C.manual;
      C.manual = null;
      if (C.tx) txElement(s, Math.max(s, ts));   // (a very long over continues as a new one)
    }
  }

  /** 0.14.2: one change of the HW stream – sent as a hand-keyed tone; no sound is needed to send. */
  function hwInput(down, ts) {
    if (!C.on) return;
    if (down && blocked()) { noteBusy(); return; }
    manualKey(down, ts);
  }

  function releaseAll() {
    if (C.manual !== null) manualKey(false, performance.now());
    C.input.releaseAll();
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
    C.input = new KeyInput(cfg);
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
  // 0.15.3: both stations key with a HW keyer → machine timing for both. The elements of the other station are its
  // own key times (ms from the start of its over, rounded to 1 ms – cwlink.js TxOver), not the playout times here,
  // so the reserve of the network does not change the gaps (tests/test_decoder_hw.py checks the rounding).
  const decode = (tones, own = false) => {
    if (!tones.length) return '';
    // 0.16.3: own keying with the threshold this device learned from the hand (the other station: its own rhythm)
    if (own && C.wordHint === undefined) C.wordHint = loadWordHint();
    const dec = decodeTones(tones, HW_WPM, MORSE, { machine: true, dot: own ? C.dot : null, word: own ? C.wordHint : undefined });
    if (own) { C.dot = dec.dot; saveWordHint(dec); }
    return dec.text.trim();
  };

  function pushLine(dir, text) {
    if (!text) return;
    C.lines.push({ dir, text });
    if (C.lines.length > LOG_MAX) C.lines.shift();
  }

  function closeTxLine() {
    pushLine('tx', decode(C.txTones, true));
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
    if (prefs.showTx && C.tx && C.txTones.length) lines.push({ dir: 'tx', text: `${decode(C.txTones, true)}…`, live: true });
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
    $('#cw-nokey').hidden = hwState.seen;
    const d = C.rx.avgDelay();
    $('#cw-delay').textContent = d === null ? '' : t('cw.delay', { s: fmtNum(d / 1000, 1) });
  }

  function renderControls() {
    if (!$('#cw-noise').options.length) {
      for (const k of Object.keys(NOISE_LEVELS)) $('#cw-noise').add(new Option(t(`cw.noise.${k}`), k));
      for (const k of CW_PRESETS) $('#cw-preset').add(new Option(k === 'clean' ? t('cw.presetNone') : t(`band.preset.${k}`), k));
    }
    $('#cw-noise').value = prefs.noise;
    $('#cw-preset').value = prefs.preset;
    $('#cw-show-tx').checked = prefs.showTx;
    $('#cw-show-rx').checked = prefs.showRx;
    renderLog();
    renderTrx();
  }

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
      // 0.14.2: the shared keyboard input of the key page (keyinput.js)
      const acts = C.input.key(e.code, down);
      if (acts === null) return false;
      if (down && !player.ready) ensureAudio().then(() => { if (C.on && !C.band.keyGain) startBand(); });
      for (const a of acts) {
        if (a.kind !== 'stream') continue;   // the paddle states of mode C are not sent (the stream is the keying)
        if (a.down && !hwState.seen) { hwState.seen = true; renderTrx(); }
        hwInput(a.down, e.timeStamp);
      }
      return true;
    },
  };
}
