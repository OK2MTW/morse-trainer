# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/keyinput.js (0.14.1, HW keyer only since 0.15.3) – keyboard input of the telegraph key
(key page + CW Chat). When keyinput.js changes, update this copy too (test_keyinput.py checks the constants)."""
import re
from pathlib import Path

KEYINPUT_JS = (Path(__file__).resolve().parent.parent / 'web/js/keyinput.js').read_text(encoding='utf-8')
HW_TYPE = re.search(r"export const HW_TYPE = '(\w+)';", KEYINPUT_JS).group(1)
HW_PADDLES = dict(re.findall(r"(\w+): '(dot|dash)'", re.search(r'export const HW_PADDLES = \{([^}]*)\}',
                                                                 KEYINPUT_JS).group(1)))


class KeyInput:
    def __init__(self, cfg):
        self.cfg = cfg
        self.keys = set()

    def change(self, code, down):
        if down:
            if code in self.keys:
                return False
            self.keys.add(code)
            return True
        if code in self.keys:
            self.keys.discard(code)
            return True
        return False

    def key(self, code, down):
        stream = code == self.cfg['stream']
        paddle = None if stream else HW_PADDLES.get(code)
        if not stream and not paddle:
            return None
        if not self.change(code, down):
            return []
        return [{'kind': 'stream', 'down': down} if stream else {'kind': 'paddle', 'side': paddle, 'down': down}]

    def release_all(self):
        self.keys.clear()
