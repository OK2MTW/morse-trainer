// SPDX-License-Identifier: EUPL-1.2
// 1.0.2 (Martin): automatic recording of keying for tuning the decoder – no transcript needed. Segments of the own
// keying (key page: free sending + exercise tasks with their target; virtual operator: overs with what the decoder and
// the VO read) go to the debug trace (kind 'klic', end.auto = the source) after AUTO_IDLE_MS of silence, when the
// segment is full, or when the page is left. Only for accounts with the debug trace on (as all traces; 180 days).
import { traceOn, tracePush, flushTrace } from './trace.js';

export const AUTO_IDLE_MS = 20000;   // a segment ends after 20 s without keying …
export const AUTO_MAX_TONES = 1500;  // … or when it has this many elements (~50 kB)
export const AUTO_MIN_TONES = 12;    // shorter free keying is not worth a record (tasks / overs always are)
export const AUTO_MAX_ITEMS = 40;    // tasks or overs in one segment

const r1 = (x) => Math.round(x * 10) / 10;

export class KeyAuto {
  /** source = 'key' / 'vo'; info() = {type, wpm, …} of the moment; decode(tones) = the decoder's text. */
  constructor(source, info, decode) {
    this.source = source;
    this.info = info;
    this.decode = decode;
    this.tones = [];
    this.items = [];
    this.timer = null;
  }

  _arm() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), AUTO_IDLE_MS);
  }

  /** One element of the own keying {start, end, el?} (ms, event clock). */
  tone(tn) {
    if (!traceOn()) return;
    this.tones.push({ start: tn.start, end: tn.end, ...(tn.el ? { el: tn.el } : {}) });
    if (this.tones.length >= AUTO_MAX_TONES) this.flush(); else this._arm();
  }

  /** A finished task / over: {target?, text, read?, tones: [{s, e}]} – the tones are stored with it. */
  item(rec) {
    if (!traceOn()) return;
    this.items.push(rec);
    if (this.items.length >= AUTO_MAX_ITEMS) this.flush(); else this._arm();
  }

  /** Ends the segment: a record when there is enough, then a background send. */
  flush() {
    clearTimeout(this.timer);
    this.timer = null;
    const tones = this.tones.sort((a, b) => a.start - b.start);
    const items = this.items;
    this.tones = [];
    this.items = [];
    if (!traceOn() || (tones.length < AUTO_MIN_TONES && !items.length)) return;
    const t0 = tones.length ? tones[0].start : 0;
    let text = '';
    try { text = tones.length ? this.decode(tones) : ''; } catch (e) { text = ''; }
    const ok = tracePush('klic', { end: {
      auto: this.source, ...this.info(), meant: '', text, ua: navigator.userAgent.slice(0, 200),
      tones: tones.map((tn) => ({ s: r1(tn.start - t0), e: r1(tn.end - t0), ...(tn.el ? { el: tn.el } : {}) })),
      ex: items,
    } });
    if (ok) flushTrace().catch(() => { /* offline – stays in the queue */ });
  }
}
