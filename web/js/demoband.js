// SPDX-License-Identifier: EUPL-1.2
// 0.9.9: demo without an account – "this is how the band sounds": a random QSO line in a chosen band situation; the text
// appears character by character exactly when it has sounded (in training you do not see it, of course). A taste of the
// goal for newcomers. Nothing is stored.
import { t } from './i18n.js';
import { BandSound, bandParams } from './band.js';
import { qsoLine } from './content.js';
import { KOCH_ORDER, CORE_SIZE } from './charset.js';

export const DEMO_BANDS = ['clean', 'weak', 'qsb', 'qrm', 'evening'];
export const DEMO_SPEEDS = [15, 20, 25];
const CHARS = KOCH_ORDER.slice(0, CORE_SIZE);
const MAX_WORDS = 14; // a sample, not a whole exchange (~20–40 s)

/** A short QSO line: the shortest of a few random ones within MAX_WORDS. */
function shortLine() {
  let best = null;
  for (let i = 0; i < 8; i++) {
    const l = qsoLine(CHARS, Math.random);
    if (l && (!best || l.length < best.length)) best = l;
    if (best && best.length <= MAX_WORDS && Math.random() < 0.5) break;
  }
  return best.length > MAX_WORDS ? best.slice(0, MAX_WORDS) : best;
}

const $ = (s) => document.querySelector(s);

export function initDemoBand({ player, ensureAudio }) {
  const band = new BandSound(player);
  const D = { preset: 'qsb', wpm: 20, timers: [], playing: false, built: false, run: 0 };

  function chips(box, values, label, current, onPick) {
    box.textContent = '';
    for (const v of values) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label(v);
      b.classList.toggle('active', v === current);
      b.setAttribute('aria-pressed', String(v === current));
      b.addEventListener('click', () => onPick(v));
      box.append(b);
    }
  }

  function draw() {
    chips($('#demo-band-presets'), DEMO_BANDS, (v) => t(`band.preset.${v}`), D.preset, (v) => { D.preset = v; draw(); play(); });
    chips($('#demo-band-speeds'), DEMO_SPEEDS, (v) => `${v} WPM`, D.wpm, (v) => { D.wpm = v; draw(); });
    $('#demo-band-hint').textContent = t(`band.presetHint.${D.preset}`);
    $('#demo-band-play').hidden = D.playing;
    $('#demo-band-stop').hidden = !D.playing;
  }

  function clearTimers() { D.timers.forEach(clearTimeout); D.timers = []; }

  async function play() {
    if (!(await ensureAudio())) { $('#demo-band-audio').hidden = false; return; }
    $('#demo-band-audio').hidden = true;
    clearTimers();
    const run = ++D.run;
    $('#demo-band-goal').hidden = true;
    const items = shortLine();
    const out = $('#demo-band-text');
    out.textContent = '';
    const st = band.playStream(items, bandParams(D.preset, { wpm: D.wpm, freq: 600 }), { gapX: 1, fwpm: D.wpm });
    D.playing = true;
    draw();
    const now = performance.now();
    st.chars.forEach((c, i) => {
      const space = i > 0 && st.chars[i - 1].w !== c.w ? ' ' : '';
      D.timers.push(setTimeout(() => { out.textContent += space + c.ch; }, Math.max(0, c.end - now)));
    });
    await st.done;
    if (run !== D.run || !D.playing) return; // replaced by a newer play or stopped
    const left = Math.max(0, (st.bandEnd ?? st.toneEnd) - performance.now()) + 150; // after the band has faded out (#20)
    D.timers.push(setTimeout(() => { D.playing = false; draw(); $('#demo-band-goal').hidden = false; }, left));
  }

  function stop() {
    D.run++;
    clearTimers();
    band.stop();
    D.playing = false;
    if (D.built) draw();
  }

  function render() {
    D.built = true;
    $('#demo-band-goal').hidden = true;
    stop();
  }

  $('#demo-band-play').addEventListener('click', play);
  $('#demo-band-stop').addEventListener('click', stop);
  return { render, stop };
}
