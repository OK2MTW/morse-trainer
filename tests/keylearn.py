# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/keylearn.js (0.13.11) – learning the key mapping with confirmation.
When keylearn.js changes, update this copy too (test_keylearn.py checks the constants)."""
import re
from pathlib import Path

KEYLEARN_JS = (Path(__file__).resolve().parent.parent / 'web/js/keylearn.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = ([\d.]+);', KEYLEARN_JS)}
QUIET_MS = CONSTS['LEARN_QUIET_MS']
SAME_MS = CONSTS['LEARN_SAME_MS']
SKIP = re.findall(r"'(\w+)'", re.search(r'export const LEARN_SKIP = \[([^\]]*)\]', KEYLEARN_JS).group(1))


def is_modifier(code):
    return re.match(r'^(Control|Shift|Alt|Meta)', code) is not None


class KeyLearn:
    def __init__(self, steps):
        self.steps = steps
        self.i = 0
        self.result = {}
        self.phase = 'wait'
        self.held = set()
        self.gesture = []
        self.quiet_at = None
        self.code = None
        self.error = None

    @property
    def step(self):
        return self.steps[self.i]

    @property
    def active(self):
        return self.phase not in ('done', 'cancel')

    def key(self, code, down, ts, repeat=False):
        if not self.active:
            return False
        if down and code == 'Escape':
            self.phase = 'cancel'
            return True
        if self.phase == 'confirm':
            if down and not repeat and code in ('Enter', 'NumpadEnter'):
                if self.error:
                    self.retry()
                else:
                    self.confirm()
            return True
        if code in SKIP:
            return True
        if down:
            if repeat or code in self.held:
                return True
            if self.phase == 'wait':
                self.phase = 'gesture'
                self.gesture = []
            self.held.add(code)
            self.gesture.append((code, ts))
            self.quiet_at = None
        else:
            if code not in self.held:
                return True
            self.held.discard(code)
            if not self.held:
                self.quiet_at = ts
        return True

    def release_all(self, ts):
        self.held.clear()
        if self.phase == 'gesture':
            self.quiet_at = ts

    def due_at(self):
        return self.quiet_at + QUIET_MS if self.phase == 'gesture' and self.quiet_at is not None else None

    def tick(self, now):
        due = self.due_at()
        if due is None or now < due:
            return False
        self.code = self.choose()
        other = [s for s, c in self.result.items() if s != self.step and c == self.code]
        self.error = 'same' if other else None
        self.phase = 'confirm'
        return True

    def choose(self):
        first = self.gesture[0]
        if self.step == 'stream':
            return next((g for g in self.gesture if not is_modifier(g[0])), first)[0]
        near = [g for g in self.gesture if g[1] - first[1] <= SAME_MS]
        return next((g for g in near if is_modifier(g[0])), first)[0]

    def confirm(self):
        if self.phase != 'confirm' or self.error:
            return False
        self.result[self.step] = self.code
        self.i += 1
        if self.i >= len(self.steps):
            self.phase = 'done'
        else:
            self.retry()
        return True

    def retry(self):
        if not self.active:
            return
        self.phase = 'wait'
        self.held.clear()
        self.gesture = []
        self.quiet_at = None
        self.code = None
        self.error = None

    def cancel(self):
        self.phase = 'cancel'
