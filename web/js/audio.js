// SPDX-License-Identifier: EUPL-1.2
// Morse tone player with precise timing for measuring the reaction time (TTR).
// Text → Morse conversion and timing are done by the morse-pro library (EUPL-1.2),
// the sound is generated here: one persistent AudioContext, soft tone edges (no clicks),
// and conversion of the sound card clock to performance.now() including the output latency.
import MorseCW from '../vendor/morse-pro/morse-pro-cw.js';
import * as WPM from '../vendor/morse-pro/morse-pro-wpm.js';

const RAMP = 0.005; // s – tone rise/fall, removes clicks
// Scheduling margin: a tone is scheduled at least this far ahead. With a shorter margin (formerly 50 ms) Android
// missed the start of a character when the main thread was busy and "caught up" → the character sounded faster.
// It does not affect the reaction time – that is measured from the real end of the tone (toneEnd).
const LEAD = 0.15;

export class MorsePlayer {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.settings = { wpm: 20, fwpm: 20, freq: 600, volume: 0.7 };
    this._active = [];
    this.keep = false;
    this._keep = null;
    this._side = null; // VK sidetone {osc, gain}
  }

  get ready() { return this.ctx !== null && this.ctx.state === 'running'; }

  // Must be called from a click/tap handler (browser autoplay rules).
  async unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC({ latencyHint: 'interactive' });
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
    }
    const wasRunning = this.ctx.state === 'running';
    // 'suspended' and Safari 'interrupted' (call, screen off) → start again
    if (!wasRunning) { try { await this.ctx.resume(); } catch (e) { /* retried next time */ } }
    if (!wasRunning && this.ctx.state === 'running') this.warmUp();
    if (this.keep) this.keepAlive(true);
    return this.ctx.state === 'running';
  }

  // Warm-up: after a while of silence Android suspends the audio output and then cuts/speeds up the first tone.
  // Some phones do not consider an empty (zero) buffer as sound, so we play an inaudible
  // tone (40 Hz, −66 dB) – the output starts before the real character sounds.
  warmUp(sec = 0.5) {
    if (!this.ready) return;
    const t0 = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.frequency.value = 40;
    g.gain.value = 0.0005;
    osc.connect(g).connect(this.ctx.destination);
    osc.start(t0);
    osc.stop(t0 + sec);
  }

  // 0.8.5 (validation #3): Bluetooth headphones and Android suspend the link after a while of silence and then cut the
  // first tone after a gap (introduction → discrimination → lesson). So during training an inaudible tone plays
  // continuously as in the warm-up – the link never sleeps. Outside training it is switched off (battery).
  keepAlive(on) {
    this.keep = on;
    if (!on) {
      if (this._keep) { try { this._keep.stop(); } catch (e) { /* already finished */ } this._keep = null; }
      return;
    }
    if (this._keep || !this.ready) return;
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.frequency.value = 40;
    g.gain.value = 0.0005;
    osc.connect(g).connect(this.ctx.destination);
    osc.start();
    this._keep = osc;
  }

  latencyInfo() {
    if (!this.ctx) return null;
    return {
      base: Math.round((this.ctx.baseLatency || 0) * 1000),
      output: Math.round((this.ctx.outputLatency || 0) * 1000),
      sampleRate: this.ctx.sampleRate,
    };
  }

  // Audio context time (s) → performance.now() time (ms) when it actually sounds.
  ctxToPerf(t) {
    const ts = this.ctx.getOutputTimestamp ? this.ctx.getOutputTimestamp() : null;
    // After audio suspend/resume the browser may return a stale timestamp → a nonsensical tone end
    // (the lesson then played "too early" and TTR was wrong). Only a fresh and consistent timestamp is used.
    const now = performance.now();
    if (ts && ts.performanceTime > 0 && now - ts.performanceTime < 1500 && now - ts.performanceTime > -50
        && Math.abs(this.ctx.currentTime - ts.contextTime) < 1.5) {
      return ts.performanceTime + (t - ts.contextTime) * 1000;
    }
    const lat = (this.ctx.outputLatency || this.ctx.baseLatency || 0);
    return now + (t - this.ctx.currentTime + lat) * 1000;
  }

  // VK (0.11.0, spec A-12): sidetone for keying – one persistent oscillator whose gain is keyed with 5 ms edges, so
  // a tone starts within milliseconds (no LEAD margin as in playback). Times are audio-clock seconds.
  _sidetone() {
    if (!this._side) {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      gain.gain.value = 0;
      osc.connect(gain).connect(this.master);
      osc.start();
      this._side = { osc, gain };
    }
    const now = this.ctx.currentTime;
    this._side.osc.frequency.setValueAtTime(this.settings.freq, now);
    this.master.gain.setValueAtTime(this.settings.volume, now);
    return this._side.gain.gain;
  }

  /** A generated element (keyer): tone from t0 to t1. */
  sidetoneElement(t0, t1) {
    if (!this.ready) return;
    const g = this._sidetone();
    g.setValueAtTime(0, t0);
    g.linearRampToValueAtTime(1, t0 + RAMP);
    g.setValueAtTime(1, Math.max(t0 + RAMP, t1 - RAMP));
    g.linearRampToValueAtTime(0, t1);
  }

  /** Keying by hand (straight key, bug dashes): the tone on / off right now. */
  sidetoneKey(on) {
    if (!this.ready) return;
    const g = this._sidetone();
    const now = this.ctx.currentTime;
    if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(now); else g.cancelScheduledValues(now);
    g.setTargetAtTime(on ? 1 : 0, now, RAMP / 3);
  }

  /** Leaving the key page: silence and free the oscillator. */
  sidetoneOff() {
    if (!this._side) return;
    const { osc, gain } = this._side;
    this._side = null;
    try {
      const now = this.ctx.currentTime;
      gain.gain.cancelScheduledValues(now);
      gain.gain.setTargetAtTime(0, now, RAMP / 3);
      osc.stop(now + 4 * RAMP);
    } catch (e) { /* already stopped */ }
  }

  // Returns the timing in ms (positive = tone, negative = silence) – directly from morse-pro.
  timings(text) {
    const cw = new MorseCW(true, this.settings.wpm, this.settings.fwpm);
    cw.translate(text, false);
    return cw.getTimings();
  }

  // Stops the playing character softly (5 ms fall) – a hard cut clicks and sounds like a "collision".
  stop() {
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    for (const { osc, gain } of this._active) {
      try {
        const g = gain.gain;
        if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(now); else g.cancelScheduledValues(now);
        g.setTargetAtTime(0, now, RAMP / 3);
        osc.stop(now + 4 * RAMP);
      } catch (e) { /* already finished */ }
    }
    this._active = [];
  }

  /**
   * Plays text. Returns at once (synchronously) times in performance.now() ms:
   *   start = start of the first tone, toneEnd = end of the last tone,
   *   done = a Promise resolved at the end of the last tone.
   */
  play(text, delay = LEAD) {
    if (!this.ready) throw new Error('Audio is not unlocked');
    this.stop();
    const { freq, volume } = this.settings;
    const timings = this.timings(text); // computed before choosing the start so that it does not shorten the margin
    const t0 = this.ctx.currentTime + Math.max(delay, LEAD);
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t0);
    osc.connect(gain).connect(this.master);
    this.master.gain.setValueAtTime(volume, this.ctx.currentTime);

    let t = t0;
    let lastToneEnd = t0;
    for (const ms of timings) {
      const d = Math.abs(ms) / 1000;
      if (ms > 0) {
        gain.gain.setValueAtTime(0, t);
        gain.gain.linearRampToValueAtTime(1, t + RAMP);
        gain.gain.setValueAtTime(1, t + d - RAMP);
        gain.gain.linearRampToValueAtTime(0, t + d);
        lastToneEnd = t + d;
      }
      t += d;
    }
    osc.start(t0);
    osc.stop(lastToneEnd + 0.02);
    this._active.push({ osc, gain });
    osc.onended = () => { this._active = this._active.filter((n) => n.osc !== osc); };

    const start = this.ctxToPerf(t0);
    const toneEnd = this.ctxToPerf(lastToneEnd);
    const done = new Promise((resolve) => setTimeout(resolve, Math.max(0, toneEnd - performance.now())));
    return { start, toneEnd, done };
  }

  /**
   * M7 – a stream of items (groups/words) without waiting for an answer. Gaps between characters by Farnsworth (wpm, fwpm),
   * the gap between items = the normal word gap × gapX. Returns at once (performance.now ms):
   *   chars = [{ch, w, end}] (end = end of the last tone of the character), wordEnds = end of the last tone of the item,
   *   start, toneEnd, done (a Promise for the end of the last tone).
   */
  playStream(items, { gapX = 1, delay = LEAD } = {}) {
    if (!this.ready) throw new Error('Audio is not unlocked');
    this.stop();
    const { wpm, fwpm, freq, volume } = this.settings;
    const cs = WPM.charSpace(wpm, fwpm) / 1000;
    const ws = (WPM.wordSpace(wpm, fwpm) * gapX) / 1000;
    const cache = new Map();
    const tones = (ch) => {
      if (!cache.has(ch)) {
        const tm = this.timings(ch);
        while (tm.length && tm.at(-1) < 0) tm.pop(); // without the trailing gap – gaps are composed here
        cache.set(ch, tm);
      }
      return cache.get(ch);
    };
    const t0 = this.ctx.currentTime + Math.max(delay, LEAD);
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t0);
    osc.connect(gain).connect(this.master);
    this.master.gain.setValueAtTime(volume, this.ctx.currentTime);
    let t = t0;
    let lastToneEnd = t0;
    const raw = [];
    const wordRaw = [];
    items.forEach((word, w) => {
      [...word].forEach((ch, i) => {
        for (const ms of tones(ch)) {
          const d = Math.abs(ms) / 1000;
          if (ms > 0) {
            gain.gain.setValueAtTime(0, t);
            gain.gain.linearRampToValueAtTime(1, t + RAMP);
            gain.gain.setValueAtTime(1, t + d - RAMP);
            gain.gain.linearRampToValueAtTime(0, t + d);
            lastToneEnd = t + d;
          }
          t += d;
        }
        raw.push({ ch, w, end: lastToneEnd });
        if (i < word.length - 1) t += cs;
      });
      wordRaw.push(lastToneEnd);
      t += ws;
    });
    osc.start(t0);
    osc.stop(lastToneEnd + 0.02);
    this._active.push({ osc, gain });
    osc.onended = () => { this._active = this._active.filter((n) => n.osc !== osc); };
    const off = this.ctxToPerf(t0) - t0 * 1000; // one conversion for the whole stream (consistent times)
    const perf = (x) => off + x * 1000;
    const toneEnd = perf(lastToneEnd);
    return {
      chars: raw.map((c) => ({ ...c, end: perf(c.end) })), wordEnds: wordRaw.map(perf),
      start: perf(t0), toneEnd,
      done: new Promise((resolve) => setTimeout(resolve, Math.max(0, toneEnd - performance.now()))),
    };
  }
}
