// SPDX-License-Identifier: EUPL-1.2
// Touch keyboard with a fixed layout of the whole set (51 characters).
// Characters not learned yet are dimmed and inactive, but stay in their place (finger memory).
import { KEYBOARD_ROWS, PROSIGN_ALIAS } from './charset.js';
import { t } from './i18n.js';

// keyboard mode = lesson mode (stored values, see storage.js MODE_CHAR / MODE_COPY)
const MODE_CHAR = 'znak';
const MODE_COPY = 'skluz';

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
    this.mode = MODE_CHAR;
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
          b.textContent = t('keyboard.repeat');
          this.repeatKey = b;
          b.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            if (this.mode === MODE_COPY) { this.flashEl(b); this.actions.onSpace?.(e.timeStamp); } else this.actions.onRepeat?.();
          });
        } else if (ch === 'PAUSE') {
          b.classList.add('key-action');
          b.textContent = '⏸';
          b.setAttribute('aria-label', t('pause.title'));
          b.addEventListener('pointerdown', (e) => { e.preventDefault(); this.actions.onPause?.(); });
        } else {
          b.dataset.char = ch;
          b.textContent = ch;
          if (PROSIGN_ALIAS[ch]) {
            const s = document.createElement('small');
            s.textContent = PROSIGN_ALIAS[ch];
            b.append(s);
          }
          // pointerdown instead of click: no delay, an exact timeStamp for measuring the reaction
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

  /** Enables only the given characters (the current Koch set). */
  setActive(chars) {
    const set = new Set(chars);
    for (const [ch, b] of this.keys) {
      b.disabled = !set.has(ch);
    }
  }

  /** M7: copy mode = the "↻ again" key types a space (word separator), character mode = repeat the character. */
  setMode(mode) {
    this.mode = mode;
    if (this.repeatKey) this.repeatKey.textContent = mode === MODE_COPY ? t('keyboard.space') : t('keyboard.repeat');
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
