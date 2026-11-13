// SPDX-License-Identifier: EUPL-1.2
// 0.15.0: firmware of the HW key CwKey on the key page. The Pi follows the GitHub releases of the HW project
// (server/firmware.py); here the user writes the image to the key's UF2 bootloader drive:
//  - Chrome/Edge on a computer: pick the drive (showDirectoryPicker) → INFO_UF2.TXT tells the chip → download from the
//    Pi → SHA-256 + every UF2 block checked → write the file; the key restarts by itself.
//  - elsewhere (Android, Firefox, Safari): choose the chip, download the checked file, copy it to the drive by hand.
// FW 0.3.0 cannot tell its version (MIDI comes with 0.4.0) → the device remembers what it wrote last; when the HW
// stream key arrives and the Pi has something newer (or nothing was written from here yet) the page offers an update.
// 0.16.2: behind a switch the page reads the version from the key over USB MIDI (FW 0.4.0+, hwmidi.js) → the offer
// comes only for a newer FW, the chip is preselected, and the key can be switched to the bootloader without NRST.
import { api } from './api.js';
import { t, fmtDate } from './i18n.js';
import { checkUf2, parseInfo, pickTarget, sha256Hex } from './uf2.js';
import { HwMidi, offerUpdate, chipTarget, sharedMidi, midiSwitchOn, saveMidiSwitch } from './hwmidi.js';

const STORE = 'morse.fw.installed';
const $ = (sel) => document.querySelector(sel);

function readInstalled() {
  try { return JSON.parse(localStorage.getItem(STORE) || 'null'); } catch (e) { return null; }
}
const midiOn = midiSwitchOn;
const saveMidiOn = saveMidiSwitch;
function saveInstalled(version, mcu) {
  try { localStorage.setItem(STORE, JSON.stringify({ version, mcu, at: Date.now() })); } catch (e) { /* private */ }
}

export function initFwUi() {
  const S = { all: [], release: null, loaded: false, offered: false, wrote: null, pending: null, busy: false,
    midi: null, dev: null, reading: false };
  const canPick = typeof window.showDirectoryPicker === 'function';

  const sel = () => S.all[Number($('#fw-ver').value) || 0] || S.release;

  function renderChips() {
    const ts = sel()?.targets || [];
    $('#fw-chip').replaceChildren(...ts.map((tg, i) => new Option(tg.mcu, String(i))));
    const tg = chipTarget(sel(), S.dev?.chip); // 0.16.2: the chip the key reported over MIDI
    if (tg) $('#fw-chip').value = String(ts.indexOf(tg));
  }

  function midiMsg(key, params) {
    $('#fw-midi-msg').textContent = key ? t(key, params) : '';
  }

  function status(key, params, bad = false) {
    const el = $('#fw-msg');
    el.textContent = key ? t(key, params) : '';
    el.classList.toggle('bad', bad);
  }

  function render() {
    const rel = S.release;
    const inst = readInstalled();
    $('#fw-card').hidden = false;
    $('#fw-avail').textContent = rel
      ? t('fw.available', { version: rel.version, date: fmtDate(rel.released, { dateStyle: 'medium' }) })
      : t('fw.none');
    $('#fw-installed').textContent = S.dev
      ? t('fw.inKey', { version: S.dev.version, chip: S.dev.chip || '?' })
      : inst
        ? t('fw.installed', { version: inst.version, date: fmtDate(inst.at, { dateStyle: 'medium' }) })
        : t('fw.installedUnknown');
    $('#fw-midi-on').checked = midiOn();
    $('#fw-boot').hidden = !(S.dev?.caps.boot && S.midi?.connected());
    $('#fw-notes-box').hidden = !rel?.notes;
    $('#fw-notes').textContent = rel?.notes || '';
    $('#fw-start').hidden = !rel;
    $('#fw-start').textContent = t(rel && offerUpdate(rel.version, S.dev?.version, inst?.version) ? 'fw.update' : 'fw.rewrite');
    const vs = $('#fw-ver');
    const keep = vs.value;
    vs.replaceChildren(...S.all.map((r, i) => new Option(i ? t('fw.older', { version: r.version }) : r.version, String(i))));
    if (keep && Number(keep) < S.all.length) vs.value = keep;
    $('#fw-ver-row').hidden = S.all.length < 2;
    renderChips();
  }

  async function load() {
    try {
      const r = await api('GET', '/fw');
      S.release = r.release || null;
      S.all = S.release ? [S.release, ...(r.older || [])] : []; // 0.15.1: older versions = a way back
      S.loaded = true;
      S.loadedAt = Date.now();
    } catch (e) {
      $('#fw-card').hidden = !S.loaded; // no access / offline: keep what we have
      return;
    }
    render();
  }

  function openWizard() {
    $('#fw-offer').hidden = true;
    $('#fw-wizard').hidden = false;
    $('#fw-ver').value = '0'; // the newest unless the user picks an older one
    renderChips();
    $('#fw-pick').hidden = !canPick;
    $('#fw-manual').hidden = canPick;
    $('#fw-done').hidden = true;
    $('#fw-copied').hidden = true;
    status('');
  }

  async function fetchImage(tg) {
    const r = await fetch(`/api/fw/${encodeURIComponent(sel().version)}/${encodeURIComponent(tg.file)}`,
      { credentials: 'same-origin', cache: 'no-store' });
    if (!r.ok) throw new Error('download');
    const buf = await r.arrayBuffer();
    if (buf.byteLength !== tg.size || (await sha256Hex(buf)) !== tg.sha256) throw new Error('sha');
    checkUf2(buf, sel().family, tg.app_base);
    return buf;
  }

  function failText(e) {
    const k = { download: 'fw.err.download', sha: 'fw.err.sha', size: 'fw.err.uf2', magic: 'fw.err.uf2',
      family: 'fw.err.uf2', numbering: 'fw.err.uf2', address: 'fw.err.uf2' }[e?.message];
    return k || 'fw.err.write';
  }

  async function pickAndWrite() {
    if (S.busy || !S.release) return;
    S.busy = true;
    let dir;
    try {
      dir = await window.showDirectoryPicker({ id: 'cwkey-boot', mode: 'readwrite' });
    } catch (e) { S.busy = false; if (e?.name !== 'AbortError') status('fw.err.pick', {}, true); return; }
    try {
      let info = { model: '', board: '' };
      try { info = parseInfo(await (await (await dir.getFileHandle('INFO_UF2.TXT')).getFile()).text()); } catch (e) { /* none */ }
      const tg = pickTarget(sel(), info, dir.name);
      if (!tg) { status('fw.err.notDrive', { name: dir.name }, true); return; }
      status('fw.checking', { mcu: tg.mcu });
      const buf = await fetchImage(tg);
      status('fw.writing', { mcu: tg.mcu, version: sel().version });
      const fh = await dir.getFileHandle(tg.file, { create: true });
      const w = await fh.createWritable();
      await w.write(buf);
      try { await w.close(); } catch (e) { /* the drive disappears while the key restarts – that is normal */ }
      written(tg);
    } catch (e) {
      status(failText(e), {}, true);
    } finally { S.busy = false; }
  }

  async function download() {
    if (S.busy || !S.release) return;
    const tg = sel().targets[Number($('#fw-chip').value) || 0];
    S.busy = true;
    try {
      status('fw.checking', { mcu: tg.mcu });
      const buf = await fetchImage(tg);
      const url = URL.createObjectURL(new Blob([buf], { type: 'application/octet-stream' }));
      const a = document.createElement('a');
      a.href = url; a.download = tg.file;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      S.pending = tg;
      status('fw.downloaded', { file: tg.file, drive: tg.volume_label });
      $('#fw-copied').hidden = false;
    } catch (e) {
      status(failText(e), {}, true);
    } finally { S.busy = false; }
  }

  function written(tg) {
    const v = sel().version;
    S.wrote = { tg, at: performance.now(), version: v };
    saveInstalled(v, tg.mcu);
    status('fw.written', { version: v });
    $('#fw-done').hidden = false;
    render();
  }

  // 0.16.2: USB MIDI (FW 0.4.0+) – the version in the key, bootloader without NRST
  async function midiConnect() {
    if (!HwMidi.supported()) { midiMsg('fw.midi.unsupported'); return; }
    if (!S.midi) {
      S.midi = sharedMidi();
    }
    S.midi.onPorts = (on) => {
      if (on) setTimeout(readDev, 300); // the key came back (e.g. after a write) – let its USB settle
      else { S.dev = null; midiMsg('fw.midi.noPort'); render(); }
    };
    try {
      if (await S.midi.open()) await readDev();
      else midiMsg('fw.midi.noPort');
    } catch (e) {
      midiMsg(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'fw.midi.denied' : 'fw.midi.err');
    }
  }

  async function readDev() {
    if (!S.midi?.connected() || S.reading) return;
    S.reading = true;
    midiMsg('fw.midi.reading');
    try {
      S.dev = await S.midi.getInfo();
      midiMsg('fw.midi.info', { version: S.dev.version, chip: S.dev.chip || '?' });
      if (S.wrote && !S.wrote.ok && S.dev.version === S.wrote.version) {
        S.wrote.ok = true;
        if (!$('#fw-wizard').hidden) status('fw.keyBack', { version: S.wrote.version });
      }
    } catch (e) {
      S.dev = null;
      midiMsg('fw.midi.noAnswer');
    } finally { S.reading = false; }
    if (S.loaded) render();
    maybeOffer();
  }

  function maybeOffer() {
    if (S.offered || S.reading || !S.release || !$('#fw-wizard').hidden) return;
    if (!offerUpdate(S.release.version, S.dev?.version, readInstalled()?.version)) return;
    S.offered = true;
    $('#fw-offer-text').textContent = t('fw.offer', { version: S.release.version });
    $('#fw-offer').hidden = false;
  }

  async function enterBoot() {
    if (S.busy || !S.midi?.connected()) return;
    S.busy = true;
    try {
      await S.midi.enterBootloader();
      S.dev = null;
      $('#fw-boot').hidden = true;
      status('fw.boot.ok');
    } catch (e) {
      status(e?.message === 'busy' ? 'fw.boot.busy' : 'fw.boot.err', {}, true);
    } finally { S.busy = false; }
  }

  $('#fw-midi-on').addEventListener('change', (e) => {
    saveMidiOn(e.target.checked);
    if (e.target.checked) midiConnect();
    else { S.midi?.close(); S.midi = null; S.dev = null; midiMsg(''); if (S.loaded) render(); }
  });
  $('#fw-boot-btn').addEventListener('click', enterBoot);
  $('#fw-ver').addEventListener('change', () => { renderChips(); status(''); });
  $('#fw-start').addEventListener('click', openWizard);
  $('#fw-offer-yes').addEventListener('click', openWizard);
  $('#fw-offer-no').addEventListener('click', () => { $('#fw-offer').hidden = true; });
  $('#fw-pick-btn').addEventListener('click', pickAndWrite);
  $('#fw-download').addEventListener('click', download);
  $('#fw-copied').addEventListener('click', () => {
    if (S.pending) written(S.pending);
    S.pending = null;
    $('#fw-copied').hidden = true;
  });
  $('#fw-close').addEventListener('click', () => { $('#fw-wizard').hidden = true; status(''); });

  return {
    /** The key page opened. */
    show() {
      load();
      if (midiOn() && !S.midi) midiConnect();
    },
    /** A HW stream key arrived: after a write = the key runs again; otherwise maybe offer the update once. */
    hwSeen() {
      if (S.wrote && !S.wrote.ok) {
        S.wrote.ok = true;
        if (!$('#fw-wizard').hidden) status('fw.keyBack', { version: S.wrote.version });
        return;
      }
      if (S.offered || S.checking || !$('#fw-wizard').hidden) return;
      // 0.15.2: the page may be open for long – the Pi checks GitHub on every login, so ask it again (≤ 1× a minute)
      if (Date.now() - (S.loadedAt || 0) > 60000) {
        S.checking = true;
        load().finally(() => { S.checking = false; this.hwSeen(); });
        return;
      }
      if (midiOn() && S.midi?.connected() && !S.dev) { readDev(); return; } // the offer follows the version
      maybeOffer();
    },
  };
}
