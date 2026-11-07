// SPDX-License-Identifier: EUPL-1.2
// Z-14 (0.10.16): entry test for those who already know CW. Every character of the main programme twice, answered on
// the keyboard, no correction (only a neutral flash). Result: known characters and the suggested number of characters
// in the Koch order; "Set N characters" moves the level (the characters count as introduced). Logic in entry.js.
import { t } from './i18n.js';
import { KOCH_ORDER, CORE_SIZE } from './charset.js';
import { MODE_CHAR } from './storage.js';
import { entrySequence, entryResult, ENTRY_TTR_MAX } from './entry.js';
import { traceBegin, traceEnd, tr, traceAudio, audioMeta } from './trace.js';

const $ = (s) => document.querySelector(s);
const TIMEOUT_MS = 6000; // after the end of the character → "don't know" (= ANSWER_TIMEOUT of lessons)
const GAP_MS = 700;      // pause before the next character

/** deps: {player, kbd, show, settings, progress, addLesson, saveProgress, ensureAudio, keepAwake, deviceKind, setHandlers, level()} */
export function initEntry(deps) {
  const { player, kbd, settings, progress } = deps;
  const E = { running: false };
  const chars = KOCH_ORDER.slice(0, CORE_SIZE);

  async function start() {
    if (!(await deps.ensureAudio())) { alert(t('audio.failed')); return; }
    await deps.keepAwake(true);
    Object.assign(E, { running: true, paused: false, seq: entrySequence(chars), i: 0, trials: [], t0: performance.now(),
      timer: null, answered: true, levelBefore: deps.level() });
    player.settings = { ...settings };
    traceAudio(player.ctx);
    traceBegin(MODE_CHAR, { entry: true, level: E.levelBefore, device: deps.deviceKind(), wpm: settings.wpm, fwpm: settings.fwpm,
      audio: audioMeta(player), ua: navigator.userAgent.slice(0, 200) });
    kbd.setMode(MODE_CHAR);
    kbd.setActive(chars);
    deps.setHandlers({ input: onAnswer, pause, repeat: null });
    $('#en-pause-overlay').hidden = true;
    $('#en-speed').textContent = t('entry.speed', { wpm: settings.wpm, fwpm: settings.fwpm });
    deps.show('entry');
    E.timer = setTimeout(next, 900);
  }

  function next() {
    if (!E.running || E.paused) return;
    if (E.i >= E.seq.length) { finish(); return; }
    E.cur = E.seq[E.i];
    E.answered = false;
    $('#en-count').textContent = t('entry.count', { i: E.i + 1, n: E.seq.length });
    $('#en-progress').style.width = `${(E.i / E.seq.length) * 100}%`;
    E.toneEnd = player.play(E.cur).toneEnd;
    tr('p', [E.cur, settings.wpm, settings.fwpm, Math.round(E.toneEnd - performance.now()), null, 'e']);
    E.timer = setTimeout(() => record(null, null), Math.max(0, E.toneEnd - performance.now()) + TIMEOUT_MS);
  }

  function onAnswer(ch, ts) {
    if (!E.running || E.paused || E.answered) return;
    record(ch, Math.round(ts - E.toneEnd));
  }

  function record(ans, ttr) {
    if (E.answered) return;
    E.answered = true;
    clearTimeout(E.timer);
    E.trials.push({ ch: E.cur, ans, ttr });
    if (ans === null) tr('to'); else tr('a', [ans, ttr, ans === E.cur ? 1 : 0]);
    E.i++;
    // no correction during the test – the next character after a short gap (an answer during the tone does not cut it)
    E.timer = setTimeout(next, Math.max(0, E.toneEnd - performance.now()) + GAP_MS);
  }

  function pause() {
    if (!E.running || E.paused) return;
    E.paused = true;
    clearTimeout(E.timer);
    player.stop();
    if (!E.answered) E.answered = true; // the interrupted character is played again after the pause
    tr('pause');
    $('#en-pause-overlay').hidden = false;
  }

  function resume() {
    if (!E.paused) return;
    E.paused = false;
    tr('resume', [0]);
    $('#en-pause-overlay').hidden = true;
    E.timer = setTimeout(next, 600);
  }

  function stop() {
    E.running = false;
    clearTimeout(E.timer);
    player.stop();
    deps.setHandlers({});
    deps.keepAwake(false);
  }

  /** Ends the test early – nothing is changed or stored. */
  function cancel() {
    if (!E.running) return;
    stop();
    traceEnd(null, { entry: 'cancel', n: E.trials.length });
    deps.show('home');
  }

  function finish() {
    stop();
    const r = entryResult(chars, E.trials);
    const ok = E.trials.filter((x) => x.ans === x.ch);
    const ttrs = ok.map((x) => x.ttr).sort((a, b) => a - b);
    // stored as a character lesson with the entry flag – the coach gets first statistics of every character
    const saved = deps.addLesson({
      at: new Date().toISOString(), device: deps.deviceKind(), level: E.levelBefore,
      durS: Math.round((performance.now() - E.t0) / 1000), trials: E.trials.length, correct: ok.length,
      acc: E.trials.length ? ok.length / E.trials.length : 0, ttr: ttrs.length ? ttrs[(ttrs.length - 1) >> 1] : null,
      wpm: settings.wpm, fwpm: settings.fwpm,
      detail: { perChar: r.perChar, adv: 'entry', entry: true },
    });
    traceEnd(saved.id, { entry: true, level: r.level, known: r.known.length });
    E.result = r;
    showResult(r);
  }

  function showResult(r) {
    $('#er-known').textContent = `${r.known.length} / ${chars.length}`;
    $('#er-level').textContent = String(r.level);
    const nextCh = chars[r.level];
    $('#er-text').textContent = t('entry.result', { known: r.known.length, n: chars.length, ms: ENTRY_TTR_MAX, level: r.level })
      + (nextCh ? ` ${t('entry.resultNext', { ch: nextCh })}` : ` ${t('entry.resultAll')}`);
    $('#er-unsure').textContent = r.unsure.length ? t('entry.unsure', { list: r.unsure.join(' ') }) : '';
    const apply = $('#er-apply');
    apply.hidden = r.level <= progress.level;
    apply.textContent = t('entry.apply', { n: r.level });
    $('#er-same').textContent = r.level <= progress.level ? t('entry.keepHigher', { n: progress.level }) : t('entry.keep');
    deps.show('entryresult');
  }

  function apply() {
    const r = E.result;
    if (!r || r.level <= progress.level) { deps.show('home'); return; }
    progress.level = r.level;
    for (const c of chars.slice(0, r.level)) if (!progress.introduced.includes(c)) progress.introduced.push(c);
    deps.saveProgress();
    deps.show('home');
  }

  $('#en-pause').addEventListener('click', pause);
  $('#en-resume').addEventListener('click', resume);
  $('#en-cancel').addEventListener('click', cancel);
  $('#er-apply').addEventListener('click', apply);

  return {
    start, pause,
    hold: () => { if (E.running && !E.paused) pause(); },
    onKey: (e) => { if (e.key === 'Escape') { if (E.paused) resume(); else pause(); return true; } return false; },
    get running() { return E.running; },
  };
}
