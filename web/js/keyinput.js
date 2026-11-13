// SPDX-License-Identifier: EUPL-1.2
// 0.14.1: keyboard input of the telegraph key – shared by the key page (keyerui.js) and the CW Chat (cwchannel.js).
// Pure logic without DOM, ported to tests/keyinput.py. 0.15.3 (Martin 2026-11-12): only the HW keyer is supported –
// the app keyer types, the on-screen and keyboard paddles are gone. Maps keydown / keyup to actions by the key
// settings of the device (cfg.stream):
//   stream – the tone of a HW keyer on / off (docs/hw/klic-rozhrani.md)
//   paddle – the paddle state of a HW key in mode C (Left / Right Ctrl), only logged – it keys nothing
// Autorepeat of the OS by own state, not by event.repeat (validation #33: on Windows a key held with another one
// may arrive marked as a repeat).

export const HW_TYPE = 'hw';
export const HW_PADDLES = { ControlLeft: 'dot', ControlRight: 'dash' };
/** Shared by the key page and the CW Chat: a stream key arrived in this app session (the key is connected). */
export const hwState = { seen: false };

export class KeyInput {
  constructor(cfg) {
    this.cfg = cfg;
    this.keys = new Set();   // codes held down
  }

  /** Own autorepeat filter: true = a real change of the key. */
  change(code, down) {
    if (down) {
      if (this.keys.has(code)) return false;
      this.keys.add(code);
      return true;
    }
    return this.keys.delete(code);
  }

  /** One keydown / keyup → actions in order ([] = swallowed repeat), null = not a key of the telegraph key. */
  key(code, down) {
    const stream = code === this.cfg.stream;
    const paddle = stream ? null : HW_PADDLES[code];
    if (!stream && !paddle) return null;
    if (!this.change(code, down)) return [];
    return [stream ? { kind: 'stream', down } : { kind: 'paddle', side: paddle, down }];
  }

  /** Focus lost / page hidden / settings changed: nothing is held any more. */
  releaseAll() { this.keys.clear(); }
}
