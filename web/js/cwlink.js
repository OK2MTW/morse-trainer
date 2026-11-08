// SPDX-License-Identifier: EUPL-1.2
// 0.13.2 – CW room channel timing (pure logic, no DOM / sound; Python port tests/cwlink.py).
//
// The sender keys an "over": element times in ms from its first key down, sent in batches every BATCH_MS. The over
// ends after a silence of max(END_MIN_MS, END_DOTS dots). The receiver plays the time line with a reserve: the first
// element of an over sounds `buffer` ms after it arrived; every later element at the same offset (the rhythm of the
// hand stays). A batch that comes too late shifts the rest of the over (a longer pause, the rhythm inside stays) and
// the reserve grows for the next overs by BUFFER_STEP_MS (max BUFFER_MAX_MS); after CLEAN_OVERS overs without a late
// batch it shrinks again. The delay key → sound is estimated from the age of the over at the server and the request
// round trip (no common clock is needed).
export const BATCH_MS = 250;          // sender: one batch per 250 ms (≤ 4 requests/s)
export const BATCH_SLOW_MS = 500;     // after 429 (public nginx limit before the CW zone is installed)
export const POLL_MS = 1000;          // room state (list, knocks) when not connected / while I key
export const POLL_RX_MS = 250;        // connected and listening
export const POLL_TX_MS = 2000;       // while I key an over (the room state is not urgent then)
export const BUFFER_MS = 500;         // receiver reserve
export const BUFFER_STEP_MS = 200;
export const BUFFER_MAX_MS = 1400;
export const CLEAN_OVERS = 3;
export const LATE_MARGIN_MS = 30;     // an element must be scheduled at least this far ahead of now
export const END_MIN_MS = 1000;       // end of an over: silence ≥ max(1 s, 7 dots)
export const END_DOTS = 7;
export const OVER_SPLIT_MS = 110000;  // the server takes an over of ≤ 2 min – a longer one continues as a new over
export const DELAY_KEEP = 10;         // the shown average delay = the last 10 overs

export const overEndMs = (dotMs) => Math.max(END_MIN_MS, END_DOTS * dotMs);

/** Sender: one over. t0 = local time (ms) of the first key down. */
export class TxOver {
  constructor(t0) {
    this.t0 = t0;
    this.els = [];      // [[start, end], …] ms from t0, increasing, never overlapping
    this.sent = 0;      // how many elements went to the server
    this.lastEnd = t0;  // local time of the end of the last element
    this.id = 0;        // over id from the server (0 = not confirmed yet)
  }

  /** A keyed element (local ms). Returns false when it would overlap the previous one beyond repair. */
  add(start, end) {
    const prev = this.els.length ? this.els[this.els.length - 1][1] : 0;
    const s = Math.max(prev, Math.round(start - this.t0));
    const e = Math.round(end - this.t0);
    if (e <= s) return false;
    this.els.push([s, e]);
    this.lastEnd = Math.max(this.lastEnd, end);
    return true;
  }

  /** Elements not sent yet that have started by `now` (automatic elements are known a few ms ahead). */
  batch(now) {
    const out = [];
    while (this.sent < this.els.length && this.els[this.sent][0] + this.t0 <= now) out.push(this.els[this.sent++]);
    return out;
  }

  /** Everything not sent yet (the end of the over). */
  rest() {
    const out = this.els.slice(this.sent);
    this.sent = this.els.length;
    return out;
  }

  /** Silence long enough to end the over (keyDown = a key / paddle is held right now). */
  silent(now, dotMs, keyDown) {
    return !keyDown && now - this.lastEnd >= overEndMs(dotMs);
  }

  /** Too long for one over at the server. */
  tooLong(now) { return now - this.t0 >= OVER_SPLIT_MS; }
}

/** Receiver: plays the overs of the other station. All times are local ms (performance.now). */
export class RxPlayout {
  constructor() {
    this.buffer = BUFFER_MS;
    this.clean = 0;       // overs without a late batch in a row
    this.cur = null;      // {id, base, late, n, end, lastEnd, delay}
    this.lastId = 0;      // the last over played to the end
    this.delays = [];     // estimated delay key → sound of the last overs (ms)
  }

  /** What to ask the server for: the over I am on and how many of its elements I have, the last one played out. */
  query() {
    return this.cur ? { over: this.cur.id, n: this.cur.n, done: this.lastId }
      : { over: this.lastId + 1, n: 0, done: this.lastId };
  }

  /**
   * New elements of over `id` (els = [[s, e]] ms from its first key down), end = the over has ended at the sender.
   * now = arrival (local ms), age = ms since the over started at the server (or null), rtt = the request round trip.
   * Returns [[start, end]] in local ms to play.
   */
  receive(id, els, end, now, age = null, rtt = 0) {
    if (id <= this.lastId) return [];
    if (this.cur && this.cur.id !== id) this.finish();
    if (!this.cur) this.cur = { id, base: null, late: false, n: 0, end: false, lastEnd: now, delay: null };
    const o = this.cur;
    const out = [];
    for (const [s, e] of els) {
      if (o.base === null) o.base = now + this.buffer - s;
      let at = o.base + s;
      if (at < now + LATE_MARGIN_MS) {   // too late: shift the rest of the over, keep the rhythm
        o.base += now + LATE_MARGIN_MS - at;
        o.late = true;
        at = o.base + s;
      }
      out.push([at, o.base + e]);
      o.lastEnd = o.base + e;
      o.n += 1;
    }
    // the sender pressed the first key ≈ now − age − rtt (age at the server + the way up ≈ the way down ≈ rtt / 2)
    if (age !== null && o.base !== null) o.delay = Math.round(o.base - (now - age - rtt));
    if (end) o.end = true;
    return out;
  }

  /** The current over has ended at the sender and its last element has sounded. */
  playedOut(now) {
    const o = this.cur;
    return !!o && o.end && (o.base === null || now >= o.lastEnd);
  }

  /** Something of the other station is still to be played (or the over is still open). */
  busy(now) { return !!this.cur && !this.playedOut(now); }

  /** Closes the current over: adapts the reserve and records the delay. Returns its id (0 = none). */
  finish() {
    const o = this.cur;
    if (!o) return 0;
    this.cur = null;
    this.lastId = Math.max(this.lastId, o.id);
    if (o.base === null) return o.id;   // nothing arrived (an empty over)
    if (o.late) {
      this.buffer = Math.min(BUFFER_MAX_MS, this.buffer + BUFFER_STEP_MS);
      this.clean = 0;
    } else {
      this.clean += 1;
      if (this.clean >= CLEAN_OVERS && this.buffer > BUFFER_MS) {
        this.buffer = Math.max(BUFFER_MS, this.buffer - BUFFER_STEP_MS);
        this.clean = 0;
      }
    }
    if (o.delay !== null) {
      this.delays.push(o.delay);
      if (this.delays.length > DELAY_KEEP) this.delays.shift();
    }
    return o.id;
  }

  /** Average delay key → sound of the last overs (ms) or null. */
  avgDelay() {
    if (!this.delays.length) return null;
    return Math.round(this.delays.reduce((a, b) => a + b, 0) / this.delays.length);
  }
}
