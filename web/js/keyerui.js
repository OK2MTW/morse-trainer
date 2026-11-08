// SPDX-License-Identifier: EUPL-1.2
// VK (0.11.0, docs/spec-klic.md A-01–A-03, A-10–A-12): Settings → Telegraph key (experimental, coaches only).
// Keyer with sidetone; inputs: keyboard / USB key converter (a USB keyboard – learned keys, default Left/Right Ctrl)
// and two on-screen paddles (Pointer Events, multitouch for squeezing). Event log with times for the acceptance test
// of the converter. Nothing is sent to the server; the key settings belong to the device (localStorage).
import { t, fmtNum } from './i18n.js';
import { MORSE } from './charset.js';
import { Keyer, KEY_TYPES, KEYER_WPM_MIN, KEYER_WPM_MAX, manualSide } from './keyer.js';
import { decodeTones } from './decoder.js';
import { traceOn, traceBegin, traceEnd, flushTrace } from './trace.js';
import {
  sendMetrics, focusOf, evaluateSending, sessionSummary, sendTask, EVAL_WINDOW, SEND_KINDS, SEND_TASKS,
  SEND_END_MS, SEND_END_UNITS,
} from './sendeval.js';

const STORE = 'morse-key';
// 0.12.2: the bug stays in the keyer logic (a USB converter may bring it back) but is not offered – nobody used it
const UI_TYPES = KEY_TYPES.filter((k) => k !== 'bug');
const DEFAULTS = {
  type: 'iambicB', wpm: 18, swap: false, sidetone: true, dot: 'ControlLeft', dash: 'ControlRight', exKind: 'char',
};
const LOOK_MS = 12;        // the next element is decided this much before its gap ends; the audio clock keeps the rhythm
const START_S = 0.003;     // a tone from idle starts this far ahead in the audio clock
const LOG_MAX = 40;
const ELEMENTS_MAX = 400;
const EST_MIN_TONES = 6;   // the tempo estimate of hand-keyed tones is shown from 6 tones on
const EVAL_MIN_TONES = 12; // the form analysis of free sending is shown from 12 tones on
const EXREC_MAX = 20;      // exercise tasks kept for the recording
const TRACE_KEY = 'klic';  // 0.12.3: kind of the debug record = server TRACE_KEY
const rnd = (tn) => ({ s: Math.round(tn.start * 10) / 10, e: Math.round(tn.end * 10) / 10, ...(tn.el ? { el: tn.el } : {}) });

const f1 = (x) => fmtNum(x, 1);
const ST_MARK = { good: '●', ok: '◐', bad: '○' };   // the colour is not the only signal (accessibility)

/**
 * D3 (0.11.4): form metrics as a list with a status mark + one sentence "focus on" (about the task, not the person).
 * box = an element; m = sendMetrics(); ev = evaluateSending() or null (free sending).
 */
export function renderEval(box, m, ev = null) {
  box.textContent = '';
  const ul = document.createElement('ul');
  ul.className = 'send-metrics';
  const row = (st, text) => {
    const li = document.createElement('li');
    if (st) {
      li.className = `st-${st}`;
      const mk = document.createElement('span');
      mk.className = 'st-mark';
      mk.textContent = ST_MARK[st];
      mk.title = t(`send.st.${st}`);
      li.append(mk, ' ');
    }
    li.append(text);
    ul.append(li);
  };
  if (ev) row(ev.acc.st, t('send.acc', { ok: ev.acc.ok, n: ev.acc.n, pct: Math.round(ev.acc.v * 100) }));
  if (m.ratio) row(m.ratio.st, t('send.ratio', { v: f1(m.ratio.v) }));
  if (m.inGap) row(m.inGap.st, t('send.inGap', { v: f1(m.inGap.v) }));
  if (m.charGap) row(m.charGap.st, t('send.charGap', { v: f1(m.charGap.v) }));
  if (m.wordGap) row(m.wordGap.st, t('send.wordGap', { v: f1(m.wordGap.v) }));
  if (m.stability) row(m.stability.st, t('send.stability', { v: Math.round(m.stability.v * 100) }));
  row(null, m.effWpm ? t('send.wpm', { c: Math.round(m.charWpm), e: Math.round(m.effWpm) })
    : t('send.wpmChar', { c: Math.round(m.charWpm) }));
  if (ev && ev.fixes) row(null, t('send.fixes', { n: ev.fixes }));
  const f = focusOf(m, ev);
  const p = document.createElement('p');
  p.className = 'send-focus';
  if (f.key === 'good') p.textContent = t('send.focus.good');
  else if (f.key === 'acc') {
    p.textContent = t('send.focus.acc', { want: f.sub.want, wantCode: f.sub.wantCode, got: f.sub.got, gotCode: f.sub.gotCode });
  } else if (f.key === 'stability') p.textContent = t('send.focus.stability', { v: Math.round(f.v * 100) });
  else p.textContent = t(`send.focus.${f.key}.${f.dir}`, { v: f1(f.v) });
  box.append(ul, p);
}

const $ = (sel) => document.querySelector(sel);

function load() {
  try {
    const c = { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(STORE)) || {}) };
    if (!UI_TYPES.includes(c.type)) c.type = DEFAULTS.type;
    if (!SEND_KINDS.includes(c.exKind)) c.exKind = DEFAULTS.exKind;
    c.wpm = Math.min(KEYER_WPM_MAX, Math.max(KEYER_WPM_MIN, Math.round(Number(c.wpm) || DEFAULTS.wpm)));
    return c;
  } catch (e) { return { ...DEFAULTS }; }
}
function save(cfg) { try { localStorage.setItem(STORE, JSON.stringify(cfg)); } catch (e) { /* private mode */ } }
/** 0.13.2: the CW room uses the same key settings (type, tempo, keys) as the key page. */
export const loadKeyConfig = load;
export const saveKeyConfig = save;
export { UI_TYPES as KEY_UI_TYPES };

export function initKeyerUi({ player, ensureAudio, getChars }) {
  const cfg = load();
  let keyer = new Keyer(cfg);
  const S = {
    timer: null, chainEnd: 0, elements: [], learn: null, log: [], t0: null, prev: null, presses: 0,
    manual: null, held: { dot: false, dash: false }, sent: { dot: false, dash: false }, open: false,
    keys: new Set(),   // codes of the keys held down (own autorepeat filter, see onKey)
    exRec: [],         // 0.12.3: the last exercise tasks with their tones (for the recording)
  };

  // ---------- keying ----------
  // D3 (0.11.3): tones in one time line in ms = the event clock (performance.now / event.timeStamp). Hand-keyed
  // tones (straight key, bug dashes) are measured from the event time stamps (el null = the decoder classifies them
  // by length); elements of the automatic keyer are known and converted from the audio clock. The output latency
  // of the sound does not enter decoding.
  const audioToEventMs = (s) => performance.now() + (s - player.ctx.currentTime) * 1000;

  function addElement(el, start, end) {
    S.elements.push({ el, start, end });
    if (X.phase === 'send') exTone({ el, start, end });
    if (S.elements.length > ELEMENTS_MAX) S.elements.splice(0, S.elements.length - ELEMENTS_MAX);
    renderOut();
  }

  function startElement(el, at) {
    const dur = keyer.elementMs(el) / 1000;
    if (cfg.sidetone) player.sidetoneElement(at, at + dur);
    const start = audioToEventMs(at);
    addElement(el, start, start + dur * 1000);
    S.chainEnd = at + dur + keyer.unit / 1000;
    clearTimeout(S.timer);
    S.timer = setTimeout(decide, Math.max(0, (S.chainEnd - player.ctx.currentTime) * 1000 - LOOK_MS));
  }

  function decide() {
    S.timer = null;
    const el = keyer.next();
    if (el) startElement(el, Math.max(S.chainEnd, player.ctx.currentTime + START_S));
  }

  function manualKey(down, ts) {
    if (down) {
      if (S.manual !== null) return;
      S.manual = ts;
      if (cfg.sidetone) player.sidetoneKey(true);
    } else if (S.manual !== null) {
      if (cfg.sidetone) player.sidetoneKey(false);
      addElement(null, S.manual, Math.max(S.manual, ts));
      S.manual = null;
    }
  }

  /** One contact change from any source (side = physical side before swapping). */
  function input(side, down, ts, src) {
    logEvent(side, down, ts, src);
    if (down) { clearTimeout(X.timer); X.timer = null; } // a task does not end while a paddle / the key is held
    if (!player.ready) return;
    const s = cfg.swap ? (side === 'dot' ? 'dash' : 'dot') : side;
    const man = manualSide(cfg.type);
    if (s === man) { manualKey(down, ts); return; }
    if (cfg.type === 'straight') return; // the straight key has one contact only
    if (down) { if (keyer.press(s)) decide(); } else keyer.release(s);
  }

  function releaseAll() {
    clearTimeout(S.timer);
    S.timer = null;
    keyer.releaseAll();
    if (S.manual !== null) manualKey(false, performance.now());
    for (const b of document.querySelectorAll('.key-paddle')) b.classList.remove('down');
    S.held = { dot: false, dash: false };
    S.keys.clear();
    S.sent = { dot: false, dash: false }; // held = finger on the button, sent = the press reached the keyer
  }

  // ---------- sending exercise (D3 step 3, 0.12.0): task → sending → evaluation; a series of SEND_TASKS ----------
  // Nothing goes to the server (that comes with D4, mode `vysilani`). Characters of the receive level.
  const X = { on: false, phase: null, target: '', tones: [], results: [], timer: null };

  function exTone(tone) {
    X.tones.push(tone);
    clearTimeout(X.timer);
    const dec = decodeTones([...X.tones].sort((a, b) => a.start - b.start), keyer.wpm, MORSE);
    const wait = Math.max(SEND_END_MS, SEND_END_UNITS * dec.dot);
    X.timer = setTimeout(exFinish, Math.max(0, tone.end - performance.now()) + wait);
  }

  function exNewTask() {
    X.target = sendTask(cfg.exKind, getChars(), Math.random, cfg.exKind === 'char' ? X.target : null);
    X.tones = [];
    X.phase = 'send';
    renderEx();
  }

  function exStart() {
    releaseAll();
    X.on = true;
    X.results = [];
    X.target = '';
    exNewTask();
    renderOut();
    $('#send-ex-run').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function exStop() {
    clearTimeout(X.timer);
    X.timer = null;
    X.on = false;
    X.phase = null;
    renderEx();
    renderOut();
  }

  function exFinish() {
    clearTimeout(X.timer);
    X.timer = null;
    if (X.phase !== 'send') return;
    if (S.manual !== null) return; // the key is still held
    const tones = [...X.tones].sort((a, b) => a.start - b.start);
    const dec = decodeTones(tones, keyer.wpm, MORSE);
    const ev = evaluateSending(X.target, tones, dec, MORSE);
    S.exRec.push({ target: X.target, text: dec.text, tones: tones.map(rnd) });
    if (S.exRec.length > EXREC_MAX) S.exRec.shift();
    ev.text = dec.text;
    X.results.push(ev);
    X.phase = 'result';
    renderEx();
  }

  function exNext() {
    if (X.phase !== 'result') return;
    if (X.results.length >= SEND_TASKS) { X.phase = 'summary'; renderEx(); return; }
    exNewTask();
  }

  /** Two rows aligned by the operations: the task above, what was sent below (copy-review styles). */
  function reviewRows(ev) {
    const sent = [...X.target.replace(/\s+/g, '')];
    const typed = [...ev.text.replace(/\s+/g, '')];
    const top = [];
    const bottom = [];
    for (const o of ev.ops) {
      if (o.op === 'ok') { top.push(['ok', sent[o.s]]); bottom.push(['ok', typed[o.t]]); }
      if (o.op === 'sub') { top.push(['', sent[o.s]]); bottom.push(['sub', typed[o.t]]); }
      if (o.op === 'del') { top.push(['del', sent[o.s]]); bottom.push(['del', '_']); }
      if (o.op === 'ins') { top.push(['', ' ']); bottom.push(['ins', typed[o.t]]); }
    }
    const box = document.createElement('div');
    box.className = 'copy-review';
    for (const [row, cls] of [[top, 'row'], [bottom, 'row typed']]) {
      const r = document.createElement('span');
      r.className = cls;
      for (const [c, ch] of row) {
        const sp = document.createElement('span');
        if (c) sp.className = c;
        sp.textContent = ch;
        r.append(sp);
      }
      box.append(r);
    }
    return box;
  }

  function renderEx() {
    const kindSel = $('#send-ex-kind');
    if (!kindSel.options.length) {
      for (const k of SEND_KINDS) {
        const o = document.createElement('option');
        o.value = k;
        kindSel.append(o);
      }
    }
    for (const o of kindSel.options) o.textContent = t(`send.ex.kind.${o.value}`);
    kindSel.value = cfg.exKind;
    $('#send-ex-intro').textContent = t('send.ex.intro', { n: getChars().length, tasks: SEND_TASKS });
    $('#send-ex-ctl').hidden = X.on;
    $('#send-ex-run').hidden = !X.on;
    // 0.12.2 (validation #32): task → paddles → buttons → evaluation, the free-sending analysis hidden – the paddles
    // stay right under the task on a phone
    $('#send-ex-tail').hidden = !X.on;
    $('#key-free').hidden = X.on;
    if (!X.on) return;
    const res = $('#send-ex-result');
    const n = X.results.length;
    $('#send-ex-done').hidden = X.phase !== 'send';
    $('#send-ex-next').hidden = X.phase !== 'result';
    $('#send-ex-next').textContent = t(n >= SEND_TASKS ? 'send.ex.summaryBtn' : 'send.ex.next');
    $('#send-ex-again').hidden = X.phase !== 'summary';
    if (X.phase === 'send') {
      $('#send-ex-progress').textContent = t('send.ex.progress', { i: n + 1, n: SEND_TASKS });
      $('#send-ex-target').textContent = X.target;
      $('#send-ex-hint').textContent = t('send.ex.wait');
      res.hidden = true;
      res.textContent = '';
    } else if (X.phase === 'result') {
      const ev = X.results.at(-1);
      $('#send-ex-progress').textContent = t('send.ex.progressDone', { i: n, n: SEND_TASKS });
      $('#send-ex-hint').textContent = t('send.ex.review');
      res.hidden = false;
      const evBox = document.createElement('div');
      renderEval(evBox, ev.metrics, ev);
      res.textContent = '';
      res.append(reviewRows(ev), evBox);
    } else {
      const sum = sessionSummary(X.results);
      $('#send-ex-progress').textContent = t('send.ex.summary', { n: sum.tasks });
      $('#send-ex-target').textContent = '';
      $('#send-ex-hint').textContent = t('send.ex.summaryHint');
      res.hidden = false;
      const evBox = document.createElement('div');
      renderEval(evBox, sum.metrics, sum);
      res.textContent = '';
      res.append(evBox);
      if (sum.conf.length) {
        const p = document.createElement('p');
        p.className = 'hint';
        p.textContent = t('send.ex.conf', {
          list: sum.conf.map((c) => `${c.want} (${c.wantCode}) → ${c.got} (${c.gotCode}) ${c.n}×`).join(', '),
        });
        res.append(p);
      }
    }
  }

  // ---------- event log (acceptance test of the converter, spec §2) ----------
  function logEvent(side, down, ts, src) {
    if (S.t0 === null) S.t0 = ts;
    const delta = S.prev === null ? null : ts - S.prev;
    S.prev = ts;
    if (down) S.presses += 1;
    S.log.unshift({ at: ts - S.t0, side, down, src, delta });
    if (S.log.length > LOG_MAX) S.log.length = LOG_MAX;
    renderLog();
  }

  // ---------- rendering ----------
  function renderOut() {
    // bug: a hand dash is stored at its release, automatic dots when scheduled → keep the decoder input in time order
    const tones = [...S.elements].sort((x, y) => x.start - y.start);
    const r = decodeTones(tones, keyer.wpm, MORSE);
    $('#key-text').textContent = r.text || '–';
    $('#key-codes').textContent = r.codes.slice(-12).join(' ');
    const hand = S.elements.filter((e) => !e.el).length;
    $('#key-est').textContent = hand >= EST_MIN_TONES
      ? t('key.estimate', { wpm: Math.round(r.wpm), ratio: f1(r.dash / r.dot) }) : '';
    // D3 (0.11.4): form of free sending over the last EVAL_WINDOW tones
    const box = $('#key-eval');
    if (X.on || tones.length < EVAL_MIN_TONES) { box.textContent = ''; box.hidden = true; return; }
    const win = tones.slice(-EVAL_WINDOW);
    const m = sendMetrics(win, decodeTones(win, keyer.wpm, MORSE));
    box.hidden = false;
    renderEval(box, m);
    const h = document.createElement('p');
    h.className = 'hint';
    h.textContent = t('send.free', { n: win.length });
    box.prepend(h);
  }

  function renderLog() {
    const tb = $('#key-log');
    tb.textContent = '';
    for (const e of S.log) {
      const tr = document.createElement('tr');
      const cells = [e.at.toFixed(1), `${e.src} ${t(`key.side.${e.side}`)}`, e.down ? '↓' : '↑',
        e.delta === null ? '' : `+${e.delta.toFixed(1)}`];
      for (const c of cells) { const td = document.createElement('td'); td.textContent = c; tr.append(td); }
      tb.append(tr);
    }
    $('#key-log-count').textContent = t('key.logCount', { n: S.presses });
  }

  function renderMap() {
    $('#key-map').textContent = S.learn
      ? t(S.learn === 'dot' ? 'key.learnDot' : 'key.learnDash')
      : t('key.map', { dot: cfg.dot, dash: cfg.dash });
  }

  function renderControls() {
    const sel = $('#key-type');
    if (!sel.options.length) {
      for (const k of UI_TYPES) {
        const o = document.createElement('option');
        o.value = k;
        sel.append(o);
      }
    }
    for (const o of sel.options) o.textContent = t(`key.type.${o.value}`);
    sel.value = cfg.type;
    $('#key-wpm-val').textContent = `${cfg.wpm} WPM`;
    $('#key-swap').checked = cfg.swap;
    $('#key-sidetone').checked = cfg.sidetone;
    const straight = cfg.type === 'straight';
    $('#key-dash').hidden = straight;
    $('#key-dot').textContent = t(straight ? 'key.straightBtn' : 'key.dot');
    $('#key-type-hint').textContent = t(`key.typeHint.${cfg.type}`);
    renderMap();
  }

  function apply() {
    save(cfg);
    releaseAll();
    keyer = new Keyer(cfg);
    renderControls();
    renderOut();
  }

  // ---------- controls ----------
  $('#key-type').addEventListener('change', (e) => { cfg.type = e.target.value; apply(); });
  $('#send-ex-kind').addEventListener('change', (e) => { cfg.exKind = e.target.value; save(cfg); });
  $('#send-ex-start').addEventListener('click', () => { if (!player.ready) ensureAudio(); exStart(); });
  $('#send-ex-again').addEventListener('click', exStart);
  $('#send-ex-done').addEventListener('click', exFinish);
  $('#send-ex-next').addEventListener('click', exNext);
  $('#send-ex-stop').addEventListener('click', exStop);
  for (const [id, d] of [['#key-wpm-minus', -1], ['#key-wpm-plus', 1]]) {
    $(id).addEventListener('click', () => {
      cfg.wpm = Math.min(KEYER_WPM_MAX, Math.max(KEYER_WPM_MIN, cfg.wpm + d));
      apply();
    });
  }
  $('#key-swap').addEventListener('change', (e) => { cfg.swap = e.target.checked; apply(); });
  $('#key-sidetone').addEventListener('change', (e) => { cfg.sidetone = e.target.checked; apply(); });
  $('#key-learn').addEventListener('click', () => { releaseAll(); S.learn = 'dot'; renderMap(); });
  $('#key-map-reset').addEventListener('click', () => {
    S.learn = null; cfg.dot = DEFAULTS.dot; cfg.dash = DEFAULTS.dash; apply();
  });
  // 0.12.3 (validation #31): the raw tones on request into the debug record (accounts with tracing only)
  $('#key-rec-send').addEventListener('click', async () => {
    const st = $('#key-rec-status');
    if (!S.elements.length && !S.exRec.length) { st.textContent = t('key.rec.empty'); return; }
    const tones = [...S.elements].sort((x, y) => x.start - y.start);
    const t0 = tones.length ? tones[0].start : 0;
    traceBegin(TRACE_KEY, null);
    traceEnd(null, {
      type: cfg.type, wpm: cfg.wpm, meant: $('#key-rec-text').value.trim().slice(0, 200),
      text: decodeTones(tones, keyer.wpm, MORSE).text, ua: navigator.userAgent.slice(0, 200),
      tones: tones.map((tn) => rnd({ ...tn, start: tn.start - t0, end: tn.end - t0 })), ex: S.exRec,
    });
    st.textContent = t('key.rec.sending');
    try { await flushTrace(); st.textContent = t('key.rec.sent'); } catch (e) { st.textContent = t('key.rec.fail'); }
  });
  $('#key-clear').addEventListener('click', () => {
    S.elements = []; S.log = []; S.t0 = null; S.prev = null; S.presses = 0;
    renderOut(); renderLog();
  });

  // on-screen paddles: pointer capture keeps the press even when the finger slides off; two fingers = squeeze
  for (const [id, side] of [['#key-dot', 'dot'], ['#key-dash', 'dash']]) {
    const b = $(id);
    const up = (e) => {
      if (!S.held[side]) return;
      S.held[side] = false;
      b.classList.remove('down');
      if (S.sent[side]) { S.sent[side] = false; input(side, false, e.timeStamp, 'touch'); }
    };
    b.addEventListener('pointerdown', async (e) => {
      e.preventDefault();
      try { b.setPointerCapture(e.pointerId); } catch (err) { /* not supported */ }
      if (S.held[side]) return;
      S.held[side] = true;
      b.classList.add('down');
      const ts = e.timeStamp;
      if (!player.ready) await ensureAudio();
      if (!S.held[side] || S.sent[side]) return; // released while the first touch unlocked the audio
      S.sent[side] = true;
      input(side, true, ts, 'touch');
    });
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('lostpointercapture', up);
    b.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  window.addEventListener('blur', () => { if (S.open) releaseAll(); });

  return {
    render() {
      S.open = true;
      // 0.11.1 (#28): opening the page is a tap too → unlock the audio now, the keep-alive tone (main.js) then keeps
      // the phone output running, so the first press is not cut
      if (!player.ready) ensureAudio();
      renderControls();
      renderOut();
      renderLog();
      renderEx();
      $('#key-rec').hidden = !traceOn();
    },
    stop() {
      S.open = false;
      S.learn = null;
      releaseAll();
      player.sidetoneOff();
      // leaving the page (or hiding it) interrupts a task in progress: it starts again with no tones
      clearTimeout(X.timer);
      X.timer = null;
      X.tones = [];
    },
    /** keydown / keyup on the key page; true = handled (the caller prevents the default – Ctrl shortcuts). */
    onKey(e, down) {
      if (S.learn) {
        if (!down || e.repeat) return true;
        if (e.code === 'Escape') { S.learn = null; renderMap(); return true; }
        cfg[S.learn] = e.code;
        if (S.learn === 'dot') { S.learn = 'dash'; renderMap(); return true; }
        S.learn = null;
        if (cfg.dash === cfg.dot) cfg.dash = DEFAULTS.dash === cfg.dot ? DEFAULTS.dot : DEFAULTS.dash;
        apply();
        return true;
      }
      const side = e.code === cfg.dot ? 'dot' : (e.code === cfg.dash ? 'dash' : null);
      if (!side && X.on && (e.code === 'Enter' || e.code === 'NumpadEnter')) {
        if (down && !e.repeat) { if (X.phase === 'send') exFinish(); else if (X.phase === 'result') exNext(); }
        return true;
      }
      if (!side) return false;
      // autorepeat of the OS (spec K-06, A-02) by own state, not e.repeat: on Windows the second Ctrl held together
      // with the first one arrives marked as a repeat (one virtual key Ctrl) and the squeeze was lost (validation #33)
      if (down) {
        if (S.keys.has(e.code)) return true;
        S.keys.add(e.code);
      } else {
        if (!S.keys.has(e.code)) return true;
        S.keys.delete(e.code);
        // releasing both Ctrl keys may report only one keyup → nothing held with Ctrl as a modifier = release all
        if (!e.ctrlKey) {
          for (const code of [...S.keys]) {
            if (code.startsWith('Control')) {
              S.keys.delete(code);
              input(code === cfg.dot ? 'dot' : 'dash', false, e.timeStamp, 'kbd');
            }
          }
        }
      }
      if (down && !player.ready) { ensureAudio(); }
      input(side, down, e.timeStamp, 'kbd');
      return true;
    },
  };
}
