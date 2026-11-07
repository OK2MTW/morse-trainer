// SPDX-License-Identifier: EUPL-1.2
// ZB listening lab (development): plays a QSO-like line in a chosen band situation, the coach judges whether it sounds
// like a real band. Nothing is stored. Visible only to coaches (Settings → Band sound).
import { t } from './i18n.js';
import { BandSound, BAND_PRESETS, BAND_DEFAULTS, bandParams } from './band.js';

const $ = (sel) => document.querySelector(sel);

// sliders: [param, min, max, step]
const SLIDERS = [
  ['wpm', 12, 35, 1], ['noise', 0, 1.5, 0.05], ['qsb', 0, 0.95, 0.05], ['qsbRate', 0.05, 0.8, 0.05],
  ['qrn', 0, 60, 2], ['qrm', 0, 3, 1], ['chirp', 0, 80, 5], ['drift', 0, 60, 5], ['rise', 1, 10, 1], ['hand', 0, 0.3, 0.02],
];
const FILTERS = [250, 500, 2400];

const CALLS = ['OK2ABC', 'OK1FXX', 'OL7M', 'DL1ZZ', 'SP6ABC', 'OM3TT', 'G4ABC', 'F5XYZ', 'S52AA', 'HA5KK'];
const NAMES = ['PETR', 'JAN', 'TOM', 'EVA', 'KAREL', 'JIRI'];
const QTHS = ['BRNO', 'PRAHA', 'OLOMOUC', 'LIBEREC', 'PLZEN'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];

/** A random QSO-like line (the trained characters do not matter here – it is about the sound). */
function line() {
  const a = pick(CALLS);
  let b = pick(CALLS);
  while (b === a) b = pick(CALLS);
  const rst = `5${pick(['5', '7', '9'])}9`;
  return pick([
    `CQ CQ CQ DE ${a} ${a} PSE K`,
    `${b} DE ${a} GM UR RST ${rst} ${rst} NAME ${pick(NAMES)} QTH ${pick(QTHS)} HW? ${b} DE ${a} K`,
    `${a} DE ${b} R TNX FER CALL UR ${rst} QSB WX CLOUDY TEMP 8C ${a} DE ${b} KN`,
    `TEST ${a} ${a} TEST`,
    `${b} DE ${a} TNX QSO 73 GL ES CUAGN ${b} DE ${a} SK`,
  ]);
}

export function initBandLab({ player, ensureAudio }) {
  const band = new BandSound(player);
  const lab = { preset: 'clean', p: bandParams('clean'), text: '', playing: false };

  function syncControls() {
    for (const [k] of SLIDERS) {
      const inp = $(`#band-${k}`);
      if (!inp) continue;
      inp.value = lab.p[k];
      $(`#band-${k}-v`).textContent = String(lab.p[k]);
    }
    $('#band-filter').value = String(lab.p.filterBw);
    for (const b of document.querySelectorAll('#band-presets button')) b.classList.toggle('active', b.dataset.preset === lab.preset);
    $('#band-preset-hint').textContent = t(`band.presetHint.${lab.preset}`);
  }

  function render() {
    const box = $('#band-presets');
    if (!box.children.length) {
      for (const id of Object.keys(BAND_PRESETS)) {
        const b = document.createElement('button');
        b.type = 'button';
        b.dataset.preset = id;
        b.textContent = t(`band.preset.${id}`);
        b.addEventListener('click', () => { lab.preset = id; lab.p = bandParams(id, { wpm: lab.p.wpm }); syncControls(); play(); });
        box.append(b);
      }
      const sl = $('#band-sliders');
      for (const [k, min, max, step] of SLIDERS) {
        const lbl = document.createElement('label');
        lbl.className = 'band-slider';
        const name = document.createElement('span');
        name.textContent = t(`band.param.${k}`);
        const v = document.createElement('span');
        v.id = `band-${k}-v`;
        v.className = 'muted';
        const inp = document.createElement('input');
        Object.assign(inp, { type: 'range', id: `band-${k}`, min, max, step });
        inp.addEventListener('input', () => {
          lab.p[k] = Number(inp.value);
          v.textContent = inp.value;
        });
        lbl.append(name, ' ', v, inp);
        sl.append(lbl);
      }
      const sel = $('#band-filter');
      for (const f of FILTERS) sel.add(new Option(`${f} Hz`, String(f)));
      sel.addEventListener('change', () => { lab.p.filterBw = Number(sel.value); });
    } else {
      for (const b of box.children) b.textContent = t(`band.preset.${b.dataset.preset}`);
    }
    $('#band-text').hidden = true;
    syncControls();
  }

  async function play() {
    if (!(await ensureAudio())) { alert(t('audio.failed')); return; }
    lab.text = line();
    $('#band-text').hidden = true;
    $('#band-text').textContent = lab.text;
    lab.playing = true;
    $('#band-status').textContent = t('band.playing');
    const { done } = band.play(lab.text, { ...BAND_DEFAULTS, ...lab.p, freq: player.settings.freq || 600 });
    await done;
    if (!lab.playing) return;
    lab.playing = false;
    $('#band-status').textContent = '';
  }

  function stop() {
    lab.playing = false;
    band.stop();
    $('#band-status').textContent = '';
  }

  $('#band-play').addEventListener('click', play);
  $('#band-stop').addEventListener('click', stop);
  $('#band-show').addEventListener('click', () => { $('#band-text').hidden = false; });

  return { render, stop };
}
