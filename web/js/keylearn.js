// SPDX-License-Identifier: EUPL-1.2
// 0.13.11: learning the key mapping with confirmation (docs/spec-klic.md A-03) – pure state machine without DOM,
// ported to tests/keylearn.py. One step captures ONE gesture: it starts with the first key pressed and ends when
// everything is released and LEARN_QUIET_MS of silence follows. A USB key sends several events for one paddle press
// (mode C: Ctrl + F13 in the same millisecond; mode B: a held paddle = a series of F13), so the other keys of the
// gesture are ignored. Then the captured key waits for confirmation (button / Enter); Esc cancels the learning.
// The same key for two steps is refused with an explanation (no silent fallback to the defaults).
//
// Phases: wait (for the first key) → gesture → confirm (code + error) → the next step … → done | cancel.

export const LEARN_QUIET_MS = 600;   // a gesture ends after this much silence with nothing held
export const LEARN_SAME_MS = 5;      // keys pressed within 5 ms of the first one count as pressed together
export const LEARN_SKIP = ['Escape', 'Enter', 'NumpadEnter', 'Tab'];   // never learned (they control the learning)

/** Modifier keys (a HW key in mode C reports the paddles as Left / Right Ctrl). */
export const isModifier = (code) => /^(Control|Shift|Alt|Meta)/.test(code);

export class KeyLearn {
  /** steps = ['dot', 'dash'] (paddles / keys of the app keyer) or ['stream'] (HW keyer). */
  constructor(steps) {
    this.steps = steps;
    this.i = 0;
    this.result = {};
    this.phase = 'wait';
    this.held = new Set();
    this.gesture = [];
    this.quietAt = null;
    this.code = null;
    this.error = null;
  }

  get step() { return this.steps[this.i]; }
  get active() { return this.phase !== 'done' && this.phase !== 'cancel'; }

  /** One keydown / keyup. Returns true while the learning is active (the caller swallows the key). */
  key(code, down, ts, repeat = false) {
    if (!this.active) return false;
    if (down && code === 'Escape') { this.phase = 'cancel'; return true; }
    if (this.phase === 'confirm') {
      if (down && !repeat && (code === 'Enter' || code === 'NumpadEnter')) {
        if (this.error) this.retry(); else this.confirm();
      }
      return true;   // the HW may keep sending – ignored until confirmed
    }
    if (LEARN_SKIP.includes(code)) return true;
    if (down) {
      if (repeat || this.held.has(code)) return true;   // autorepeat of the OS (also unmarked, Windows Ctrl)
      if (this.phase === 'wait') { this.phase = 'gesture'; this.gesture = []; }
      this.held.add(code);
      this.gesture.push({ code, ts });
      this.quietAt = null;
    } else {
      if (!this.held.delete(code)) return true;          // released a key pressed before the step started
      if (!this.held.size) this.quietAt = ts;
    }
    return true;
  }

  /** Focus lost / page hidden: no keyup will come, the gesture counts as released now. */
  releaseAll(ts) {
    this.held.clear();
    if (this.phase === 'gesture') this.quietAt = ts;
  }

  /** When the gesture is over (silence after releasing everything); null = it is not running. */
  dueAt() { return this.phase === 'gesture' && this.quietAt !== null ? this.quietAt + LEARN_QUIET_MS : null; }

  /** Clock tick (ms of the event clock). Returns true when the gesture has just ended (→ confirm). */
  tick(now) {
    const due = this.dueAt();
    if (due === null || now < due) return false;
    this.code = this.choose();
    const other = Object.entries(this.result).find(([s, c]) => s !== this.step && c === this.code);
    this.error = other ? 'same' : null;
    this.phase = 'confirm';
    return true;
  }

  /**
   * The key of the gesture: the HW stream prefers a key that is not a modifier (mode C sends Ctrl with F13), a paddle
   * prefers a modifier pressed together with the first key (mode C: Ctrl = the paddle, F13 = the keyer output);
   * otherwise the first key pressed.
   */
  choose() {
    const first = this.gesture[0];
    if (this.step === 'stream') return (this.gesture.find((g) => !isModifier(g.code)) || first).code;
    const near = this.gesture.filter((g) => g.ts - first.ts <= LEARN_SAME_MS);
    return (near.find((g) => isModifier(g.code)) || first).code;
  }

  /** Confirmed (button / Enter): store the key, go to the next step. */
  confirm() {
    if (this.phase !== 'confirm' || this.error) return false;
    this.result[this.step] = this.code;
    this.i += 1;
    if (this.i >= this.steps.length) this.phase = 'done';
    else this.retry();
    return true;
  }

  /** Again: the same step from the start. */
  retry() {
    if (!this.active) return;
    this.phase = 'wait';
    this.held.clear();
    this.gesture = [];
    this.quietAt = null;
    this.code = null;
    this.error = null;
  }

  cancel() { this.phase = 'cancel'; }
}
