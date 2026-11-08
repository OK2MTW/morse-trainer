// SPDX-License-Identifier: EUPL-1.2
// VK (0.11.0, docs/spec-klic.md A-10): keyer logic – pure, without DOM and sound, ported to tests/keyer.py.
// Decoding of the keyed tones: decoder.js (D3, 0.11.3).
// The driver (keyerui.js) feeds paddle presses/releases and asks for the next element at the end of each element's
// trailing gap; it plays the elements in the audio clock.
//
// Key types (stored values, not translated):
//   iambicB  – two paddles; squeeze = alternating elements; releasing both during an element adds the opposite one
//   iambicA  – the same without the extra element (stops after the current one)
//   single   – single-lever paddle: the last pressed side wins, no alternation
//   bug      – semi-automatic: dots automatic (dot side held), dashes by hand (tone while the dash side is held)
//   straight – straight key: the tone follows the contact (dot side) – timing by the operator
// Memory (A-10): a paddle pressed while an element or its gap is running is remembered and sent next, even if it was
// released meanwhile (dot / dash memory). Not for bug and straight key.

export const KEY_TYPES = ['iambicB', 'iambicA', 'single', 'bug', 'straight'];
export const DOT = '.';
export const DASH = '-';
export const KEYER_WPM_MIN = 5;
export const KEYER_WPM_MAX = 40;
export const RATIO_MIN = 2.8;
export const RATIO_MAX = 3.5;

/** Length of one unit (dot) in ms at a given speed (PARIS: 50 units per word). */
export const unitMs = (wpm) => 1200 / wpm;

const sideOf = (el) => (el === DOT ? 'dot' : 'dash');
const opposite = (el) => (el === DOT ? DASH : DOT);

/** Types where the app generates the elements (the rest is keyed by hand – the tone follows the contact). */
export const isAutomatic = (type) => type !== 'straight';
/** Which side keys the tone by hand: straight key = dot contact, bug = dash side. null = none. */
export function manualSide(type) {
  if (type === 'straight') return 'dot';
  if (type === 'bug') return 'dash';
  return null;
}

export class Keyer {
  constructor({ type = 'iambicB', wpm = 18, ratio = 3 } = {}) {
    this.type = KEY_TYPES.includes(type) ? type : 'iambicB';
    this.wpm = Math.min(KEYER_WPM_MAX, Math.max(KEYER_WPM_MIN, wpm));
    this.ratio = Math.min(RATIO_MAX, Math.max(RATIO_MIN, ratio));
    this.reset();
  }

  reset() {
    this.down = { dot: false, dash: false };
    this.mem = { dot: false, dash: false };
    this.order = [];      // sides held, the latest pressed last
    this.last = null;     // last element sent (alternation)
    this.busy = false;    // an element or its trailing gap is running
    this.squeeze = false; // both paddles held at some moment of the current element (iambic B)
  }

  get unit() { return unitMs(this.wpm); }
  /** Duration of an element in ms (the gap after it is always one unit). */
  elementMs(el) { return el === DASH ? this.unit * this.ratio : this.unit; }

  /** Paddle pressed. Returns true when the keyer is idle and the driver should ask next() right away. */
  press(side) {
    if (this.down[side]) return false;
    this.down[side] = true;
    this.order.push(side);
    if (this.down.dot && this.down.dash) this.squeeze = true;
    if (this.busy && this.type !== 'bug' && this.type !== 'straight') this.mem[side] = true;
    return !this.busy && isAutomatic(this.type) && (this.type !== 'bug' || side === 'dot');
  }

  release(side) {
    if (!this.down[side]) return;
    this.down[side] = false;
    this.order = this.order.filter((s) => s !== side);
  }

  /** Releases everything (focus lost, page hidden). */
  releaseAll() {
    this.reset();
  }

  /**
   * The next element (DOT / DASH) or null = the keyer goes idle. Called when idle after a press, and at the end of
   * each element's trailing gap.
   */
  next() {
    const t = this.type;
    let el = null;
    if (t === 'bug') {
      el = this.down.dot ? DOT : null;
    } else if (t !== 'straight') {
      const dot = this.down.dot || this.mem.dot;
      const dash = this.down.dash || this.mem.dash;
      if (dot && dash) {
        if (t === 'single') {
          // a tap during the element (memory) is the newer intention; otherwise the latest held side
          const held = this.order.at(-1);
          if (this.mem.dot !== this.mem.dash) el = this.mem.dot ? DOT : DASH;
          else el = held === 'dash' ? DASH : DOT;
        } else if (this.last) {
          el = opposite(this.last);
        } else {
          el = this.order[0] === 'dash' ? DASH : DOT;
        }
      } else if (dot) {
        el = DOT;
      } else if (dash) {
        el = DASH;
      } else if (t === 'iambicB' && this.squeeze && this.last) {
        el = opposite(this.last); // B: both released during a squeezed element → one more, the opposite one
      }
    }
    if (el) {
      this.mem[sideOf(el)] = false;
      this.last = el;
      this.busy = true;
      this.squeeze = this.down.dot && this.down.dash;
    } else {
      this.busy = false;
      this.last = null;
      this.squeeze = false;
      this.mem = { dot: false, dash: false };
    }
    return el;
  }
}
