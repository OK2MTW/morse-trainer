// SPDX-License-Identifier: EUPL-1.2
// Copy-behind lesson (M7 U3, M8 U4): a stream of items in lines, typing without waiting, word marks delayed by
// 1 word (from step 9 by 2 words – whole-word lag), correction at the end of the line, fatigue per line, lesson result.
// Speed: a step with wpm (U4) plays the character and the gaps at that speed, otherwise the settings from M6.
// The scoring logic is in copy.js (tested in Python).
import { t, fmtNum } from './i18n.js';
import { MODE_CHAR, MODE_COPY } from './storage.js';
import { evaluate, lessonSummary, CopyFatigue, ROUND_ITEMS, ROUND_TAIL_MS } from './copy.js';
import { makeItems } from './content.js';
import { normalizeKey } from './charset.js';
import { DAY_WARN_MIN, SESSION_END_MIN } from './coach.js';
import { traceBegin, traceEnd, tr, traceAudio, audioMeta } from './trace.js';

const $ = (s) => document.querySelector(s);
const fmtTime = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const pct = (x) => `${Math.round(x * 100)} %`;
const num = (x) => fmtNum(x);
const TAIL_MAX_MS = 3 * ROUND_TAIL_MS; // typing after the end of the stream extends the line, at most up to here
const MARK_AFTER_MS = 600;            // the mark of word k at the earliest 600 ms after word k+1 has finished

/**
 * deps: {player, kbd, show, settings, progress, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind,
 *        currentLoad, fallbackChars()}
 */
export function initCopy(deps) {
  const { player, kbd, settings } = deps;
  const C = { running: false };
  let R = null; // current line

  function plan() {
    const cp = deps.coachInfo.data?.copy;
    const chars = cp?.chars?.length ? cp.chars : deps.fallbackChars();
    return {
      step: cp?.step || 1, content: cp?.content || 'groups', gapX: cp?.gapX || 3, name: cp?.name || t('copy.groups'), chars,
      wpm: cp?.wpm || null, markLag: cp?.markLag || 1,
    };
  }

  async function start() {
    if (!(await deps.ensureAudio())) { alert(t('audio.failed')); return; }
    await deps.keepAwake(true);
    Object.assign(C, {
      running: true, paused: false, plan: plan(), rounds: [], activeMs: 0, pauses: [], pauseAt: 0,
      lessonMs: settings.lessonMin * 60000, tick: null, fat: new CopyFatigue(), fatEvents: [],
    });
    // M8: a step with a speed (U4) – character and gaps at the step speed; the settings for character lessons do not change
    C.wpm = C.plan.wpm || settings.wpm;
    C.fwpm = C.plan.wpm || settings.fwpm;
    player.settings = { ...settings, wpm: C.wpm, fwpm: C.fwpm };
    traceAudio(player.ctx);
    traceBegin(MODE_COPY, {
      level: deps.progress.level, plan: C.plan, device: deps.deviceKind(), wpm: C.wpm, fwpm: C.fwpm,
      set: { freq: settings.freq, vol: settings.volume, min: settings.lessonMin }, audio: audioMeta(player),
      ua: navigator.userAgent.slice(0, 200),
    });
    kbd.setMode(MODE_COPY);
    kbd.setActive(deps.fallbackChars()); // any known character can be typed (a confusion too), content only from mastered ones
    $('#cp-phase').textContent = t('copy.phase', { step: C.plan.step, name: C.plan.name, wpm: C.wpm, fwpm: C.fwpm })
      + (C.plan.gapX > 1 ? ` · ${t('copy.phaseGap', { x: num(C.plan.gapX) })}` : '')
      + (C.plan.markLag > 1 ? ` · ${t('copy.phaseWordLag')}` : '');
    $('#cp-acc').textContent = '–';
    $('#cp-pause-overlay').hidden = true;
    $('#cp-fatigue-overlay').hidden = true;
    deps.show('copy');
    C.tick = setInterval(updateBar, 250);
    await new Promise((r) => setTimeout(r, 800));
    if (C.running && !C.paused) startRound();
  }

  function updateBar() {
    const ms = C.activeMs + (R && R.t0 && !R.done ? performance.now() - R.t0 : 0);
    $('#cp-time').textContent = fmtTime(ms);
    $('#cp-progress').style.width = `${Math.min(100, (ms / C.lessonMs) * 100)}%`;
    if (C.paused) $('#cp-pause-time').textContent = fmtTime(Date.now() - C.pauseAt);
  }

  // ---------- line ----------
  function startRound() {
    const items = makeItems(C.plan.content, C.plan.chars, ROUND_ITEMS);
    R = {
      items, typed: [], disp: [], marks: items.map(() => null), timers: [], done: false, review: false,
      startS: C.activeMs / 1000,
    };
    $('#cp-review').hidden = true;
    $('#cp-next').hidden = true;
    $('#cp-typed').hidden = false;
    $('#cp-status').textContent = t('copy.listen');
    drawTyped();
    drawMarks();
    const st = player.playStream(items, { gapX: C.plan.gapX });
    Object.assign(R, { chars: st.chars, wordEnds: st.wordEnds, toneEnd: st.toneEnd, t0: st.start });
    // round: items and the end of each character in ms from the start of the line (typing "k" is timed from the same start)
    tr('round', { items, wpm: player.settings.wpm, fwpm: player.settings.fwpm,
      ends: st.chars.map((c) => [c.ch, Math.round(c.end - st.start)]) });
    const now = performance.now();
    const lag = C.plan.markLag;
    st.wordEnds.forEach((end, k) => {
      if (k < lag) return;
      R.timers.push(setTimeout(() => markWord(k - lag), Math.max(0, end - now) + MARK_AFTER_MS));
    });
    armTail();
  }

  function armTail() {
    clearTimeout(R.tail);
    const now = performance.now();
    const due = Math.max(R.toneEnd + ROUND_TAIL_MS, Math.min(now + ROUND_TAIL_MS / 2, R.toneEnd + TAIL_MAX_MS));
    R.tail = setTimeout(endRound, Math.max(0, due - now));
  }

  function markWord(k) {
    if (!R || R.done) return;
    // continuously: alignment of the sent text up to word k+markLag with everything typed – the mark only for word k
    const lag = C.plan.markLag;
    const upto = R.chars.filter((c) => c.w <= k + lag);
    const ev = evaluate(R.items.slice(0, k + lag + 1), upto, R.typed);
    R.marks[k] = ev.words[k];
    drawMarks();
  }

  function drawTyped() {
    const el = $('#cp-typed');
    el.textContent = R.disp.join('');
    const cur = document.createElement('span');
    cur.className = 'cur';
    cur.textContent = '​';
    el.append(cur);
  }

  function drawMarks() {
    const el = $('#cp-marks');
    el.textContent = '';
    R.marks.forEach((m) => {
      const s = document.createElement('span');
      s.textContent = m === null ? '·' : m ? '✓' : '✗';
      if (m !== null) s.className = m ? 'ok' : 'bad';
      el.append(s);
    });
  }

  function onChar(ch, ts) {
    if (!C.running || C.paused || !R || R.done) return;
    R.typed.push({ ch, t: ts });
    tr('k', [ch, Math.round(ts - R.t0)]);
    R.disp.push(ch);
    drawTyped();
    if (performance.now() > R.toneEnd) armTail();
  }

  function onSpace() {
    if (!R || R.done || C.paused) return;
    if (R.disp.length && R.disp.at(-1) !== ' ') { R.disp.push(' '); drawTyped(); }
  }

  function onBackspace() {
    if (!R || R.done || C.paused) return;
    if (R.disp.length && R.disp.at(-1) !== ' ') { R.disp.pop(); R.typed.pop(); drawTyped(); tr('bs'); }
  }

  function endRound() {
    if (!R || R.done) return;
    R.done = true;
    R.timers.forEach(clearTimeout);
    clearTimeout(R.tail);
    C.activeMs += performance.now() - R.t0;
    const ev = evaluate(R.items, R.chars, R.typed);
    C.rounds.push({ items: R.items, ev });
    tr('roundEnd', { acc: ev.sc.acc, words: ev.words.map((w) => (w ? 1 : 0)) });
    R.marks = ev.words;
    drawMarks();
    drawReview(ev);
    const sum = lessonSummary(C.rounds);
    $('#cp-acc').textContent = sum.acc === null ? '–' : pct(sum.acc);
    const last = C.activeMs >= C.lessonMs;
    $('#cp-status').textContent = t('copy.lineResult', { acc: ev.sc.acc === null ? '–' : pct(ev.sc.acc), ok: ev.words.filter(Boolean).length, n: ev.words.length });
    const nb = $('#cp-next');
    nb.textContent = last ? t('copy.toResult') : t('copy.nextLine');
    nb.hidden = false;
    R.review = true;
    // M8: fatigue per line – a break is proposed during the line correction (the stream is not interrupted)
    const f = C.fat.add(ev.sc, R.startS, C.activeMs / 1000);
    if (f.propose) proposeFatigue(f);
  }

  function proposeFatigue(f) {
    tr('fat', { kind: f.kind, accDrop: f.accDrop, missUp: f.missUp });
    C.fatEvents.push({ t: Math.round(C.activeMs / 1000), kind: f.kind, accDrop: f.accDrop, missUp: f.missUp, action: null });
    $('#cp-fat-text').textContent = (f.kind === 'acc'
      ? t('copy.fatAcc', { pp: Math.round(f.accDrop * 100) })
      : t('copy.fatMiss', { pp: Math.round(f.missUp * 100) }))
      + ` ${t('copy.fatAdvice')}`;
    $('#cp-fatigue-overlay').hidden = false;
  }

  function fatigueChoice(action) {
    tr('fatChoice', action);
    const e = C.fatEvents.at(-1);
    if (e) e.action = action;
    $('#cp-fatigue-overlay').hidden = true;
    if (action === 'pause') pause();
    else if (action === 'end') finish();
    else C.fat.snooze(C.activeMs / 1000);
  }

  function drawReview(ev) {
    const box = $('#cp-review');
    box.textContent = '';
    const sent = R.chars.map((c) => c.ch);
    const tch = R.typed.map((x) => x.ch);
    const wordOf = R.chars.map((c) => c.w);
    // blocks by words: an operation belongs to the word of the sent character, an insertion to the word before it
    const blocks = R.items.map(() => ({ s: [], t: [] }));
    let w = 0;
    for (const o of ev.ops) {
      if (o.s !== null) w = wordOf[o.s];
      const b = blocks[w];
      if (o.op === 'ok') { b.s.push(['ok', sent[o.s]]); b.t.push(['ok', tch[o.t]]); }
      if (o.op === 'sub') { b.s.push(['', sent[o.s]]); b.t.push(['sub', tch[o.t]]); }
      if (o.op === 'del') { b.s.push(['del', sent[o.s]]); b.t.push(['del', '_']); }
      if (o.op === 'ins') { b.s.push(['', ' ']); b.t.push(['ins', tch[o.t]]); }
    }
    blocks.forEach((b, k) => {
      const wb = document.createElement('span');
      wb.className = ev.words[k] ? 'wb' : 'wb bad';
      for (const [row, cls] of [[b.s, 'row'], [b.t, 'row typed']]) {
        const r = document.createElement('span');
        r.className = cls;
        for (const [c, ch] of row) {
          const s = document.createElement('span');
          if (c) s.className = c;
          s.textContent = ch;
          r.append(s);
        }
        wb.append(r);
      }
      box.append(wb);
    });
    const lg = document.createElement('div');
    lg.className = 'legend';
    lg.textContent = t('copy.legend');
    box.append(lg);
    box.hidden = false;
  }

  function next() {
    if (!R?.review) return;
    if (C.activeMs >= C.lessonMs) { finish(); return; }
    startRound();
  }

  // ---------- pause ----------
  function pause() {
    if (!C.running || C.paused) return;
    player.stop();
    if (R && !R.done) { // the interrupted line is dropped
      R.done = true;
      R.timers.forEach(clearTimeout);
      clearTimeout(R.tail);
      C.activeMs += Math.max(0, performance.now() - R.t0);
    }
    C.paused = true;
    C.pauseAt = Date.now();
    tr('pause');
    $('#cp-pause-overlay').hidden = false;
  }

  function resume() {
    if (!C.paused) return;
    C.pauses.push([Math.round(C.activeMs / 1000), Math.round((Date.now() - C.pauseAt) / 1000)]);
    tr('resume', [Math.round((Date.now() - C.pauseAt) / 1000), player.ctx?.state]);
    C.paused = false;
    C.fat.reset(); // after a pause a new window (the baseline stays)
    $('#cp-pause-overlay').hidden = true;
    if (R?.review) return; // pause during the line correction – continue with the "Next line" button
    deps.ensureAudio().then(() => { player.warmUp(); setTimeout(() => { if (C.running && !C.paused) startRound(); }, 1500); });
  }

  // ---------- end of the lesson ----------
  function finish() {
    clearInterval(C.tick);
    if (R && !R.done) pause();
    C.running = false;
    C.paused = false;
    $('#cp-pause-overlay').hidden = true;
    $('#cp-fatigue-overlay').hidden = true;
    player.stop();
    player.settings = settings; // back to the shared settings (the step speed applied to this lesson only)
    kbd.setMode(MODE_CHAR);
    deps.keepAwake(false);
    if (!C.rounds.length) { traceEnd(null, { empty: true }); deps.show('home'); return; }
    const s = lessonSummary(C.rounds);
    const p = C.plan;
    const saved = deps.addLesson({
      at: new Date().toISOString(), device: deps.deviceKind(), mode: MODE_COPY, level: deps.progress.level,
      durS: Math.round(C.activeMs / 1000), trials: s.n, correct: s.ok, acc: s.acc ?? 0, ttr: null,
      wpm: C.wpm, fwpm: C.fwpm,
      detail: {
        copy: { step: p.step, content: p.content, gapX: p.gapX, ...(p.wpm ? { wpm: p.wpm } : {}), markLag: p.markLag, ...s },
        ...(C.pauses.length ? { pauses: C.pauses } : {}),
        ...(C.fat.base || C.fatEvents.length ? { fatigue: { base: C.fat.base, events: C.fatEvents } } : {}),
      },
    });
    traceEnd(saved.id, { n: s.n, ok: s.ok, acc: s.acc, activeS: Math.round(C.activeMs / 1000) });
    showResult(s);
  }

  function showResult(s) {
    $('#cr-acc').textContent = s.acc === null ? '–' : pct(s.acc);
    $('#cr-words').textContent = t('copy.wordsOf', { ok: s.words.ok, n: s.words.n });
    $('#cr-lag').textContent = s.lagCh === null ? '–' : t('dash.lagChars', { n: num(s.lagCh) })
      + (C.plan.markLag > 1 && s.lagW !== null ? ` / ${t('dash.lagWords', { n: num(s.lagW) })}` : '');
    const cp = deps.coachInfo.data?.copy;
    let v;
    if (s.acc >= 0.9) v = `${t('copy.verdictGood', { acc: pct(s.acc) })} ${cp?.next || ''}`;
    else if (s.acc >= 0.75) v = t('copy.verdictMid', { acc: pct(s.acc) });
    else v = t('copy.verdictLow', { acc: pct(s.acc) });
    $('#cr-verdict').textContent = v;
    const d = [];
    if (s.lagMs !== null) {
      d.push(t('copy.lagDetail', { lag: num(s.lagCh), ms: s.lagMs, p90: s.lagChP90, max: s.lagChMax })
        + (s.lagW !== null ? ` ${t('copy.lagWordsDetail', { lag: num(s.lagW), p90: s.lagWP90 })}` : ''));
    }
    if (C.fatEvents.length) d.push(t('copy.fatNote'));
    if (s.drift !== null && s.drift > 1) d.push(t('copy.drift', { n: num(s.drift) }));
    d.push(t('copy.counts', { ok: s.ok, sub: s.sub, del: s.del, ins: s.ins, n: s.n, rounds: s.rounds }));
    if (s.confusions.length) d.push(`${t('result.confusions', { list: s.confusions.slice(0, 5).map((c) => `${c.pair} ${c.n}×`).join(', ') })}.`);
    $('#cr-detail').textContent = d.join(' ');
    const ld = deps.currentLoad();
    const rl = $('#cr-load');
    rl.hidden = false;
    rl.className = ld.suggestEnd || ld.dayWarn ? 'hint warn' : 'hint';
    rl.textContent = ld.dayWarn
      ? t('result.loadDayWarn', { min: Math.round(ld.dayMin), max: DAY_WARN_MIN })
      : ld.suggestEnd
        ? t('copy.loadSessionEnd', { min: Math.round(ld.sessionMin), max: SESSION_END_MIN })
        : t('result.loadSession', { min: Math.round(ld.sessionMin) });
    deps.show('copyresult');
  }

  /** Keys in the 'copy' view (PC). Returns true when handled. */
  function onKey(e) {
    if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return false;
    if (!$('#cp-fatigue-overlay').hidden) { // break proposed: Esc = pause, otherwise buttons only
      if (e.key === 'Escape') { fatigueChoice('pause'); return true; }
      return false;
    }
    if (e.key === 'Escape') { if (C.paused) resume(); else pause(); return true; }
    if (C.paused) return false;
    if (R?.review) {
      if (e.key === 'Enter' || e.key === ' ') { next(); return true; }
      return false;
    }
    if (e.key === 'Enter') { if (R && performance.now() > R.toneEnd) endRound(); return true; }
    if (e.key === ' ') { onSpace(); return true; }
    if (e.key === 'Backspace') { onBackspace(); return true; }
    const ch = normalizeKey(e.key);
    if (ch) { kbd.flash(ch); onChar(ch, e.timeStamp); return true; }
    return false;
  }

  $('#cp-next').addEventListener('click', next);
  $('#cp-pause').addEventListener('click', () => (C.paused ? resume() : pause()));
  $('#cp-resume').addEventListener('click', resume);
  $('#cp-finish').addEventListener('click', finish);
  $('#cp-fat-pause').addEventListener('click', () => fatigueChoice('pause'));
  $('#cp-fat-end').addEventListener('click', () => fatigueChoice('end'));
  $('#cp-fat-continue').addEventListener('click', () => fatigueChoice('continue'));

  return {
    start, onKey, onChar, onSpace,
    pause: () => (!$('#cp-fatigue-overlay').hidden ? fatigueChoice('pause') : C.paused ? resume() : pause()),
    hold: pause,
    get running() { return C.running; },
  };
}
