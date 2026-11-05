// SPDX-License-Identifier: EUPL-1.2
// Dotyková klávesnice s pevným rozložením celé sady (51 znaků).
// Nenaučené znaky jsou ztlumené a neaktivní, ale zůstávají na svém místě (paměť prstů).
import { KEYBOARD_ROWS, PROSIGN_ALIAS } from './charset.js';

export class TouchKeyboard {
  /**
   * @param {HTMLElement} root
   * @param {(ch: string, timeStamp: number) => void} onChar
   * @param {{onRepeat?: Function, onPause?: Function}} actions
   */
  constructor(root, onChar, actions = {}) {
    this.root = root;
    this.onChar = onChar;
    this.actions = actions;
    this.keys = new Map();
    this.mode = 'znak';
    this._render();
  }

  _render() {
    this.root.textContent = '';
    this.root.classList.add('kbd');
    for (const row of KEYBOARD_ROWS) {
      const r = document.createElement('div');
      r.className = 'kbd-row';
      for (const ch of row) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'key';
        if (ch === 'REPEAT') {
          b.classList.add('key-wide', 'key-action');
          b.textContent = '↻ znovu';
          this.repeatKey = b;
          b.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            if (this.mode === 'skluz') { this.flashEl(b); this.actions.onSpace?.(e.timeStamp); } else this.actions.onRepeat?.();
          });
        } else if (ch === 'PAUSE') {
          b.classList.add('key-action');
          b.textContent = '⏸';
          b.setAttribute('aria-label', 'Pauza');
          b.addEventListener('pointerdown', (e) => { e.preventDefault(); this.actions.onPause?.(); });
        } else {
          b.dataset.char = ch;
          b.textContent = ch;
          if (PROSIGN_ALIAS[ch]) {
            const s = document.createElement('small');
            s.textContent = PROSIGN_ALIAS[ch];
            b.append(s);
          }
          // pointerdown místo click: žádné zpoždění, přesný timeStamp pro měření reakce
          b.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            if (b.disabled) return;
            if (navigator.vibrate) navigator.vibrate(8);
            this.flash(ch);
            this.onChar(ch, e.timeStamp);
          });
          this.keys.set(ch, b);
        }
        r.append(b);
      }
      this.root.append(r);
    }
  }

  /** Povolí jen zadané znaky (aktuální Kochova sada). */
  setActive(chars) {
    const set = new Set(chars);
    for (const [ch, b] of this.keys) {
      b.disabled = !set.has(ch);
    }
  }

  /** M7: 'skluz' = klávesa „↻ znovu“ píše mezeru (oddělovač slov), 'znak' = opakování znaku. */
  setMode(mode) {
    this.mode = mode;
    if (this.repeatKey) this.repeatKey.textContent = mode === 'skluz' ? '␣ mezera' : '↻ znovu';
  }

  flash(ch, cls = 'pressed', ms = 180) {
    this.flashEl(this.keys.get(ch), cls, ms);
  }

  flashEl(b, cls = 'pressed', ms = 180) {
    if (!b) return;
    b.classList.add(cls);
    setTimeout(() => b.classList.remove(cls), ms);
  }
}
