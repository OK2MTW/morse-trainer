// SPDX-License-Identifier: EUPL-1.2
// Přehrávač Morse tónů s přesným časováním pro měření reakční doby (TTR).
// Převod textu → Morse a výpočet časování dělá knihovna morse-pro (EUPL-1.2),
// zvuk generujeme sami: jeden trvalý AudioContext, měkké hrany tónu (bez cvakání),
// a převod času zvukové karty na performance.now() včetně výstupní latence.
import MorseCW from '../vendor/morse-pro/morse-pro-cw.js';
import * as WPM from '../vendor/morse-pro/morse-pro-wpm.js';

const RAMP = 0.005; // s – náběh/doběh tónu, odstraní cvakání
// Rezerva plánování: tón se plánuje aspoň tolik dopředu. Při kratší rezervě (dřív 50 ms) Android
// při zaneprázdněném hlavním vláknu zmeškal začátek znaku a „dohnal“ ho → znak zněl zrychleně.
// Reakční dobu to neovlivní – měří se od skutečného konce tónu (toneEnd).
const LEAD = 0.15;

export class MorsePlayer {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.settings = { wpm: 20, fwpm: 20, freq: 600, volume: 0.7 };
    this._active = [];
    this.keep = false;
    this._keep = null;
  }

  get ready() { return this.ctx !== null && this.ctx.state === 'running'; }

  // Musí se zavolat z obsluhy kliknutí/klepnutí (pravidla autoplay v prohlížečích).
  async unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC({ latencyHint: 'interactive' });
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
    }
    const wasRunning = this.ctx.state === 'running';
    // 'suspended' i Safari 'interrupted' (hovor, zhasnutá obrazovka) → znovu spustit
    if (!wasRunning) { try { await this.ctx.resume(); } catch (e) { /* zkusí se příště */ } }
    if (!wasRunning && this.ctx.state === 'running') this.warmUp();
    if (this.keep) this.keepAlive(true);
    return this.ctx.state === 'running';
  }

  // Zahřátí: Android po chvíli ticha uspí zvukový výstup a první tón pak usekne/zrychlí.
  // Prázdný (nulový) buffer některé telefony za zvuk nepovažují, proto hrajeme neslyšitelný
  // tón (40 Hz, −66 dB) – výstup se rozběhne dřív, než zazní skutečný znak.
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

  // 0.8.5 (validace #3): Bluetooth sluchátka a Android uspí přenos po chvíli ticha a první tón po přestávce
  // (seznámení → rozlišování → lekce) pak usekne. Během tréninku proto trvale hraje neslyšitelný tón
  // jako při zahřátí – linka nikdy neusne. Mimo trénink se vypne (baterie).
  keepAlive(on) {
    this.keep = on;
    if (!on) {
      if (this._keep) { try { this._keep.stop(); } catch (e) { /* už skončil */ } this._keep = null; }
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

  // Čas zvukového kontextu (s) → čas performance.now() (ms), kdy to skutečně zazní.
  ctxToPerf(t) {
    const ts = this.ctx.getOutputTimestamp ? this.ctx.getOutputTimestamp() : null;
    // Po uspání/probuzení zvuku umí prohlížeč vrátit zastaralé razítko → nesmyslný konec tónu
    // (lekce pak hrála „moc brzo“ a TTR byla špatně). Razítko bereme jen čerstvé a konzistentní.
    const now = performance.now();
    if (ts && ts.performanceTime > 0 && now - ts.performanceTime < 1500 && now - ts.performanceTime > -50
        && Math.abs(this.ctx.currentTime - ts.contextTime) < 1.5) {
      return ts.performanceTime + (t - ts.contextTime) * 1000;
    }
    const lat = (this.ctx.outputLatency || this.ctx.baseLatency || 0);
    return now + (t - this.ctx.currentTime + lat) * 1000;
  }

  // Vrátí časování v ms (kladné = tón, záporné = ticho) – přímo z morse-pro.
  timings(text) {
    const cw = new MorseCW(true, this.settings.wpm, this.settings.fwpm);
    cw.translate(text, false);
    return cw.getTimings();
  }

  // Zastaví hrající znak měkce (5 ms doběh) – tvrdé utnutí cvaká a zní jako „kolize“.
  stop() {
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    for (const { osc, gain } of this._active) {
      try {
        const g = gain.gain;
        if (g.cancelAndHoldAtTime) g.cancelAndHoldAtTime(now); else g.cancelScheduledValues(now);
        g.setTargetAtTime(0, now, RAMP / 3);
        osc.stop(now + 4 * RAMP);
      } catch (e) { /* už skončil */ }
    }
    this._active = [];
  }

  /**
   * Přehraje text. Vrací hned (synchronně) časy v performance.now() ms:
   *   start = začátek prvního tónu, toneEnd = konec posledního tónu,
   *   done = Promise, která se splní ve chvíli konce posledního tónu.
   */
  play(text, delay = LEAD) {
    if (!this.ready) throw new Error('Zvuk není odemčený');
    this.stop();
    const { freq, volume } = this.settings;
    const timings = this.timings(text); // výpočet před určením startu, ať nezkracuje rezervu
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
   * M7 – proud položek (skupiny/slova) bez čekání na odpověď. Mezery mezi znaky podle Farnsworthu (wpm, fwpm),
   * mezera mezi položkami = normální mezera mezi slovy × gapX. Vrací hned (performance.now ms):
   *   chars = [{ch, w, end}] (end = konec posledního tónu znaku), wordEnds = konec posledního tónu položky,
   *   start, toneEnd, done (Promise na konec posledního tónu).
   */
  playStream(items, { gapX = 1, delay = LEAD } = {}) {
    if (!this.ready) throw new Error('Zvuk není odemčený');
    this.stop();
    const { wpm, fwpm, freq, volume } = this.settings;
    const cs = WPM.charSpace(wpm, fwpm) / 1000;
    const ws = (WPM.wordSpace(wpm, fwpm) * gapX) / 1000;
    const cache = new Map();
    const tones = (ch) => {
      if (!cache.has(ch)) {
        const tm = this.timings(ch);
        while (tm.length && tm.at(-1) < 0) tm.pop(); // bez koncové mezery – mezery skládáme sami
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
    const off = this.ctxToPerf(t0) - t0 * 1000; // jeden převod pro celý proud (konzistentní časy)
    const perf = (x) => off + x * 1000;
    const toneEnd = perf(lastToneEnd);
    return {
      chars: raw.map((c) => ({ ...c, end: perf(c.end) })), wordEnds: wordRaw.map(perf),
      start: perf(t0), toneEnd,
      done: new Promise((resolve) => setTimeout(resolve, Math.max(0, toneEnd - performance.now()))),
    };
  }
}
