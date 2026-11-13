// SPDX-License-Identifier: EUPL-1.2
// 0.16.2: the USB MIDI settings channel of the HW key CwKey (FW 0.4.0+, morse-key-hw docs/midi-settings-spec.md,
// protocol version 1). Pure functions (frames, 14-bit numbers, decoding, ranges, the update offer) are ported to
// tests/hwmidi.py – when they change, update the port too (test_hwmidi.py checks constants and fragments).
// The driver (HwMidi) needs Web MIDI with SysEx: Chrome/Edge on a computer, Chrome on Android; elsewhere the app
// works as before (the version is what this device wrote last). MIDI never keys anything (H-21).
import { newer } from './uf2.js';

export const MIDI_MFR = 0x7D;            // non-commercial manufacturer ID
export const MIDI_ID0 = 0x43;            // 'C'
export const MIDI_ID1 = 0x4B;            // 'K'
export const MIDI_PROTO = 1;             // protocol version
export const MIDI_GET_INFO = 0x01;
export const MIDI_GET_ALL = 0x02;
export const MIDI_GET = 0x03;
export const MIDI_SET = 0x04;
export const MIDI_SAVE = 0x05;
export const MIDI_RESET_DEFAULTS = 0x06;
export const MIDI_ENTER_BOOTLOADER = 0x07;
export const MIDI_INFO = 0x41;
export const MIDI_VALUE = 0x42;
export const MIDI_ACK = 0x43;
export const MIDI_NAK = 0x44;
export const MIDI_CHANGED = 0x45;
export const MIDI_CAP_TONE = 1;          // capabilities bitmask of INFO
export const MIDI_CAP_PTT = 2;
export const MIDI_CAP_BOOT = 4;
export const MIDI_TIMEOUT = 500;         // ms per request, one retry (never for SAVE / ENTER_BOOTLOADER)
export const MIDI_RETRIES = 1;
export const MIDI_SAVE_TIMEOUT = 6000;   // SAVE waits until the keyer is idle (max 5 s in the FW)
export const MIDI_PORT = 'CW Key';       // port name (input and output)
export const BOOT_CONFIRM = [0x55, 0x46, 0x32]; // "UF2"
export const NAK_REASONS = ['', 'command', 'id', 'range', 'busy', 'unsupported', 'flash', 'confirm', 'frame'];
export const CHIPS = ['F411', 'F401'];

// [id, name, min, max] – spec section 5.3; unknown ids from the key are ignored
export const MIDI_SETTINGS = [
  [0x01, 'wpm', 5, 60],
  [0x02, 'keyer_mode', 0, 1],
  [0x03, 'dah_ratio_x10', 28, 35],
  [0x04, 'weight_pct', 25, 75],
  [0x05, 'element_memory', 0, 1],
  [0x06, 'paddle_swap', 0, 1],
  [0x07, 'usb_mode', 0, 1],
  [0x08, 'sidetone_on', 0, 1],
  [0x09, 'tone_hz', 300, 1200],
  [0x0A, 'volume_pct', 0, 100],
  [0x0B, 'ptt_enabled', 0, 1],
  [0x0C, 'ptt_lead_ms', 0, 100],
  [0x0D, 'ptt_hang_ms', 50, 3000],
  [0x0E, 'stream_key', 0x04, 0x73],
];
const BY_ID = new Map(MIDI_SETTINGS.map((s) => [s[0], s]));

/** A number 0–16383 → [LSB7, MSB7]. */
export function to14(v) {
  if (!Number.isInteger(v) || v < 0 || v > 16383) throw new Error('range');
  return [v & 0x7f, (v >> 7) & 0x7f];
}

export function from14(lo, hi) {
  return (lo & 0x7f) | ((hi & 0x7f) << 7);
}

/** A host → key message: F0 7D 43 4B ver cmd seq payload… F7. */
export function frame(cmd, seq, payload = []) {
  for (const b of payload) if (!Number.isInteger(b) || b < 0 || b > 127) throw new Error('byte');
  return [0xF0, MIDI_MFR, MIDI_ID0, MIDI_ID1, MIDI_PROTO, cmd & 0x7f, seq & 0x7f, ...payload, 0xF7];
}

/** SET of a known setting within its range, else Error('id') / Error('range') – nothing is sent then. */
export function setFrame(seq, id, value) {
  const s = BY_ID.get(id);
  if (!s) throw new Error('id');
  if (!Number.isInteger(value) || value < s[2] || value > s[3]) throw new Error('range');
  return frame(MIDI_SET, seq, [id, ...to14(value)]);
}

export function bootFrame(seq) {
  return frame(MIDI_ENTER_BOOTLOADER, seq, BOOT_CONFIRM);
}

/** Bytes from the key → {cmd, seq, payload}, or null when it is not a CW Key message of our protocol version. */
export function parse(bytes) {
  const b = Array.from(bytes || []);
  if (b.length < 8 || b[0] !== 0xF0 || b[b.length - 1] !== 0xF7) return null;
  if (b[1] !== MIDI_MFR || b[2] !== MIDI_ID0 || b[3] !== MIDI_ID1 || b[4] !== MIDI_PROTO) return null;
  const body = b.slice(5, -1);
  if (body.some((x) => x > 127)) return null;
  return { cmd: body[0], seq: body[1], payload: body.slice(2) };
}

/** A parsed message → {type, …}, or null (unknown or too short – ignored). */
export function decode(m) {
  if (!m) return null;
  const p = m.payload;
  if (m.cmd === MIDI_INFO) {
    if (p.length < 8) return null;
    const n = p[7];
    const caps = p[6];
    return {
      type: 'info', seq: m.seq, proto: p[0], version: `${p[1]}.${p[2]}.${p[3]}`, chip: CHIPS[p[4]] ?? null,
      caps: { tone: !!(caps & MIDI_CAP_TONE), ptt: !!(caps & MIDI_CAP_PTT), boot: !!(caps & MIDI_CAP_BOOT) },
      name: String.fromCharCode(...p.slice(8, 8 + n)),
    };
  }
  if (m.cmd === MIDI_VALUE || m.cmd === MIDI_CHANGED) {
    if (p.length < 3) return null;
    const s = BY_ID.get(p[0]);
    return { type: m.cmd === MIDI_VALUE ? 'value' : 'changed', seq: m.seq, id: p[0], name: s ? s[1] : null,
      value: from14(p[1], p[2]) };
  }
  if (m.cmd === MIDI_ACK) return p.length < 1 ? null : { type: 'ack', seq: m.seq, of: p[0] };
  if (m.cmd === MIDI_NAK) {
    if (p.length < 2) return null;
    return { type: 'nak', seq: m.seq, of: p[0], code: p[1], reason: NAK_REASONS[p[1]] || 'unknown' };
  }
  return null;
}

/** GET_ALL values → {name: value} of known settings only. */
export function settingsMap(values) {
  const out = {};
  for (const v of values || []) if (v.name) out[v.name] = v.value;
  return out;
}

/** Automatic retries of a command: never for SAVE and ENTER_BOOTLOADER (spec section 8). */
export function retriesFor(cmd) {
  return cmd === MIDI_SAVE || cmd === MIDI_ENTER_BOOTLOADER ? 0 : MIDI_RETRIES;
}

/** The version the update offer compares with: read from the key when known, else what this device wrote last. */
export function knownVersion(deviceVersion, writtenHere) {
  return deviceVersion || writtenHere || null;
}

/** Offer the firmware `available`? With the version from the key only when it is newer; unknown → as before. */
export function offerUpdate(available, deviceVersion, writtenHere) {
  return newer(available, knownVersion(deviceVersion, writtenHere));
}

/** The release target of the chip the key reported (F411 / F401), else null. */
export function chipTarget(release, chip) {
  if (!chip) return null;
  return (release?.targets || []).find((tg) => String(tg.mcu || '').includes(chip)) || null;
}

/** Web MIDI driver of one CW Key (browser only). */
export class HwMidi {
  constructor() {
    this.access = null;
    this.inp = null;
    this.out = null;
    this.seq = 0;
    this.wait = new Map();
    this.info = null;
    this.onChanged = null;   // (decoded CHANGED) – a setting changed with the KEY button
    this.onPorts = null;     // (connected: bool) – the key appeared / disappeared
  }

  static supported() {
    return typeof navigator !== 'undefined' && typeof navigator.requestMIDIAccess === 'function';
  }

  /** Asks for MIDI access (a permission prompt the first time); true when the key's ports are there. */
  async open() {
    this.closed = false;
    if (!this.access) {
      this.access = await navigator.requestMIDIAccess({ sysex: true });
      this.access.addEventListener('statechange', () => {
        if (this.closed) return;
        const was = this.connected();
        this.bind();
        if (was !== this.connected()) {
          if (!this.connected()) this.info = null;
          this.onPorts?.(this.connected());
        }
      });
    }
    return this.bind();
  }

  connected() { return !!(this.inp && this.out); }

  /** Stops listening (the switch turned off); MIDI access itself stays granted. */
  close() {
    this.closed = true;
    if (this.inp) this.inp.onmidimessage = null;
    for (const w of this.wait.values()) clearTimeout(w.timer);
    this.wait.clear();
    this.inp = this.out = this.info = null;
    this.onPorts = this.onChanged = null;
  }

  bind() {
    const find = (map) => [...map.values()].find((p) => p.state !== 'disconnected' && String(p.name || '').includes(MIDI_PORT)) || null;
    const inp = find(this.access.inputs);
    if (inp !== this.inp) {
      if (this.inp) this.inp.onmidimessage = null;
      this.inp = inp;
      if (inp) inp.onmidimessage = (e) => this.message(e.data);
    }
    this.out = find(this.access.outputs);
    return this.connected();
  }

  message(data) {
    const d = decode(parse(data));
    if (!d) return;
    if (d.type === 'changed') { this.onChanged?.(d); return; }
    const w = this.wait.get(d.seq);
    if (!w) return;
    if (d.type === 'value' && w.collect) { w.values.push(d); w.arm(); return; }
    this.wait.delete(d.seq);
    clearTimeout(w.timer);
    w.resolve(w.collect ? { ...d, values: w.values } : d);
  }

  once(cmd, bytes, collect, ms) {
    return new Promise((resolve, reject) => {
      if (!this.connected()) { reject(new Error('port')); return; }
      const seq = this.seq = (this.seq + 1) & 0x7f;
      const w = { collect, values: [], resolve };
      w.arm = () => {
        clearTimeout(w.timer);
        w.timer = setTimeout(() => { this.wait.delete(seq); reject(new Error('timeout')); }, ms);
      };
      this.wait.set(seq, w);
      w.arm();
      try { this.out.send(bytes(seq)); } catch (e) { clearTimeout(w.timer); this.wait.delete(seq); reject(e); }
    });
  }

  async request(cmd, bytes = (seq) => frame(cmd, seq), collect = false) {
    const ms = cmd === MIDI_SAVE ? MIDI_SAVE_TIMEOUT : MIDI_TIMEOUT;
    for (let i = 0; ; i++) {
      try { return await this.once(cmd, bytes, collect, ms); } catch (e) {
        if (e.message !== 'timeout' || i >= retriesFor(cmd)) throw e;
      }
    }
  }

  async getInfo() {
    const d = await this.request(MIDI_GET_INFO);
    if (d.type !== 'info') throw new Error('reply');
    this.info = d;
    return d;
  }

  async getAll() {
    const d = await this.request(MIDI_GET_ALL, undefined, true);
    if (d.type !== 'ack') throw new Error(d.reason || 'reply');
    return settingsMap(d.values);
  }

  /** SET in the key's RAM (the key stores it itself 5 s later) → the ACK / NAK. */
  set(id, value) {
    return this.request(MIDI_SET, (seq) => setFrame(seq, id, value));
  }

  /** ENTER_BOOTLOADER → ACK, then the key restarts into TinyUF2 (its drive appears). Never retried. */
  async enterBootloader() {
    const d = await this.request(MIDI_ENTER_BOOTLOADER, (seq) => bootFrame(seq));
    if (d.type !== 'ack') throw new Error(d.reason || 'reply');
    this.info = null;
    return d;
  }
}
