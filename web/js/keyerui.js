// SPDX-License-Identifier: EUPL-1.2
// VK (0.11.0, docs/spec-klic.md A-01–A-03, A-10–A-12): Settings → Telegraph key.
// 0.15.3 (Martin 2026-11-12): only the HW keyer CwKey (USB) – the app keyer types (iambic, single lever, bug,
// straight key), the on-screen paddles and the keyboard paddles are gone; without a HW key nothing can be sent.
// Event log with times for the acceptance test of the key. The key settings belong to the device (localStorage).
import { t, fmtNum } from './i18n.js';
import { MORSE } from './charset.js';
import { decodeTones, gapDiagnostics, loadWordHint, saveWordHint } from './decoder.js';
import { KeyLearn } from './keylearn.js';
import { KeyInput, HW_TYPE, hwState } from './keyinput.js';
import { logSummary, KEYLOG_MAX } from './keylog.js';
import { traceOn, traceBegin, traceEnd, flushTrace } from './trace.js';
import {
  sendMetrics, focusOf, evaluateSending, sessionSummary, sendTask, EVAL_WINDOW, SEND_KINDS, SEND_TASKS,
  SEND_END_MS, SEND_END_UNITS,
} from './sendeval.js';

const STORE = 'morse-key';
// 0.14.0 (spec A-04, docs/hw/klic-rozhrani.md): a HW keyer with USB – the key forms the elements and plays the
// sidetone; the app reads one stream key (key down = tone on), decodes with machine timing, does not run its keyer.
// Mode C adds the paddle states as Left / Right Ctrl – only logged (Z-24 later), they do not key anything.
const PADDLES_MAX = 800;   // paddle events of mode C kept for the debug record
const DEFAULTS = { type: HW_TYPE, exKind: 'char', stream: 'F13', hwSidetone: false };
export const HW_WPM = 18;  // the decoder's fallback speed before the first dots of the key are measured
const validCode = (c) => typeof c === 'string' && /^[A-Za-z0-9]{1,32}$/.test(c);
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
    const st = JSON.parse(localStorage.getItem(STORE)) || {};
    // 0.15.3: a stored app keyer type (iambicB …) becomes the HW keyer; its old fields are dropped
    const c = { ...DEFAULTS, exKind: st.exKind, stream: st.stream, hwSidetone: st.hwSidetone === true, type: HW_TYPE };
    if (!SEND_KINDS.includes(c.exKind)) c.exKind = DEFAULTS.exKind;
    if (!validCode(c.stream)) c.stream = DEFAULTS.stream;
    return c;
  } catch (e) { return { ...DEFAULTS }; }
}
function save(cfg) { try { localStorage.setItem(STORE, JSON.stringify(cfg)); } catch (e) { /* private mode */ } }
/** 0.13.2: the CW room uses the same key settings (stream key, sidetone) as the key page. */
export const loadKeyConfig = load;

export function initKeyerUi({ player, ensureAudio, getChars, onHwSeen = () => {} }) {
  const cfg = load();
  const S = {
    elements: [], learn: null, learnTimer: null, log: [], t0: null, prev: null, presses: 0, manual: null, open: false,
    input: new KeyInput(cfg),   // 0.14.1: keyboard input (autorepeat filter, HW stream) – keyinput.js
    exRec: [],         // 0.12.3: the last exercise tasks with their tones (for the recording)
    events: [],        // 0.14.3: key events {at, code, down} for the summary (KEYLOG_MAX)
    paddles: [],       // 0.14.0: paddle states of a HW key in mode C {side, down, at} (debug record)
    hwDot: null,       // 0.14.0: the last measured dot of the HW stream (ms) – the hint of the decoder
    lastDec: null,     // 0.15.4: the last decoding of the transcript (diagnostics)
  };
  const sidetoneOn = () => cfg.hwSidetone;

  /** Decoding of the tones of the page: the HW stream with machine timing (dec.tones then carry the elements). */
  function decode(tones) {
    if (tones.length <= 1 || S.wordHint === undefined) S.wordHint = loadWordHint(); // 0.16.3: a new record starts with the hand's threshold
    const dec = decodeTones(tones, HW_WPM, MORSE, { machine: true, dot: S.hwDot, word: S.wordHint });
    if (tones.length) { S.hwDot = dec.dot; saveWordHint(dec); }
    return dec;
  }

  // ---------- keying ----------
  // D3 (0.11.3): tones in one time line in ms = the event clock (event.timeStamp); the output latency of the sound
  // does not enter decoding.
  function addElement(el, start, end) {
    S.elements.push({ el, start, end });
    if (X.phase === 'send') exTone({ el, start, end });
    if (S.elements.length > ELEMENTS_MAX) S.elements.splice(0, S.elements.length - ELEMENTS_MAX);
    renderOut();
  }

  function manualKey(down, ts) {
    if (down) {
      if (S.manual !== null) return;
      S.manual = ts;
      if (sidetoneOn() && player.ready) player.sidetoneKey(true);
    } else if (S.manual !== null) {
      if (sidetoneOn() && player.ready) player.sidetoneKey(false);
      addElement(null, S.manual, Math.max(S.manual, ts));
      S.manual = null;
    }
  }

  /** 0.14.0: one change of the HW stream (tone on / off) – no app keyer, no sound needed (the key plays it). */
  function hwInput(down, ts, code) {
    logEvent('stream', down, ts, 'hw', code);
    if (down) {
      onHwSeen(); // 0.15.0: the key is connected (firmware offer / the key runs again after an update)
      if (!hwState.seen) { hwState.seen = true; renderNoKey(); }
    }
    if (down) { clearTimeout(X.timer); X.timer = null; }
    manualKey(down, ts);
  }

  function releaseAll() {
    if (S.manual !== null) manualKey(false, performance.now());
    S.input.releaseAll();
  }

  /** 0.15.3: no stream key seen in this app session → how to connect the key (sending needs the HW key). */
  function renderNoKey() {
    $('#key-nokey').hidden = hwState.seen || !!S.learn;
  }

  // ---------- sending exercise (D3 step 3, 0.12.0): task → sending → evaluation; a series of SEND_TASKS ----------
  // Nothing goes to the server (that comes with D4, mode `vysilani`). Characters of the receive level.
  const X = { on: false, phase: null, target: '', tones: [], results: [], timer: null };

  function exTone(tone) {
    X.tones.push(tone);
    clearTimeout(X.timer);
    const dec = decode([...X.tones].sort((a, b) => a.start - b.start));
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
    const dec = decode(tones);
    const ev = evaluateSending(X.target, dec.tones, dec, MORSE);
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
  function logEvent(side, down, ts, src, code = '') {
    if (S.t0 === null) S.t0 = ts;
    const delta = S.prev === null ? null : ts - S.prev;
    S.prev = ts;
    if (down) S.presses += 1;
    S.log.unshift({ at: ts - S.t0, side, down, src, delta, code });
    // 0.14.3: the whole record for the summary of the acceptance test (H-42 (1)); touch = the side as the key
    S.events.push({ at: ts, code: code || `${src}:${side}`, down });
    if (S.events.length > KEYLOG_MAX) S.events.shift();
    if (S.log.length > LOG_MAX) S.log.length = LOG_MAX;
    renderLog();
  }

  // ---------- rendering ----------
  function renderOut() {
    // bug: a hand dash is stored at its release, automatic dots when scheduled → keep the decoder input in time order
    const tones = [...S.elements].sort((x, y) => x.start - y.start);
    const r = decode(tones);
    S.lastDec = r;
    if ($('#key-diag-box').open) renderDiag();
    $('#key-text').textContent = r.text || '–';
    $('#key-codes').textContent = r.codes.slice(-12).join(' ');
    $('#key-est').textContent = tones.length >= EST_MIN_TONES ? t('key.estimateHw', { wpm: Math.round(r.wpm) }) : '';
    // D3 (0.11.4): form of free sending over the last EVAL_WINDOW tones
    const box = $('#key-eval');
    if (X.on || tones.length < EVAL_MIN_TONES) { box.textContent = ''; box.hidden = true; return; }
    const win = tones.slice(-EVAL_WINDOW);
    const dw = decode(win);
    const m = sendMetrics(dw.tones, dw);
    box.hidden = false;
    renderEval(box, m);
    const h = document.createElement('p');
    h.className = 'hint';
    h.textContent = t('send.free', { n: win.length });
    box.prepend(h);
  }

  // ---------- 0.15.4: how the decoder reads (the last words gap by gap) ----------
  function diagLines() {
    const d = S.lastDec && gapDiagnostics(S.lastDec, MORSE);
    if (!d || !d.rows.length) return null;
    const n = (x) => fmtNum(x, 1);
    const head = t('key.diag.head', { dot: Math.round(d.dot), wpm: Math.round(d.wpm), split: n(d.split), word: n(d.word) });
    const rows = d.rows.map((r) => {
      const ch = r.ch === '' ? t('key.diag.fix') : (r.ch ?? t('key.diag.unknown'));
      let line = r.before === null ? t('key.diag.rowFirst', { ch, code: r.code })
        : t('key.diag.row', { ch, code: r.code, before: n(r.before), kind: t(`key.diag.kind${r.kind}`) });
      if (r.close) line = `⚠ ${line}`;
      if (r.inMax !== null) line += ` · ${r.inClose ? '⚠ ' : ''}${t('key.diag.inside', { x: n(r.inMax) })}`;
      return { line, close: r.close || r.inClose };
    });
    return { head, rows };
  }

  function renderDiag() {
    const d = diagLines();
    const ol = $('#key-diag');
    ol.textContent = '';
    $('#key-diag-head').textContent = d ? d.head : t('key.diag.empty');
    if (!d) return;
    for (const r of d.rows) {
      const li = document.createElement('li');
      li.textContent = r.line;
      if (r.close) li.className = 'close';
      ol.append(li);
    }
  }

  function renderLog() {
    const tb = $('#key-log');
    tb.textContent = '';
    for (const e of S.log) {
      const tr = document.createElement('tr');
      const cells = [e.at.toFixed(1), `${e.src} ${t(`key.side.${e.side}`)}`, e.code, e.down ? '↓' : '↑',
        e.delta === null ? '' : `+${e.delta.toFixed(1)}`];
      for (const c of cells) { const td = document.createElement('td'); td.textContent = c; tr.append(td); }
      tb.append(tr);
    }
    $('#key-log-count').textContent = t('key.logCount', { n: S.presses });
    // the summary only while the log is open (it runs over up to KEYLOG_MAX events on every key change)
    if ($('#key-log').closest('details').open) $('#key-log-sum').textContent = sumLines(logSummary(S.events)).join('\n');
  }

  // ---------- summary of the event log for the HW project (0.14.3, H-42 (1)) ----------
  function sumLines(sum) {
    const ms = (x) => f1(x);
    const grp = (key, g) => `  ${t(key, { n: g.n, med: ms(g.med), min: ms(g.min), max: ms(g.max) })}`;
    const out = [t('key.logSum.head', { n: sum.events, s: f1(sum.ms / 1000) })];
    for (const k of sum.keys) {
      out.push(t('key.logSum.key', { code: k.code, n: k.n }));
      if (k.dot) out.push(grp('key.logSum.dot', k.dot), grp('key.logSum.dash', k.dash));
      else if (k.all) out.push(grp('key.logSum.all', k.all));
      if (k.wpm) out.push(`  ${t('key.logSum.wpm', { wpm: f1(k.wpm) })}`);
    }
    out.push(t('key.logSum.err', { dup: sum.dup, orphan: sum.orphan, open: sum.open }));
    return out;
  }

  function logText() {
    const t0 = S.events.length ? S.events[0].at : 0;
    let prev = null;
    const rows = S.events.map((e) => {
      const r = `${(e.at - t0).toFixed(1)}\t${e.code}\t${e.down ? 'down' : 'up'}\t${prev === null ? '' : `+${(e.at - prev).toFixed(1)}`}`;
      prev = e.at;
      return r;
    });
    return [`${t('app.title')} ${new Date().toISOString()}`, `UA: ${navigator.userAgent}`,
      `${t('key.type')}: ${cfg.type} (${cfg.stream})`, ...sumLines(logSummary(S.events)), '',
      'ms\tcode\tevent\tdelta', ...rows].join('\n');
  }

  // ---------- learning the keys with confirmation (0.13.11, keylearn.js) ----------
  function learnStart() {
    releaseAll();
    S.learn = new KeyLearn(['stream']);
    renderMap();
  }

  function learnEnd() {
    clearTimeout(S.learnTimer);
    S.learnTimer = null;
    const kl = S.learn;
    S.learn = null;
    if (kl && kl.phase === 'done') {
      hwState.seen = true;   // a key gesture of the stream arrived (the key is connected)
      Object.assign(cfg, kl.result);
      apply();
    } else renderMap();
  }

  /** After every learning event: finished / cancelled → end, a gesture running → wake up when its silence is over. */
  function learnUpdate() {
    const kl = S.learn;
    if (!kl) return;
    if (!kl.active) { learnEnd(); return; }
    clearTimeout(S.learnTimer);
    S.learnTimer = null;
    const due = kl.dueAt();
    if (due !== null) {
      S.learnTimer = setTimeout(() => { S.learnTimer = null; kl.tick(performance.now()); learnUpdate(); },
        Math.max(0, due - performance.now()) + 5);
    }
    renderMap();
  }

  function renderMap() {
    const kl = S.learn;
    const box = $('#key-learn-box');
    box.hidden = !kl;
    if (!kl) {
      $('#key-map').textContent = t('key.mapHw', { code: cfg.stream });
      renderNoKey();
      return;
    }
    renderNoKey();
    $('#key-map').textContent = t('key.learnStream');
    const confirm = kl.phase === 'confirm';
    let msg = '';
    if (kl.phase === 'gesture') msg = t('key.learnHeld');
    else if (confirm) msg = t('key.learnGot.stream', { code: kl.code });   // one step only – no clash of two keys
    $('#key-learn-msg').textContent = msg;
    $('#key-learn-ok').hidden = !confirm || !!kl.error;
    $('#key-learn-again').hidden = !confirm;
  }

  function renderControls() {
    $('#key-sidetone').checked = sidetoneOn();
    renderMap();
  }

  function apply() {
    save(cfg);
    releaseAll();
    renderControls();
    renderOut();
  }

  // ---------- controls ----------
  $('#send-ex-kind').addEventListener('change', (e) => { cfg.exKind = e.target.value; save(cfg); });
  $('#send-ex-start').addEventListener('click', () => { if (!player.ready) ensureAudio(); exStart(); });
  $('#send-ex-again').addEventListener('click', exStart);
  $('#send-ex-done').addEventListener('click', exFinish);
  $('#send-ex-next').addEventListener('click', exNext);
  $('#send-ex-stop').addEventListener('click', exStop);
  $('#key-sidetone').addEventListener('change', (e) => { cfg.hwSidetone = e.target.checked; apply(); });
  $('#key-learn').addEventListener('click', learnStart);
  $('#key-learn-ok').addEventListener('click', () => { if (S.learn) { S.learn.confirm(); learnUpdate(); } });
  $('#key-learn-again').addEventListener('click', () => { if (S.learn) { S.learn.retry(); learnUpdate(); } });
  $('#key-learn-cancel').addEventListener('click', () => { if (S.learn) { S.learn.cancel(); learnUpdate(); } });
  $('#key-map-reset').addEventListener('click', () => {
    if (S.learn) S.learn.cancel();
    learnEnd();
    cfg.stream = DEFAULTS.stream;
    apply();
  });
  // 0.12.3 (validation #31): the raw tones on request into the debug record (accounts with tracing only)
  $('#key-rec-send').addEventListener('click', async () => {
    const st = $('#key-rec-status');
    if (!S.elements.length && !S.exRec.length) { st.textContent = t('key.rec.empty'); return; }
    const tones = [...S.elements].sort((x, y) => x.start - y.start);
    const t0 = tones.length ? tones[0].start : 0;
    traceBegin(TRACE_KEY, null);
    traceEnd(null, {
      type: cfg.type, wpm: S.hwDot ? Math.round(1200 / S.hwDot) : HW_WPM, meant: $('#key-rec-text').value.trim().slice(0, 200),
      text: decode(tones).text, ua: navigator.userAgent.slice(0, 200),
      tones: tones.map((tn) => rnd({ ...tn, start: tn.start - t0, end: tn.end - t0 })), ex: S.exRec,
      stream: cfg.stream, paddles: S.paddles.map((p) => ({ ...p, at: Math.round((p.at - t0) * 10) / 10 })),
    });
    st.textContent = t('key.rec.sending');
    try { await flushTrace(); st.textContent = t('key.rec.sent'); } catch (e) { st.textContent = t('key.rec.fail'); }
  });
  function clearOut() {
    S.elements = []; S.log = []; S.t0 = null; S.prev = null; S.presses = 0; S.paddles = []; S.events = [];
    renderOut(); renderLog();
  }
  $('#key-clear').addEventListener('click', clearOut);
  $('#key-diag-box').addEventListener('toggle', renderDiag);
  $('#key-diag-copy').addEventListener('click', async () => {
    const d = diagLines();
    const st = $('#key-diag-status');
    if (!d) { st.textContent = t('key.diag.empty'); return; }
    try {
      await navigator.clipboard.writeText([d.head, ...d.rows.map((r) => r.line)].join('\n'));
      st.textContent = t('key.logCopied');
    } catch (e) {
      st.textContent = t('key.diag.copyFail');
    }
  });
  $('#key-log').closest('details').addEventListener('toggle', renderLog);
  $('#key-log-copy').addEventListener('click', async () => {
    const st = $('#key-log-copy-status');
    const text = logText();
    const area = $('#key-log-text');
    try {
      await navigator.clipboard.writeText(text);
      area.hidden = true;
      st.textContent = t('key.logCopied');
    } catch (e) {
      // no clipboard (permission, old browser): show the text to be selected by hand
      area.value = text;
      area.hidden = false;
      area.select();
      st.textContent = t('key.logCopyFail');
    }
  });
  const lost = () => {
    if (!S.open) return;
    releaseAll();
    if (S.learn) { S.learn.releaseAll(performance.now()); learnUpdate(); }
  };
  window.addEventListener('blur', lost);
  document.addEventListener('visibilitychange', () => { if (document.hidden) lost(); });

  return {
    render() {
      S.open = true;
      // 0.14.2: the CW Chat may have changed the shared key settings meanwhile
      Object.assign(cfg, load());
      // 0.11.1 (#28): opening the page is a tap too → unlock the audio now, the keep-alive tone (main.js) then keeps
      // the phone output running, so the first press is not cut
      if (!player.ready) ensureAudio();
      renderControls();
      renderOut();
      renderLog();
      renderEx();
      renderNoKey();
      $('#key-rec').hidden = !traceOn();
    },
    stop() {
      S.open = false;
      if (S.learn) S.learn.cancel();
      learnEnd();
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
        // 0.13.11: one gesture per step, then a confirmation (a USB key sends several keys for one paddle press)
        S.learn.key(e.code, down, e.timeStamp, e.repeat);
        learnUpdate();
        return true;
      }
      // 0.14.1: shared keyboard input (keyinput.js): own autorepeat filter, HW stream and the paddle states (mode C)
      const acts = S.input.key(e.code, down);
      if (acts === null) {
        if (X.on && (e.code === 'Enter' || e.code === 'NumpadEnter')) {
          if (down && !e.repeat) { if (X.phase === 'send') exFinish(); else if (X.phase === 'result') exNext(); }
          return true;
        }
        return false;
      }
      for (const a of acts) {
        if (a.kind === 'stream') hwInput(a.down, e.timeStamp, e.code);
        else if (a.kind === 'paddle') {
          logEvent(a.side, a.down, e.timeStamp, 'hw', e.code);
          S.paddles.push({ side: a.side, down: a.down, at: e.timeStamp });
          if (S.paddles.length > PADDLES_MAX) S.paddles.shift();
        }
      }
      return true;
    },
  };
}
