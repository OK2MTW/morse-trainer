// SPDX-License-Identifier: EUPL-1.2
// 0.9.2: demo without an account – a short beginner lesson with three characters (K, M, U) to try the sound and the
// keyboard. Nothing is stored or sent: no progress, no statistics, no debug trace. Fixed beginner pace (20/15 WPM).
import { t } from './i18n.js';

export const DEMO_CHARS = ['K', 'M', 'U'];
const DEMO_TEMPO = { wpm: 20, fwpm: 15, freq: 600, volume: 0.7 };
const DEMO_MS = 60000;          // active drill time
const ANSWER_TIMEOUT = 6000;    // ms after the end of the character → "don't know"
const FIX_AFTER_PRESS = 600;    // the correction at the earliest this long after the answer …
const FIX_AFTER_TONE = 700;     // … and this long after the original character has finished
const NEXT_GAP = 700;           // pause before the next character after a correct answer
const AFTER_FIX_GAP = 1500;     // longer pause after a correction (it must not merge with the next character)

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const untilTone = (end) => Math.max(0, end - performance.now());

/**
 * @param {{player: import('./audio.js').MorsePlayer, kbd: import('./keyboard.js').TouchKeyboard,
 *          ensureAudio: () => Promise<boolean>, setHandlers: (h: {input?, repeat?, pause?}) => void}} deps
 */
export function initDemo({ player, kbd, ensureAudio, setHandlers }) {
  const S = { run: 0, phase: 'idle', current: null, toneEnd: 0, answered: true, trials: [], activeMs: 0,
    last: 0, tick: null, timer: null, saved: null };

  const stage = (ch = '', cls = '', status = '') => {
    $('#demo-char').textContent = ch;
    $('#demo-char').className = `big-char${cls ? ` ${cls}` : ''}`;
    $('#demo-status').textContent = status;
  };
  const part = (name) => {
    for (const p of ['idle', 'play', 'result']) $(`#demo-${p}`).hidden = p !== name;
    $('#demo-band').hidden = name === 'play'; // 0.9.9: the band sample only outside the demo lesson
  };
  const later = (fn, ms) => { clearTimeout(S.timer); S.timer = setTimeout(fn, ms); };

  function render() {
    stop();
    part('idle');
    kbd.setMode('znak');
    kbd.setActive(DEMO_CHARS);
  }

  async function start() {
    if (!(await ensureAudio())) { $('#demo-audio').hidden = false; return; }
    $('#demo-audio').hidden = true;
    stop();
    const run = ++S.run;
    S.saved = player.settings;
    player.settings = { ...DEMO_TEMPO };
    player.keepAlive(true);
    Object.assign(S, { trials: [], activeMs: 0, answered: true, current: null });
    part('play');
    updateBar();
    // introduction: each character twice with its letter shown
    S.phase = 'intro';
    setHandlers({ input: null, repeat: () => { if (S.current) player.play(S.current); }, pause: stop });
    for (const [i, c] of DEMO_CHARS.entries()) {
      S.current = c;
      stage(c, '', t('demo.listen', { i: i + 1, n: DEMO_CHARS.length }));
      await sleep(i === 0 ? 900 : 400);
      for (let k = 0; k < 2; k++) {
        if (run !== S.run) return;
        await player.play(c).done;
        await sleep(450);
      }
    }
    if (run !== S.run) return;
    // drill
    S.phase = 'drill';
    stage('', '', t('lesson.getReady'));
    setHandlers({ input: onAnswer, repeat: onRepeat, pause: stop });
    S.last = performance.now();
    S.tick = setInterval(() => {
      const now = performance.now();
      S.activeMs += now - S.last;
      S.last = now;
      updateBar();
    }, 250);
    later(next, 900);
  }

  function pick() {
    // random, but never the same character three times in a row
    const n = S.trials.length;
    const same = n >= 2 && S.trials[n - 1].ch === S.trials[n - 2].ch ? S.trials[n - 1].ch : null;
    const pool = DEMO_CHARS.filter((c) => c !== same);
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function next() {
    if (S.phase !== 'drill') return;
    if (S.activeMs >= DEMO_MS) return finish();
    S.current = pick();
    S.answered = false;
    stage();
    S.toneEnd = player.play(S.current).toneEnd;
    armTimeout();
  }

  function armTimeout() {
    later(onTimeout, untilTone(S.toneEnd) + ANSWER_TIMEOUT);
  }

  function onAnswer(ch, ts) {
    if (S.phase !== 'drill' || S.answered) return;
    S.answered = true;
    const ttr = Math.round(ts - S.toneEnd);
    const ok = ch === S.current;
    S.trials.push({ ch: S.current, ok, ttr });
    updateBar();
    if (ok) {
      stage(S.current, 'ok', `${Math.max(0, ttr)} ms`);
      later(next, untilTone(S.toneEnd) + NEXT_GAP);
    } else {
      stage(S.current, 'bad', t('lesson.wasYou', { ch: S.current, ans: ch }));
      kbd.flash(S.current, 'hint', 1500);
      later(fix, Math.max(FIX_AFTER_PRESS, untilTone(S.toneEnd) + FIX_AFTER_TONE));
    }
  }

  function onTimeout() {
    if (S.phase !== 'drill' || S.answered) return;
    S.answered = true;
    S.trials.push({ ch: S.current, ok: false, ttr: null });
    stage(S.current, 'miss', t('lesson.was', { ch: S.current }));
    kbd.flash(S.current, 'hint', 1500);
    updateBar();
    later(fix, FIX_AFTER_PRESS);
  }

  function fix() {
    if (S.phase !== 'drill') return;
    const { toneEnd } = player.play(S.current);
    later(next, untilTone(toneEnd) + AFTER_FIX_GAP);
  }

  function onRepeat() {
    if (S.phase !== 'drill' || S.answered) return;
    S.toneEnd = player.play(S.current).toneEnd;
    armTimeout();
  }

  function updateBar() {
    const s = Math.ceil(Math.max(0, DEMO_MS - S.activeMs) / 1000);
    $('#demo-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    $('#demo-progress').style.width = `${Math.min(100, (S.activeMs / DEMO_MS) * 100)}%`;
    const n = S.trials.length;
    $('#demo-acc').textContent = n ? `${Math.round((S.trials.filter((x) => x.ok).length / n) * 100)} % · ${n}` : '–';
  }

  function finish() {
    const trials = S.trials;
    stop();
    const ok = trials.filter((x) => x.ok);
    const ttrs = ok.map((x) => x.ttr).filter((x) => x != null && x >= 0).sort((a, b) => a - b);
    const med = ttrs.length ? ttrs[Math.floor(ttrs.length / 2)] : null;
    $('#demo-score').textContent = trials.length
      ? t('demo.score', { ok: ok.length, n: trials.length, pct: Math.round((ok.length / trials.length) * 100) })
      : t('demo.noAnswers');
    $('#demo-ttr').textContent = med != null ? t('demo.reaction', { ms: med }) : '';
    part('result');
  }

  /** Stops everything (leaving the view, ⏸ / Esc, a new start). Restores the player settings. */
  function stop() {
    S.run++;
    S.phase = 'idle';
    clearTimeout(S.timer);
    clearInterval(S.tick);
    player.stop();
    player.keepAlive(false);
    if (S.saved) { player.settings = S.saved; S.saved = null; }
    setHandlers({ input: null, repeat: null, pause: null });
    if (!$('#demo-play').hidden) part('idle');
  }

  $('#demo-start').addEventListener('click', start);
  $('#demo-again').addEventListener('click', start);
  $('#demo-stop').addEventListener('click', stop);
  return { render, stop, get running() { return S.phase !== 'idle'; } };
}
