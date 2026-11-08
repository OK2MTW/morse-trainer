# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/keyer.js (VK, 0.11.0) – keyer state machine (the decoder: tests/decoder.py).
When keyer.js changes, update this copy too (test_keyer.py checks the constants and the key types)."""
import re
from pathlib import Path

KEYER_JS = (Path(__file__).resolve().parent.parent / 'web/js/keyer.js').read_text(encoding='utf-8')
KEY_TYPES = re.findall(r"'(\w+)'", re.search(r'export const KEY_TYPES = \[([^\]]*)\]', KEYER_JS).group(1))
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = ([\d.]+);', KEYER_JS)}
DOT, DASH = '.', '-'


def unit_ms(wpm):
    return 1200 / wpm


def side_of(el):
    return 'dot' if el == DOT else 'dash'


def opposite(el):
    return DASH if el == DOT else DOT


def is_automatic(t):
    return t != 'straight'


def manual_side(t):
    return {'straight': 'dot', 'bug': 'dash'}.get(t)


class Keyer:
    def __init__(self, type='iambicB', wpm=18, ratio=3):
        self.type = type if type in KEY_TYPES else 'iambicB'
        self.wpm = min(CONSTS['KEYER_WPM_MAX'], max(CONSTS['KEYER_WPM_MIN'], wpm))
        self.ratio = min(CONSTS['RATIO_MAX'], max(CONSTS['RATIO_MIN'], ratio))
        self.reset()

    def reset(self):
        self.down = {'dot': False, 'dash': False}
        self.mem = {'dot': False, 'dash': False}
        self.order = []
        self.last = None
        self.busy = False
        self.squeeze = False

    @property
    def unit(self):
        return unit_ms(self.wpm)

    def element_ms(self, el):
        return self.unit * self.ratio if el == DASH else self.unit

    def press(self, side):
        if self.down[side]:
            return False
        self.down[side] = True
        self.order.append(side)
        if self.down['dot'] and self.down['dash']:
            self.squeeze = True
        if self.busy and self.type not in ('bug', 'straight'):
            self.mem[side] = True
        return not self.busy and is_automatic(self.type) and (self.type != 'bug' or side == 'dot')

    def release(self, side):
        if not self.down[side]:
            return
        self.down[side] = False
        self.order = [s for s in self.order if s != side]

    def release_all(self):
        self.reset()

    def next(self):
        t, el = self.type, None
        if t == 'bug':
            el = DOT if self.down['dot'] else None
        elif t != 'straight':
            dot = self.down['dot'] or self.mem['dot']
            dash = self.down['dash'] or self.mem['dash']
            if dot and dash:
                if t == 'single':
                    held = self.order[-1] if self.order else None
                    if self.mem['dot'] != self.mem['dash']:
                        el = DOT if self.mem['dot'] else DASH
                    else:
                        el = DASH if held == 'dash' else DOT
                elif self.last:
                    el = opposite(self.last)
                else:
                    el = DASH if self.order and self.order[0] == 'dash' else DOT
            elif dot:
                el = DOT
            elif dash:
                el = DASH
            elif t == 'iambicB' and self.squeeze and self.last:
                el = opposite(self.last)
        if el:
            self.mem[side_of(el)] = False
            self.last = el
            self.busy = True
            self.squeeze = self.down['dot'] and self.down['dash']
        else:
            self.busy = False
            self.last = None
            self.squeeze = False
            self.mem = {'dot': False, 'dash': False}
        return el
