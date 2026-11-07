// SPDX-License-Identifier: EUPL-1.2
// U6 head copy lesson (0.10.14): one over of a QSO is played (clean or on the band), nothing is typed while listening;
// then HEAD_Q questions about its content answered by writing the value, a check with the whole text, next QSO.
// Lesson time = listening + answering (pauses excluded). Logic in head.js (tested in Python).
import { t } from './i18n.js';
import { MODE_HEAD } from './storage.js';
import { makeHeadQso, scoreHead, headSummary, HEAD_Q } from './head.js';
import { BandSound, bandParams } from './band.js';
import { DAY_WARN_MIN, SESSION_END_MIN } from './coach.js';
import { traceBegin, traceEnd, tr, traceAudio, audioMeta } from './trace.js';

const $ = (s) => document.querySelector(s);
const fmtTime = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const pct = (x) => `${Math.round(x * 100)} %`;
const AFTER_MS = 500; // the questions appear this long after the last tone (the band fades out)

/** deps: {player, show, settings, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind, currentLoad, fallbackChars(), level()} */
export function initHead(deps) {
  const { player, settings } = deps;
  const band = new BandSound(player);
  const H = { running: false };
  let R = null; // current transmission

  function plan() {
    const hd = deps.coachInfo.data?.head || {};
    const chars = (deps.coachInfo.data?.copy?.chars || []).filter((c) => deps.fallbackChars().includes(c));
    return { step: hd.step || 1, wpm: hd.wpm || 25, band: hd.band || null, name: hd.name || '', chars: chars.length ? chars : deps.fallbackChars() };
  }

  async function start() {
    if (!(await deps.ensureAudio())) { alert(t('audio.failed')); return; }
    await deps.keepAwake(true);
    const p = plan();
    Object.assign(H, { running: true, paused: false, plan: p, rounds: [], activeMs: 0, pauses: [], pauseAt: 0,
      lessonMs: settings.lessonMin * 60000, tick: null });
    player.settings = { ...settings, wpm: p.wpm, fwpm: p.wpm };
    traceAudio(player.ctx);
    traceBegin(MODE_HEAD, { level: deps.level(), plan: { step: p.step, wpm: p.wpm, band: p.band }, device: deps.deviceKind(),
      set: { freq: settings.freq, vol: settings.volume, min: settings.lessonMin }, audio: audioMeta(player),
      ua: navigator.userAgent.slice(0, 200) });
    $('#hd-phase').textContent = t('head.phase', { step: p.step, name: p.name });
    $('#hd-acc').textContent = '–';
    $('#hd-pause-overlay').hidden = true;
    deps.show('head');
    H.tick = setInterval(updateBar, 250);
    await new Promise((r) => setTimeout(r, 800));
    if (H.running && !H.paused) startRound();
  }

  const elapsed = () => H.activeMs + (R && R.t0 && !R.checked ? performance.now() - R.t0 : 0);

  function updateBar() {
    const ms = elapsed();
    $('#hd-time').textContent = fmtTime(ms);
    $('#hd-progress').style.width = `${Math.min(100, (ms / H.lessonMs) * 100)}%`;
    if (H.paused) $('#hd-pause-time').textContent = fmtTime(Date.now() - H.pauseAt);
  }

  // ---------- one transmission ----------
  function startRound() {
    const qso = makeHeadQso(H.plan.chars, Math.random);
    if (!qso) { finish(); return; }
    R = { qso, t0: performance.now(), listening: true, checked: false, token: {} };
    $('#hd-form').hidden = true;
    $('#hd-check').hidden = true;
    $('#hd-next').hidden = true;
    $('#hd-reveal').hidden = true;
    $('#hd-status').textContent = t('head.listen');
    const st = H.plan.band
      ? band.playStream(qso.items, bandParams(H.plan.band, { wpm: H.plan.wpm, freq: settings.freq || 600 }), { gapX: 1, fwpm: H.plan.wpm })
      : player.playStream(qso.items, { gapX: 1 });
    tr('round', { text: qso.text, q: qso.questions, ...(H.plan.band ? { band: H.plan.band, freq: st.freq } : {}) });
    const token = R.token;
    st.done.then(() => setTimeout(() => { if (R && R.token === token && H.running && !H.paused) ask(); }, AFTER_MS));
  }

  function ask() {
    R.listening = false;
    $('#hd-status').textContent = t('head.answer');
    const form = $('#hd-form');
    form.textContent = '';
    R.qso.questions.forEach((key, i) => {
      const lab = document.createElement('label');
      lab.className = 'hd-q';
      const span = document.createElement('span');
      span.textContent = t(`head.q.${key}`);
      const inp = document.createElement('input');
      Object.assign(inp, { type: 'text', name: key, autocomplete: 'off', spellcheck: false, maxLength: 20 });
      inp.setAttribute('autocapitalize', 'characters');
      inp.setAttribute('autocorrect', 'off');
      inp.dataset.key = key;
      if (i === HEAD_Q - 1) inp.enterKeyHint = 'done';
      lab.append(span, inp);
      form.append(lab);
    });
    form.hidden = false;
    $('#hd-check').hidden = false;
    form.querySelector('input')?.focus();
  }

  function check() {
    if (!R || R.listening || R.checked) return;
    const written = {};
    for (const inp of $('#hd-form').querySelectorAll('input')) written[inp.dataset.key] = inp.value;
    const sc = scoreHead(R.qso, written);
    R.checked = true;
    H.activeMs += performance.now() - R.t0;
    H.rounds.push({ sc });
    tr('roundEnd', { ok: sc.ok, n: sc.n, res: sc.res.map((x) => [x.key, x.ok ? 1 : 0]) });
    // feedback: every field with the right value, then the whole transmission
    for (const lab of $('#hd-form').querySelectorAll('.hd-q')) {
      const inp = lab.querySelector('input');
      const x = sc.res.find((r) => r.key === inp.dataset.key);
      inp.disabled = true;
      lab.classList.add(x.ok ? 'ok' : 'bad');
      if (!x.ok) {
        const c = document.createElement('span');
        c.className = 'hd-right';
        c.textContent = t('head.right', { v: x.expected });
        lab.append(c);
      }
    }
    const rv = $('#hd-reveal');
    rv.textContent = R.qso.text;
    rv.hidden = false;
    const sum = headSummary(H.rounds);
    $('#hd-acc').textContent = pct(sum.acc);
    $('#hd-status').textContent = t('head.roundResult', { ok: sc.ok, n: sc.n });
    $('#hd-check').hidden = true;
    const nb = $('#hd-next');
    nb.textContent = H.activeMs >= H.lessonMs ? t('copy.toResult') : t('head.next');
    nb.hidden = false;
    nb.focus();
  }

  function next() {
    if (!R?.checked) return;
    if (H.activeMs >= H.lessonMs) { finish(); return; }
    startRound();
  }

  // ---------- pause ----------
  function pause() {
    if (!H.running || H.paused) return;
    player.stop();
    band.stop();
    H.paused = true;
    H.pauseAt = Date.now();
    if (R && !R.checked) { // an interrupted transmission is not scored – a new one after the pause
      H.activeMs += performance.now() - R.t0;
      R.token = null;
      R = null;
    }
    tr('pause');
    $('#hd-pause-overlay').hidden = false;
  }

  function resume() {
    if (!H.paused) return;
    const s = Math.round((Date.now() - H.pauseAt) / 1000);
    H.pauses.push([Math.round(H.activeMs / 1000), s]);
    tr('resume', [s]);
    H.paused = false;
    $('#hd-pause-overlay').hidden = true;
    if (!R) startRound();
  }

  function finish(aborted = false) {
    if (!H.running) return;
    H.running = false;
    clearInterval(H.tick);
    player.stop();
    band.stop();
    R = null;
    deps.keepAwake(false);
    $('#hd-pause-overlay').hidden = true;
    if (!H.rounds.length) { traceEnd(null, { empty: true }); if (!aborted) deps.show('copyhome'); return; }
    const s = headSummary(H.rounds);
    const p = H.plan;
    const saved = deps.addLesson({
      at: new Date().toISOString(), device: deps.deviceKind(), mode: MODE_HEAD, level: deps.level(),
      durS: Math.round(H.activeMs / 1000), trials: s.q, correct: s.ok, acc: s.acc ?? 0, ttr: null, wpm: p.wpm, fwpm: p.wpm,
      detail: {
        head: { step: p.step, wpm: p.wpm, ...(p.band ? { band: p.band } : {}), q: s.q, ok: s.ok, rounds: s.rounds, fields: s.fields },
        ...(H.pauses.length ? { pauses: H.pauses } : {}),
        ...(aborted ? { aborted: true } : {}),
      },
    });
    traceEnd(saved.id, { q: s.q, ok: s.ok, acc: s.acc, activeS: Math.round(H.activeMs / 1000), ...(aborted ? { aborted: true } : {}) });
    if (!aborted) showResult(s);
  }

  function showResult(s) {
    $('#hr-acc').textContent = pct(s.acc);
    $('#hr-q').textContent = String(s.q);
    $('#hr-rounds').textContent = String(s.rounds);
    const hd = deps.coachInfo.data?.head;
    $('#hr-verdict').textContent = s.acc >= 0.9 ? `${t('head.verdictGood', { acc: pct(s.acc) })} ${hd?.next || ''}`
      : s.acc >= 0.75 ? t('head.verdictMid', { acc: pct(s.acc) }) : t('head.verdictLow', { acc: pct(s.acc) });
    const parts = Object.entries(s.fields).map(([k, [n, ok]]) => `${t(`head.f.${k}`)} ${ok}/${n}`);
    $('#hr-detail').textContent = `${t('head.fields', { list: parts.join(', ') })}`
      + (s.q < (hd?.minQ || 12) ? ` ${t('head.short', { n: hd?.minQ || 12 })}` : '');
    const ld = deps.currentLoad();
    const rl = $('#hr-load');
    rl.className = ld.suggestEnd || ld.dayWarn ? 'hint warn' : 'hint';
    rl.textContent = ld.dayWarn ? t('result.loadDayWarn', { min: Math.round(ld.dayMin), max: DAY_WARN_MIN })
      : ld.suggestEnd ? t('copy.loadSessionEnd', { min: Math.round(ld.sessionMin), max: SESSION_END_MIN })
        : t('result.loadSession', { min: Math.round(ld.sessionMin) });
    deps.show('headresult');
  }

  /** Keys in the 'head' view (PC): Enter = check / next, Esc = pause. Returns true when handled. */
  function onKey(e) {
    if (e.key === 'Escape') { if (H.paused) resume(); else pause(); return true; }
    if (e.key === 'Enter' && !H.paused) {
      if (R && !R.listening && !R.checked) { check(); return true; }
      if (R?.checked) { next(); return true; }
    }
    return false;
  }

  $('#hd-check').addEventListener('click', check);
  $('#hd-form').addEventListener('submit', (e) => { e.preventDefault(); check(); });
  $('#hd-next').addEventListener('click', next);
  $('#hd-pause').addEventListener('click', pause);
  $('#hd-resume').addEventListener('click', resume);
  $('#hd-finish').addEventListener('click', () => finish());

  return {
    start, onKey, pause,
    hold: () => { if (H.running && !H.paused) pause(); },
    abort: () => finish(true),
    get running() { return H.running; },
  };
}
