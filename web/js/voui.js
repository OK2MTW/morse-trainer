// SPDX-License-Identifier: EUPL-1.2
// 0.16.0 – the virtual operator in the CW room (UI): settings, keying with the HW stream, the end of the user's over
// (K / KN / BK / SK / AR or silence), the answer of the VO on the band (LiveBand, a weak noise always), break-in after
// a word, the transcript and what the VO heard. Logic: vo.js. Nothing goes to the server; only the settings stay in
// localStorage. The VO never keys the HW (H-21) – it only sounds here.
import { t } from './i18n.js';
import { loadKeyConfig, HW_WPM } from './keyerui.js';
import { KeyInput, hwState } from './keyinput.js';
import { LiveBand, bandParams } from './band.js';
import { decodeTones, loadWordHint, saveWordHint } from './decoder.js';
import { MORSE } from './charset.js';
import {
  VirtualOperator, VO_MODES, VO_REPLY_MS, VO_SILENCE_MS, VO_WPM, VO_WPM_MIN, VO_WPM_MAX, overText, overEnded,
  voTimings, looksLikeCall,
  VO_QRS,
} from './vo.js';
import { HwMidi, KeyTempo, KEY_WPM_ID, sharedMidi, midiSwitchOn } from './hwmidi.js';

const $ = (s) => document.querySelector(s);
const STORE = 'morse-vo';
const WPM_CHOICES = ['auto', 12, 15, 18, 20, 22, 25, 28, 30, 35];
const FW_CHOICES = [0, 15, 12, 10, 8];
const SHOW = ['after', 'live', 'hide'];
const PRESETS = ['clean', 'qsb', 'flutter', 'qrn', 'qrm', 'evening'];
const DEFAULTS = { mode: 'quick', call: '', wpm: 'auto', fw: 0, show: 'after', preset: 'clean', keyTempo: false };
const NOISE = 0.08;          // a weak noise always (the "min" of the CW room)
const PEER_OFFSET_HZ = 50;   // the VO sounds 50 Hz above the own sidetone (as the other station in the room)
const LEAD_MS = 120;         // a word of the VO is put on the band this long before it sounds
const START_MS = 150;
const LOG_MAX = 20;

function load() {
  try {
    const p = { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(STORE)) || {}) };
    if (!VO_MODES.includes(p.mode)) p.mode = DEFAULTS.mode;
    if (!WPM_CHOICES.includes(p.wpm)) p.wpm = DEFAULTS.wpm;
    if (!FW_CHOICES.includes(p.fw)) p.fw = DEFAULTS.fw;
    if (!SHOW.includes(p.show)) p.show = DEFAULTS.show;
    if (!PRESETS.includes(p.preset)) p.preset = DEFAULTS.preset;
    p.keyTempo = p.keyTempo === true;
    p.call = typeof p.call === 'string' ? p.call.slice(0, 12) : '';
    return p;
  } catch (e) { return { ...DEFAULTS }; }
}
function save(p) { try { localStorage.setItem(STORE, JSON.stringify(p)); } catch (e) { /* private mode */ } }

const clampWpm = (w) => Math.min(VO_WPM_MAX, Math.max(VO_WPM_MIN, Math.round(w)));

/** getNick() = the nickname (a call sign suggestion), isLinked() = a real connection in the room is running. */
export function initVoUi({ player, ensureAudio, getNick, isLinked }) {
  const prefs = load();
  const V = {
    on: false, running: false, vo: null, cfg: null, input: null, band: new LiveBand(player), manual: null,
    tones: [], timer: null, play: null, lines: [], heard: null, dot: 1200 / HW_WPM, wpmSet: false,
    kt: null, ktOff: null, ktBusy: false, keyOk: false,
  };
  const toCtx = (ms) => player.ctx.currentTime + (ms - performance.now()) / 1000;

  // ---------- panel ----------
  function fillSelects() {
    if ($('#cw-vo-mode').options.length) return;
    for (const m of VO_MODES) $('#cw-vo-mode').add(new Option(t(`vo.mode.${m}`), m));
    for (const w of WPM_CHOICES) $('#cw-vo-wpm').add(new Option(w === 'auto' ? t('vo.wpmAuto') : `${w} WPM`, String(w)));
    for (const f of FW_CHOICES) $('#cw-vo-fw').add(new Option(f ? `${f} WPM` : t('vo.fwOff'), String(f)));
    for (const s of SHOW) $('#cw-vo-show').add(new Option(t(`vo.show.${s}`), s));
    for (const k of PRESETS) $('#cw-vo-preset').add(new Option(k === 'clean' ? t('cw.presetNone') : t(`band.preset.${k}`), k));
  }

  function renderSetup() {
    fillSelects();
    $('#cw-vo-mode').value = prefs.mode;
    $('#cw-vo-mode-hint').textContent = t(`vo.modeHint.${prefs.mode}`);
    const nick = (getNick() || '').toUpperCase();
    $('#cw-vo-mycall').value = prefs.call || (looksLikeCall(nick) ? nick : '');
    $('#cw-vo-wpm').value = String(prefs.wpm);
    $('#cw-vo-fw').value = String(prefs.fw);
    $('#cw-vo-show').value = prefs.show;
    $('#cw-vo-preset').value = prefs.preset;
    $('#cw-vo-keytempo').checked = prefs.keyTempo;
    $('#cw-vo-keytempo-row').hidden = !V.keyOk;
    $('#cw-vo-keytempo-hint').hidden = !V.keyOk;
    $('#cw-vo-setup').hidden = V.running;
    $('#cw-vo-run').hidden = !V.running;
    $('#cw-vo-call').textContent = V.vo ? t('vo.callIs', { call: V.vo.call }) : '';
  }

  function readSetup() {
    prefs.mode = $('#cw-vo-mode').value;
    prefs.call = $('#cw-vo-mycall').value.trim().toUpperCase().replace(/[^A-Z0-9/]/g, '').slice(0, 12);
    const w = $('#cw-vo-wpm').value;
    prefs.wpm = w === 'auto' ? 'auto' : Number(w);
    prefs.fw = Number($('#cw-vo-fw').value);
    prefs.show = $('#cw-vo-show').value;
    prefs.preset = $('#cw-vo-preset').value;
    if (V.keyOk) prefs.keyTempo = $('#cw-vo-keytempo').checked;
    save(prefs);
  }

  function open() {
    if (isLinked()) return;   // the room says why (cwroomui.js)
    V.on = true;
    $('#cw-vo').hidden = false;
    renderSetup();
    $('#cw-vo').scrollIntoView({ block: 'nearest' });
    probeKey();
  }

  // ---------- 0.16.4 (Z-26): the user's QRS / QRQ changes the tempo of the HW key over USB MIDI ----------
  /** The option is offered only with the MIDI switch on (Firmware card) and a key that answered (FW 0.4.0+). */
  async function probeKey() {
    if (!midiSwitchOn() || !HwMidi.supported()) { V.keyOk = false; return; }
    const m = sharedMidi();
    try {
      if (!m.connected() && !(await m.open())) { V.keyOk = false; return; }
      if (!m.info) await m.getInfo();
      V.keyOk = true;
    } catch (e) { V.keyOk = false; }
    if (!V.running) renderSetup();
  }

  const keyMsg = (key, params) => { $('#cw-vo-key-msg').textContent = key ? t(key, params) : ''; };

  async function keyTempoStart() {
    keyTempoStop(false);
    keyMsg('');
    if (!prefs.keyTempo || !V.keyOk) return;
    const m = sharedMidi();
    const kt = V.kt = new KeyTempo(VO_QRS);
    V.ktOff = m.listen({
      changed: (d) => { if (d.id === KEY_WPM_ID && V.kt === kt) { kt.changed(d.value); keyMsg('vo.key.hand', { wpm: d.value }); } },
    });
    try {
      let w;
      try { w = await m.get(KEY_WPM_ID); } catch (e) { w = (await m.getAll()).wpm; }  // GET not answered → GET_ALL
      if (Number.isInteger(w)) kt.known(w);
    } catch (e) { /* no speed known → nothing will be changed */ }
  }

  /** Sends the pending speed – only while the user is not keying (the VO answers after K). */
  async function keySend(w, restore) {
    const kt = V.kt;
    if (!kt || w === null || V.ktBusy) return;
    if (!restore && V.manual !== null) return;
    V.ktBusy = true;
    try {
      const d = await sharedMidi().set(KEY_WPM_ID, w);
      if (d.type !== 'ack') throw new Error(d.reason || 'reply');
      kt.sent(w);
      keyMsg(restore ? 'vo.key.back' : 'vo.key.set', { wpm: w });
    } catch (e) {
      keyMsg('vo.key.err');
    } finally { V.ktBusy = false; }
  }

  function keyTempoReply(heard) {
    if (!V.kt || !heard) return;
    const dir = heard.qrs && !heard.qrq ? -1 : heard.qrq && !heard.qrs ? 1 : 0;
    if (dir) keySend(V.kt.request(dir), false);
  }

  /** The end of the connection: the original speed back (unless the KEY button chose last). */
  function keyTempoStop(restore = true) {
    const kt = V.kt;
    if (!kt) return;
    if (restore) keySend(kt.restoreTo(), true).finally(() => { if (V.kt === kt) V.kt = null; });
    else V.kt = null;
    V.ktOff?.();
    V.ktOff = null;
  }

  function close() {
    stopRun();
    V.on = false;
    V.vo = null;
    $('#cw-vo').hidden = true;
  }

  // ---------- a QSO ----------
  async function start() {
    readSetup();
    if (!player.ready && !(await ensureAudio())) return;
    stopRun();
    V.cfg = loadKeyConfig();
    V.input = new KeyInput(V.cfg);
    const now = new Date();
    V.vo = new VirtualOperator({
      mode: prefs.mode, userCall: prefs.call, hour: now.getHours(), year: now.getFullYear(),
      wpm: prefs.wpm === 'auto' ? VO_WPM : prefs.wpm,
    });
    V.wpmSet = prefs.wpm !== 'auto';
    V.lines = [];
    V.tones = [];
    V.heard = null;
    V.running = true;
    keyTempoStart();
    const base = bandParams(prefs.preset);
    V.band.start(bandParams(prefs.preset, {
      freq: (player.settings.freq || 600) + PEER_OFFSET_HZ, noise: Math.max(NOISE, base.noise || 0),
    }));
    renderSetup();
    renderAll();
  }

  function stopRun() {
    clearTimeout(V.timer);
    if (V.play) V.play.timers.forEach(clearTimeout);
    V.play = null;
    if (V.manual !== null && player.ready) player.sidetoneKey(false);
    V.manual = null;
    V.input?.releaseAll();
    V.band.stop();
    V.running = false;
    keyTempoStop();
  }

  function keyEvent(down, ts) {
    if (down) {
      if (V.manual !== null) return;
      if (V.play) breakIn();
      clearTimeout(V.timer);
      V.manual = ts;
      if (V.cfg.hwSidetone && player.ready) player.sidetoneKey(true);
    } else if (V.manual !== null) {
      if (V.cfg.hwSidetone && player.ready) player.sidetoneKey(false);
      V.tones.push({ start: V.manual, end: Math.max(V.manual, ts) });
      V.manual = null;
      armEnd();
      renderLog();
    }
    renderTrx();
  }

  const decodeOwn = () => {
    if (V.tones.length <= 1 || V.wordHint === undefined) V.wordHint = loadWordHint(); // 0.16.3: every over starts with the hand's threshold
    const dec = decodeTones(V.tones, HW_WPM, MORSE, { machine: true, dot: V.dot, word: V.wordHint });
    if (V.tones.length) saveWordHint(dec);
    return dec;
  };

  /** The end of the over: VO_REPLY_MS after K / KN / BK / SK / AR, else VO_SILENCE_MS of silence. */
  function armEnd() {
    clearTimeout(V.timer);
    const text = overText(decodeOwn().chars);
    V.timer = setTimeout(endOver, overEnded(text) ? VO_REPLY_MS : VO_SILENCE_MS);
  }

  function endOver() {
    if (V.manual !== null || !V.tones.length || !V.running) return;
    const dec = decodeOwn();
    V.dot = dec.dot;
    const text = overText(dec.chars);
    V.tones = [];
    if (!V.wpmSet && text) { V.vo.wpm = clampWpm(dec.wpm); V.wpmSet = true; }   // the VO at the speed of the key
    pushLine('me', text || '?');
    const r = V.vo.reply(text);
    V.heard = r.heard;
    keyTempoReply(r.heard);
    if (r.text) playVo(r.text, r.wpm);
    renderAll();
  }

  /** The VO sends: words are put on the band one by one (break-in stops after the current word). */
  function playVo(text, wpm) {
    const fw = prefs.fw && prefs.fw < wpm ? prefs.fw : null;
    const tm = voTimings(text, wpm, fw, MORSE);
    const words = text.split(/\s+/);
    const t0 = performance.now() + START_MS;
    const P = { words, timers: [], shown: 0, cur: -1, curEnd: t0, stopped: false };
    V.play = P;
    const byWord = [];
    for (const e of tm.els) (byWord[e.word] ||= []).push(e);
    byWord.forEach((els, wi) => {
      if (!els) return;
      const wEnd = t0 + els.at(-1).end;
      P.timers.push(setTimeout(() => {
        if (V.play !== P || P.stopped) return;
        for (const e of els) V.band.keyElement(toCtx(t0 + e.start), toCtx(t0 + e.end));
        P.cur = wi;
        P.curEnd = wEnd;
      }, Math.max(0, t0 + els[0].start - LEAD_MS - performance.now())));
      P.timers.push(setTimeout(() => {
        if (V.play !== P || P.stopped) return;
        P.shown = wi + 1;
        if (prefs.show === 'live') renderLog();
      }, Math.max(0, wEnd - performance.now())));
    });
    P.timers.push(setTimeout(() => finishVo(P, words.length), Math.max(0, t0 + tm.end - performance.now()) + 50));
    renderTrx();
    renderLog();
  }

  function finishVo(P, n) {
    if (V.play !== P) return;
    P.timers.forEach(clearTimeout);
    V.play = null;
    pushLine('vo', P.words.slice(0, n).join(' ') + (n < P.words.length ? ' …' : ''));
    renderAll();
  }

  /** The user keys while the VO sends: the VO finishes the current word and goes quiet. */
  function breakIn() {
    const P = V.play;
    if (P.stopped) return;
    P.stopped = true;
    P.timers.forEach(clearTimeout);
    P.timers = [setTimeout(() => finishVo(P, P.cur + 1), Math.max(0, P.curEnd - performance.now()) + 20)];
  }

  function pushLine(dir, text) {
    V.lines.push({ dir, text });
    if (V.lines.length > LOG_MAX) V.lines.shift();
  }

  // ---------- rendering ----------
  function renderTrx() {
    if (!V.running) return;
    const st = V.manual !== null || V.tones.length ? 'tx' : (V.play ? 'rx' : 'free');
    const el = $('#cw-vo-trx');
    el.className = `cw-trx ${st}`;
    el.textContent = t(`cw.trx.${st}`);
    $('#cw-vo-wpm-now').textContent = V.vo ? t('vo.wpmNow', { wpm: V.vo.wpm }) : '';
    $('#cw-vo-nokey').hidden = hwState.seen;
  }

  function voText(text) { return prefs.show === 'hide' ? t('vo.hidden') : text; }

  function renderLog() {
    const ul = $('#cw-vo-log');
    ul.textContent = '';
    const lines = V.lines.map((l) => ({ ...l, text: l.dir === 'vo' ? voText(l.text) : l.text }));
    if (V.tones.length) lines.push({ dir: 'me', text: `${overText(decodeOwn().chars)}…`, live: true });
    if (V.play && prefs.show === 'live' && V.play.shown) {
      lines.push({ dir: 'vo', text: `${V.play.words.slice(0, V.play.shown).join(' ')}…`, live: true });
    }
    for (const l of lines.slice(-12)) {
      const li = document.createElement('li');
      li.className = `cw-line ${l.dir === 'me' ? 'tx' : 'rx'}${l.live ? ' live' : ''}`;
      const who = document.createElement('b');
      who.textContent = l.dir === 'me' ? t('cw.logMe') : t('vo.logVo');
      li.append(who, ` ${l.text}`);
      ul.append(li);
    }
    ul.hidden = !lines.length;
  }

  function renderHeard() {
    const h = V.heard;
    const el = $('#cw-vo-heard');
    if (V.vo?.phase === 'done' && !V.play) { el.textContent = t('vo.done'); return; }
    if (!h) { el.textContent = ''; return; }
    const parts = [];
    if (h.cq) parts.push('CQ');
    if (h.toVo) parts.push(t('vo.h.toVo'));
    if (h.from) parts.push(t('vo.h.from', { v: h.from }));
    if (h.rst) parts.push(t('vo.h.rst', { v: h.rst }));
    if (h.name) parts.push(t('vo.h.name', { v: h.name }));
    if (h.qth) parts.push(t('vo.h.qth', { v: h.qth }));
    if (h.asks.length) parts.push(t('vo.h.asks', { v: h.asks.join(', ') }));
    if (h.agn) parts.push('AGN');
    if (h.qrs) parts.push('QRS');
    if (h.qrq) parts.push('QRQ');
    if (h.bye) parts.push('73 / SK');
    el.textContent = parts.length ? t('vo.heard', { v: parts.join(' · ') }) : t('vo.heardNothing');
  }

  function renderAll() {
    $('#cw-vo-call').textContent = V.vo ? t('vo.callIs', { call: V.vo.call }) : '';
    renderTrx();
    renderLog();
    renderHeard();
  }

  // ---------- events ----------
  document.addEventListener('cw-vo-open', open);
  $('#cw-vo-mode').addEventListener('change', () => { $('#cw-vo-mode-hint').textContent = t(`vo.modeHint.${$('#cw-vo-mode').value}`); });
  $('#cw-vo-start').addEventListener('click', start);
  $('#cw-vo-close').addEventListener('click', close);
  $('#cw-vo-end').addEventListener('click', close);
  $('#cw-vo-new').addEventListener('click', () => { stopRun(); V.vo = null; renderSetup(); });
  $('#cw-vo-cq').addEventListener('click', () => {
    if (!V.running || V.play || V.tones.length) return;
    const r = V.vo.cq();
    playVo(r.text, r.wpm);
    renderAll();
  });
  window.addEventListener('blur', () => { if (V.running && V.manual !== null) keyEvent(false, performance.now()); });

  return {
    /** keydown / keyup in the room; true = handled (only while a QSO with the VO runs). */
    onKey(e, down) {
      if (!V.on || !V.running || isLinked()) return false;
      const acts = V.input.key(e.code, down);
      if (acts === null) return false;
      for (const a of acts) {
        if (a.kind !== 'stream') continue;
        if (a.down && !hwState.seen) hwState.seen = true;
        keyEvent(a.down, e.timeStamp);
      }
      return true;
    },
    /** Leaving the room. */
    stop() { if (V.on) close(); },
  };
}
