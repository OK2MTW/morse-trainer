# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/keylog.js (0.14.3) – summary of the key event log (acceptance test H-42 (1)).
When keylog.js changes, update this copy too (test_keylog.py checks the constants)."""
import re
from pathlib import Path

KEYLOG_JS = (Path(__file__).resolve().parent.parent / 'web/js/keylog.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = ([\d.]+);', KEYLOG_JS)}
SPLIT = CONSTS['LOG_SPLIT']


def _median(a):
    s = sorted(a)
    n = len(s)
    return s[(n - 1) // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _stats(a):
    return {'n': len(a), 'med': _median(a), 'min': min(a), 'max': max(a)} if a else None


def length_groups(lens):
    s = sorted(lens)
    at, best = -1, 0
    for i in range(1, len(s)):
        r = s[i] / max(1, s[i - 1])
        if r > best:
            best, at = r, i
    if at < 0 or best < SPLIT:
        return {'dot': None, 'dash': None, 'all': _stats(s)}
    return {'dot': _stats(s[:at]), 'dash': _stats(s[at:]), 'all': _stats(s)}


def log_summary(events):
    open_, lens = {}, {}
    dup = orphan = 0
    for e in events:
        lens.setdefault(e['code'], [])
        if e['down']:
            if e['code'] in open_:
                dup += 1
            open_[e['code']] = e['at']
        elif e['code'] not in open_:
            orphan += 1
        else:
            lens[e['code']].append(e['at'] - open_.pop(e['code']))
    keys = []
    for code, ln in lens.items():
        g = length_groups(ln)
        keys.append({'code': code, 'n': len(ln), **g, 'wpm': 1200 / g['dot']['med'] if g['dot'] else None})
    return {'events': len(events), 'ms': events[-1]['at'] - events[0]['at'] if events else 0, 'keys': keys,
            'dup': dup, 'orphan': orphan, 'open': len(open_)}
