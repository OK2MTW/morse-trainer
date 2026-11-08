// SPDX-License-Identifier: EUPL-1.2
// ZB – band sound (development 2026-11-06): a receiver with noise, fading, static and other stations, plus keying of
// real transmitters (rise time / clicks, chirp, drift, hand keying). One engine for U5, the virtual operator, the CW room
// and contests. Everything is scheduled ahead in Web Audio – no timers during playback.
//
//   stations ─┬─ key (envelope) → QSB → level ─┐
//   noise ────┼────────────────────────────────┼─→ receiver filter (2× band-pass around the tone) → AGC-ish gain → out
//   QRN ──────┘                                │
//
// The receiver filter is common to all sources, so a narrow filter really removes a neighbouring station (as on the band).
import MorseCW from '../vendor/morse-pro/morse-pro-cw.js';
import * as WPM from '../vendor/morse-pro/morse-pro-wpm.js';

const LEAD = 0.15;           // s – scheduling margin (as audio.js)
const NOISE_LEAD = 0.8;      // s – the band is heard before the first character and after the last one
const NOISE_TAIL = 0.8;
// #20: everything (noise, static, other stations) ends together – the receiver output fades out over the last BAND_FADE s
// of the tail (after the last tone of the main station), other stations are cut at the end and start a new message only
// while QRM_MIN_LEFT s are left. Before 0.10.4 a QRM message started up to 3 s before the end played on without noise.
export const BAND_FADE = 0.6;
const QRM_MIN_LEFT = 1.2;
const STOP_FADE = 0.03;      // s – stop() during playback: fade instead of a click
const SIGNAL = 0.5;          // peak level of the main station
const REF_BW = 500;          // Hz – noise = 1 means in-band noise ≈ the signal (RMS) in a 500 Hz filter

/** Defaults of one situation; presets override a part of it. */
export const BAND_DEFAULTS = {
  wpm: 20, freq: 600,
  filterBw: 500,      // Hz – receiver filter width (250 CW narrow, 500 CW, 2400 SSB)
  noise: 0,           // 0–1 – noise level relative to the signal (≈ 1 / SNR)
  qsb: 0,             // 0–0.95 – depth of fading
  qsbRate: 0.15,      // Hz – speed of fading (0.05 slow … 0.6 fast flutter)
  qrn: 0,             // static crashes per minute
  qrm: 0,             // number of other stations (0–3)
  chirp: 0,           // Hz – frequency jump at key-down, settling in ~10 ms
  drift: 0,           // Hz – slow drift over the whole transmission
  rise: 5,            // ms – edge of the keying (1 = hard, clicks; 5 normal; 10 soft)
  hand: 0,            // 0–0.3 – hand keying: random deviation of element lengths
  toneVar: 0,         // Hz – M9: every line on a different tone (± toneVar around the set tone)
};

/** Situations for listening (ids are translated in the UI: band.preset.<id>). */
export const BAND_PRESETS = {
  clean: {},
  weak: { noise: 0.7, filterBw: 500 },
  qsb: { noise: 0.35, qsb: 0.85, qsbRate: 0.12 },
  flutter: { noise: 0.3, qsb: 0.6, qsbRate: 0.5 },
  qrn: { noise: 0.3, qrn: 30 },
  qrm: { noise: 0.25, qrm: 2, filterBw: 2400 },
  qrmNarrow: { noise: 0.25, qrm: 2, filterBw: 250 },
  hand: { hand: 0.18, rise: 3, noise: 0.15 },
  chirp: { chirp: 40, drift: 25, rise: 2, noise: 0.15 },
  evening: { noise: 0.5, qsb: 0.6, qsbRate: 0.15, qrn: 12, qrm: 2, hand: 0.1, chirp: 15, drift: 10, filterBw: 500 },
};

/**
 * M9 (U5): band situations of the copy-behind ladder (server/coach.py COPY_STEPS "band"), milder than the lab presets –
 * one new element per step. Not shown in the lab.
 */
export const BAND_LADDER = {
  u5noise: { noise: 0.35 },
  u5qsb: { noise: 0.25, qsb: 0.6, qsbRate: 0.12 },
  u5qrm: { noise: 0.2, qrm: 1, filterBw: 500 },
  u5mix: { noise: 0.3, qsb: 0.4, qsbRate: 0.15, qrn: 6, hand: 0.06, toneVar: 120, filterBw: 500 },
  u5band: { noise: 0.4, qsb: 0.5, qsbRate: 0.15, qrn: 10, qrm: 2, hand: 0.08, chirp: 10, drift: 8, toneVar: 150, filterBw: 500 },
};

export const bandParams = (preset, over = {}) => ({
  ...BAND_DEFAULTS, ...(BAND_PRESETS[preset] || BAND_LADDER[preset] || {}), ...over,
});

// M9 part 2 (2026-11-07): characters the band made unreadable do not count in copy-behind scoring (threshold 90 % stays).
// A character is masked when, over its keyed span: fading pulls the signal under the in-band noise (SNR < 0 dB in the
// filter) – 'f'; another station closer than MASK_QRM_HZ is keyed at ≥ MASK_QRM_RATIO of the main amplitude after the
// filter – 'm'; a static crash is louder (RMS) than the signal – 'n'. Python port: tests/band.py.
export const MASK_SNR = 1;
export const MASK_QRM_HZ = 300;
export const MASK_QRM_RATIO = 0.5;
export const MASK_QRN_RATIO = 1;

/** Fading gain at ctx time t – f = {base, lfo: [{rate, amp, start}]} as returned by _station. */
export const fadeAt = (f, t) => f.base + f.lfo.reduce((s, l) => s + l.amp * Math.sin(2 * Math.PI * l.rate * (t - l.start)), 0);

/** Amplitude gain of the receiver (2 band-pass sections, Q = freq / bw) for a tone off Hz from the tuned freq. */
export function bandpassGain(off, freq, bw) {
  const f = freq + off;
  const q = freq / bw;
  const h = 1 / Math.sqrt(1 + q * q * (f / freq - freq / f) ** 2);
  return h * h;
}

/**
 * Masked characters (pure, exported for tests). spans = [{from, to}] keyed span of each character of the main station
 * (ctx s); env = {noise, filterBw, freq, sampleRate, main (fade), qrm: [{off, level, keys: [[on, off]], fade}],
 * qrn: [[t, peak, decay]]}. Returns 'f' | 'm' | 'n' | null for each character.
 */
export function maskChars(spans, env) {
  const noiseRel = (env.noise || 0) * Math.sqrt(env.filterBw / REF_BW); // in-band noise RMS / signal RMS (fade 1)
  const crashRel = (0.577 * Math.sqrt((0.64 * env.filterBw) / (env.sampleRate / 2))) / (SIGNAL * Math.SQRT1_2);
  return spans.map(({ from, to }) => {
    const fm = Math.min(fadeAt(env.main, from), fadeAt(env.main, (from + to) / 2), fadeAt(env.main, to));
    if (noiseRel > 0 && fm < MASK_SNR * noiseRel) return 'f';
    for (const q of env.qrm || []) {
      if (Math.abs(q.off) >= MASK_QRM_HZ) continue;
      const g = (q.level / SIGNAL) * bandpassGain(q.off, env.freq, env.filterBw);
      for (const [a, b] of q.keys) {
        if (a < to && b > from && g * fadeAt(q.fade, (Math.max(a, from) + Math.min(b, to)) / 2) >= MASK_QRM_RATIO * fm) return 'm';
      }
    }
    for (const [t, peak, decay] of env.qrn || []) {
      const r0 = (peak * crashRel) / fm; // crash RMS / signal RMS at the attack, decays with time constant decay / 3
      if (r0 < MASK_QRN_RATIO || t >= to) continue;
      if (t + (decay / 3) * Math.log(r0 / MASK_QRN_RATIO) > from) return 'n';
    }
    return null;
  });
}

/** Normal random number (Box–Muller). */
function gauss(rng) {
  const u = Math.max(rng(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng());
}

/**
 * Element timings [ms] of a text (+ tone, − gap) with optional hand keying: every element and gap deviates randomly
 * (Gaussian, sigma = hand), a dah a little more than a dit. Exported for tests.
 */
export function keyTimings(text, wpm, hand = 0, rng = Math.random) {
  const cw = new MorseCW(true, wpm, wpm);
  cw.translate(text, false);
  const tm = cw.getTimings();
  if (!hand) return tm;
  return tm.map((ms) => {
    const f = Math.min(1.8, Math.max(0.45, 1 + gauss(rng) * hand * (Math.abs(ms) > 1800 / wpm ? 1.2 : 1)));
    return ms * f;
  });
}

/** Text of other stations (QRM) – calls and typical phrases, independent of the trained characters. */
const QRM_TEXTS = ['CQ CQ DE DL4ABC DL4ABC K', 'TEST OK1KHL OK1KHL', 'RST 599 599 BK', 'QRZ? DE G3XYZ K', 'TU 73 GL',
  'CQ DX DE SP9ZZ K', 'UR 579 NAME JAN JAN', '5NN 14 5NN 14'];

export class BandSound {
  constructor(player) {
    this.player = player; // MorsePlayer – shares its AudioContext and master volume
    this.nodes = [];
    this.timer = null;
  }

  get ctx() { return this.player.ctx; }

  _noiseBuffer(sec = 2) {
    if (this._noise) return this._noise;
    const n = Math.round(this.ctx.sampleRate * sec);
    const buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    this._noise = buf;
    return buf;
  }

  _track(node) { this.nodes.push(node); return node; }

  /** Receiver: 2 band-pass sections around the tone (steeper skirts) + make-up gain. */
  _receiver(p, t0) {
    const ctx = this.ctx;
    const q = p.freq / p.filterBw;
    const a = this._track(ctx.createBiquadFilter());
    const b = this._track(ctx.createBiquadFilter());
    for (const f of [a, b]) { f.type = 'bandpass'; f.frequency.value = p.freq; f.Q.value = q; }
    const out = this._track(ctx.createGain());
    out.gain.setValueAtTime(1, t0); // band-pass = 0 dB at the tone; noise level is normalised in _noiseSource
    a.connect(b).connect(out).connect(this.player.master);
    this.out = out;
    return a;
  }

  /** Common end of the band: the receiver output fades out over BAND_FADE s before `to` (all sources together). */
  _fadeOut(to) {
    this.out.gain.setValueAtTime(1, to - BAND_FADE);
    this.out.gain.linearRampToValueAtTime(0, to);
  }

  /**
   * One transmitter: keyed oscillator with chirp and drift, fading, level. tm = element timings (default from text).
   * Returns {end, ends, starts, keys, fade}: end of the last tone (s), the tone end after / start of each element (ctx s,
   * by index of tm), keyed intervals [[on, off]] and the fading {base, lfo} (for maskChars).
   * until (ctx s): tones are cut there (other stations end with the band, #20).
   */
  _station(rx, { text, tm: tm0 = null, wpm, freq, level, t0, p, qsb = 0, qsbRate = 0.15, until = Infinity, rng = Math.random }) {
    const ctx = this.ctx;
    const osc = this._track(ctx.createOscillator());
    const key = this._track(ctx.createGain());
    const fade = this._track(ctx.createGain());
    const lvl = this._track(ctx.createGain());
    osc.type = 'sine';
    key.gain.setValueAtTime(0, t0);
    lvl.gain.value = level;
    osc.connect(key).connect(fade).connect(lvl).connect(rx);
    const tm = tm0 || keyTimings(text, wpm, p.hand, rng);
    const ends = [];
    const starts = [];
    const keys = [];
    const total = tm.reduce((s, ms) => s + Math.abs(ms), 0) / 1000;
    const rise = Math.max(0.0008, p.rise / 1000);
    let t = t0;
    let end = t0;
    for (const ms of tm) {
      starts.push(t);
      const d = Math.min(Math.abs(ms) / 1000, Math.max(0, until - t));
      if (ms > 0 && d > 0.005) {
        keys.push([t, t + d]);
        const r = Math.min(rise, d / 3);
        const f = freq + p.drift * ((t - t0) / Math.max(total, 1));
        osc.frequency.setValueAtTime(f + p.chirp, t);
        if (p.chirp) osc.frequency.setTargetAtTime(f, t, 0.004);
        key.gain.setValueAtTime(0, t);
        key.gain.linearRampToValueAtTime(1, t + r);
        key.gain.setValueAtTime(1, t + d - r);
        key.gain.linearRampToValueAtTime(0, t + d);
        end = t + d;
      }
      t += Math.abs(ms) / 1000;
      ends.push(end);
    }
    osc.frequency.setValueAtTime(freq, t0 - 0.01);
    // fading: two slow sines of incommensurate rates → irregular, never periodic to the ear
    fade.gain.value = 1 - qsb / 2;
    const fd = { base: 1 - qsb / 2, lfo: [] };
    if (qsb > 0) {
      for (const [rate, share] of [[qsbRate, 0.7], [qsbRate * 0.37 + 0.013, 0.3]]) {
        const lfo = this._track(ctx.createOscillator());
        const depth = this._track(ctx.createGain());
        lfo.frequency.value = rate;
        depth.gain.value = (qsb / 2) * share;
        lfo.connect(depth).connect(fade.gain);
        // random phase: started up to 5 s in the past – but never before the context time 0 (#25: a fresh context right
        // after the page load threw a RangeError and the demo / the first U5 line did not play)
        const ls = Math.max(ctx.currentTime, t0 - rng() * 5);
        lfo.start(ls);
        fd.lfo.push({ rate, amp: (qsb / 2) * share, start: ls });
        lfo.stop(end + 0.1);
      }
    }
    osc.start(t0);
    osc.stop(end + 0.05);
    return { end, ends, starts, keys, fade: fd };
  }

  _noiseSource(rx, noise, from, to) {
    if (noise <= 0) return;
    // white noise (RMS 0.577) through the 2-section band-pass keeps ≈ sqrt(0.64 · bw / (fs/2)) of it → normalise to REF_BW,
    // so a wider filter lets more noise through (as a real receiver)
    const inBand = 0.577 * Math.sqrt((0.64 * REF_BW) / (this.ctx.sampleRate / 2));
    const level = (noise * SIGNAL * Math.SQRT1_2) / inBand;
    const src = this._track(this.ctx.createBufferSource());
    const g = this._track(this.ctx.createGain());
    src.buffer = this._noiseBuffer();
    src.loop = true;
    g.gain.setValueAtTime(0, from);
    g.gain.linearRampToValueAtTime(level, from + 0.3);
    g.gain.setValueAtTime(level, to - 0.3);
    g.gain.linearRampToValueAtTime(0, to);
    src.connect(g).connect(rx);
    src.start(from, Math.random() * 1.5);
    src.stop(to + 0.05);
  }

  /** Static crashes: short noise bursts at random (Poisson) times, sharp attack, decay 40–250 ms. */
  _qrn(rx, perMin, from, to, rng) {
    const crashes = [];
    if (perMin <= 0) return crashes;
    let t = from;
    for (;;) {
      t += -Math.log(Math.max(rng(), 1e-9)) * (60 / perMin);
      if (t >= to - 0.3) break;
      const src = this._track(this.ctx.createBufferSource());
      const g = this._track(this.ctx.createGain());
      src.buffer = this._noiseBuffer();
      const peak = 2 + rng() * 5; // wideband – the receiver filter keeps ~1/10 of it
      const decay = 0.04 + rng() * 0.21;
      crashes.push([t, peak, decay]);
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(peak, t + 0.002);
      g.gain.setTargetAtTime(0, t + 0.002, decay / 3);
      src.connect(g).connect(rx);
      src.start(t, rng() * 1.5);
      src.stop(t + decay * 2 + 0.05);
    }
    return crashes;
  }

  /**
   * Plays text as received on the band. p = bandParams(...). Returns {done: Promise, sec: duration}.
   * The main station has level 1; noise, static and QRM are relative to it.
   */
  play(text, p, rng = Math.random) {
    if (!this.player.ready) throw new Error('Audio is not unlocked');
    this.stop();
    this.player.stop();
    const ctx = this.ctx;
    this.player.master.gain.setValueAtTime(this.player.settings.volume ?? 0.7, ctx.currentTime);
    const t0 = ctx.currentTime + LEAD + NOISE_LEAD;
    const rx = this._receiver(p, ctx.currentTime);
    const { end } = this._station(rx, { text, wpm: p.wpm, freq: p.freq, level: SIGNAL, t0, p, qsb: p.qsb, qsbRate: p.qsbRate, rng });
    this._background(rx, p, t0 - NOISE_LEAD, end + NOISE_TAIL, rng);
    this._fadeOut(end + NOISE_TAIL);
    const sec = end + NOISE_TAIL - ctx.currentTime;
    const done = new Promise((resolve) => { this.timer = setTimeout(resolve, sec * 1000); });
    return { done, sec };
  }

  /** Noise, static and other stations between from and to (ctx s); nothing sounds after `to`. Returns {qrm, qrn} for maskChars. */
  _background(rx, p, from, to, rng) {
    this._noiseSource(rx, p.noise, from, to);
    const qrn = this._qrn(rx, p.qrn, from, to, rng);
    const qrm = [];
    // other stations: different tone (offset ±150–700 Hz), speed, level and fading, keyed for the whole duration
    for (let i = 0; i < Math.min(3, p.qrm); i++) {
      const off = (150 + rng() * 550) * (rng() < 0.5 ? -1 : 1);
      const wpm = Math.round(14 + rng() * 16);
      let t = from + rng() * 1.5;
      while (t < to - QRM_MIN_LEFT) {
        const msg = QRM_TEXTS[Math.floor(rng() * QRM_TEXTS.length)];
        const level = SIGNAL * (0.3 + rng() * 0.7);
        const st = this._station(rx, { text: msg, wpm, freq: p.freq + off, level, t0: t, until: to,
          p: { ...p, chirp: 0, drift: 0, hand: p.hand / 2 }, qsb: 0.4, qsbRate: 0.1 + rng() * 0.2, rng });
        qrm.push({ off, level, keys: st.keys, fade: st.fade });
        t = st.end + 0.6 + rng() * 2;
      }
    }
    return { qrm, qrn };
  }

  /**
   * M9 (U5): a copy-behind stream on the band – same contract as MorsePlayer.playStream (chars [{ch, w, end}], wordEnds,
   * start, toneEnd, done; performance.now ms). Gaps by Farnsworth (wpm, fwpm), word gap × gapX. The receiver is tuned
   * to the station; with toneVar every line has its own tone. M9 part 2: a masked character has mask 'f' | 'm' | 'n'.
   */
  playStream(items, p, { gapX = 1, fwpm = null } = {}, rng = Math.random) {
    if (!this.player.ready) throw new Error('Audio is not unlocked');
    this.stop();
    this.player.stop();
    const ctx = this.ctx;
    this.player.master.gain.setValueAtTime(this.player.settings.volume ?? 0.7, ctx.currentTime);
    const fw = fwpm || p.wpm;
    const cs = -WPM.charSpace(p.wpm, fw);
    const ws = -WPM.wordSpace(p.wpm, fw) * gapX;
    const tm = [];
    const marks = []; // {ch, w, f, i} – index of the first and the last element of the character in tm
    items.forEach((word, w) => {
      [...word].forEach((ch, i) => {
        const el = keyTimings(ch, p.wpm, p.hand, rng);
        while (el.length && el.at(-1) < 0) el.pop();
        const f = tm.length;
        tm.push(...el);
        marks.push({ ch, w, f, i: tm.length - 1 });
        if (i < word.length - 1) tm.push(cs);
      });
      tm.push(ws);
    });
    const freq = Math.round(p.freq + (p.toneVar ? (rng() * 2 - 1) * p.toneVar : 0));
    const q = { ...p, freq };
    const t0 = ctx.currentTime + LEAD + NOISE_LEAD;
    const rx = this._receiver(q, ctx.currentTime);
    const { end, ends, starts, fade } = this._station(rx, { tm, wpm: p.wpm, freq, level: SIGNAL, t0, p: q, qsb: p.qsb, qsbRate: p.qsbRate, rng });
    const bg = this._background(rx, q, t0 - NOISE_LEAD, end + NOISE_TAIL, rng);
    const mask = maskChars(marks.map((m) => ({ from: starts[m.f], to: ends[m.i] })),
      { noise: q.noise, filterBw: q.filterBw, freq, sampleRate: ctx.sampleRate, main: fade, ...bg });
    this._fadeOut(end + NOISE_TAIL);
    const off = this.player.ctxToPerf(t0) - t0 * 1000;
    const perf = (x) => off + x * 1000;
    const chars = marks.map((m, k) => ({ ch: m.ch, w: m.w, end: perf(ends[m.i]), ...(mask[k] ? { mask: mask[k] } : {}) }));
    const wordEnds = items.map((_, w) => chars.filter((c) => c.w === w).at(-1)?.end ?? perf(t0));
    const toneEnd = perf(end);
    return {
      chars, wordEnds, start: perf(t0), toneEnd, bandEnd: perf(end + NOISE_TAIL), freq,
      done: new Promise((resolve) => { this.timer = setTimeout(resolve, Math.max(0, toneEnd - performance.now())); }),
    };
  }

  /** Stops at once (pause, a new line/sample) – a short fade instead of a click, then the nodes are released. */
  stop() {
    clearTimeout(this.timer);
    const nodes = this.nodes;
    this.nodes = [];
    if (!nodes.length) return;
    const now = this.ctx.currentTime;
    const g = this.out?.gain;
    if (g) {
      if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(now);
      else { g.cancelScheduledValues(now); g.setValueAtTime(g.value, now); }
      g.linearRampToValueAtTime(0, now + STOP_FADE);
    }
    for (const n of nodes) {
      try { if (n.stop) n.stop(now + STOP_FADE + 0.01); } catch (e) { /* not started / already finished */ }
    }
    setTimeout(() => nodes.forEach((n) => { try { n.disconnect(); } catch (e) { /* already disconnected */ } }),
      (STOP_FADE + 0.05) * 1000);
    this.out = null;
  }
}

// 0.13.2 – CW room: a band that runs as long as the connection – noise / static / other stations in segments of
// LIVE_SEG s (overlapping, so the noise does not dip), and the other station as one oscillator keyed by the received
// time line. Only the listener's own choice shapes it (nothing is shared); the own sidetone does not go through it.
const LIVE_SEG = 30;
const LIVE_OVERLAP = 0.3;
const LIVE_AHEAD = 5;        // s – the next segment is prepared this long before the current one ends

export class LiveBand extends BandSound {
  /** p = bandParams(...) with freq = the tone of the other station. Returns false when the audio is locked. */
  start(p) {
    if (!this.player.ready) return false;
    this.stop();
    const ctx = this.ctx;
    this.p = p;
    this.player.master.gain.setValueAtTime(this.player.settings.volume ?? 0.7, ctx.currentTime);
    const t0 = ctx.currentTime + 0.05;
    this.rx = this._receiver(p, t0);
    const osc = this._track(ctx.createOscillator());
    const key = this._track(ctx.createGain());
    const fade = this._track(ctx.createGain());
    const lvl = this._track(ctx.createGain());
    osc.type = 'sine';
    osc.frequency.value = p.freq;
    key.gain.value = 0;
    lvl.gain.value = SIGNAL;
    fade.gain.value = 1 - p.qsb / 2;
    osc.connect(key).connect(fade).connect(lvl).connect(this.rx);
    if (p.qsb > 0) {
      for (const [rate, share] of [[p.qsbRate, 0.7], [p.qsbRate * 0.37 + 0.013, 0.3]]) {
        const lfo = this._track(ctx.createOscillator());
        const depth = this._track(ctx.createGain());
        lfo.frequency.value = rate;
        depth.gain.value = (p.qsb / 2) * share;
        lfo.connect(depth).connect(fade.gain);
        lfo.start(t0);
      }
    }
    osc.start(t0);
    this.keyGain = key.gain;
    this.segEnd = t0 + LIVE_OVERLAP;
    this._segment();
    return true;
  }

  _segment() {
    if (!this.rx) return;
    const ctx = this.ctx;
    const from = Math.max(ctx.currentTime + 0.05, this.segEnd - LIVE_OVERLAP);
    const to = from + LIVE_SEG;
    const n0 = this.nodes.length;
    this._background(this.rx, this.p, from, to, Math.random);
    const seg = new Set(this.nodes.slice(n0));
    this.segEnd = to;
    // nodes of a finished segment are released (a connection may last long)
    setTimeout(() => {
      this.nodes = this.nodes.filter((n) => !seg.has(n));
      seg.forEach((n) => { try { n.disconnect(); } catch (e) { /* already disconnected */ } });
    }, (to - ctx.currentTime + 1) * 1000);
    this.timer = setTimeout(() => this._segment(), Math.max(1, to - LIVE_AHEAD - ctx.currentTime) * 1000);
  }

  /** One element of the other station from t0 to t1 (audio-clock s). */
  keyElement(t0, t1) {
    if (!this.keyGain) return;
    const now = this.ctx.currentTime;
    const a = Math.max(t0, now + 0.002);
    if (t1 - a < 0.005) return;
    const r = Math.min(Math.max(0.0008, this.p.rise / 1000), (t1 - a) / 3);
    const g = this.keyGain;
    g.setValueAtTime(0, a);
    g.linearRampToValueAtTime(1, a + r);
    g.setValueAtTime(1, t1 - r);
    g.linearRampToValueAtTime(0, t1);
  }

  /** Silences the other station at once (hang up, a lost race for the channel). */
  silence() {
    if (!this.keyGain) return;
    const now = this.ctx.currentTime;
    if (this.keyGain.cancelAndHoldAtTime) this.keyGain.cancelAndHoldAtTime(now);
    else this.keyGain.cancelScheduledValues(now);
    this.keyGain.setTargetAtTime(0, now, 0.003);
  }

  stop() {
    super.stop();
    this.rx = null;
    this.keyGain = null;
  }
}
