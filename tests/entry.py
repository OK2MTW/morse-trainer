# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/entry.js (Z-14 entry test) – order of the test and evaluation.
When entry.js changes, update this copy too (test_entry.py checks the constants)."""
import re
from pathlib import Path

ENTRY_JS = (Path(__file__).resolve().parent.parent / 'web/js/entry.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): int(m.group(2)) for m in re.finditer(r'export const ([A-Z_]+) = (\d+);', ENTRY_JS)}
ENTRY_REPS, ENTRY_TTR_MAX, ENTRY_MIN_LEVEL = CONSTS['ENTRY_REPS'], CONSTS['ENTRY_TTR_MAX'], CONSTS['ENTRY_MIN_LEVEL']


def entry_sequence(chars, rng):
    pool = [c for c in chars for _ in range(ENTRY_REPS)]
    out = []
    while pool:
        ok = [i for i, c in enumerate(pool) if not out or c != out[-1]] or list(range(len(pool)))
        out.append(pool.pop(ok[int(rng() * len(ok))]))
    return out


def entry_result(chars, trials):
    per = {c: [] for c in chars}
    for t in trials:
        if t['ch'] in per:
            per[t['ch']].append(t)
    known, unsure, per_char = [], [], []
    for c in chars:
        ts = per[c]
        ok = [x for x in ts if x['ans'] == c]
        good = len(ts) >= ENTRY_REPS and len(ok) == len(ts) and all(x['ttr'] is not None and x['ttr'] <= ENTRY_TTR_MAX for x in ok)
        (known if good else unsure).append(c)
        if ts:
            r = sorted(x['ttr'] for x in ok if x['ttr'] is not None)
            per_char.append({'ch': c, 'n': len(ts), 'acc': len(ok) / len(ts), 'ttr': r[(len(r) - 1) >> 1] if r else None})
    level = 0
    while level < len(chars) and chars[level] in known:
        level += 1
    return {'known': known, 'unsure': unsure, 'level': max(ENTRY_MIN_LEVEL, level), 'perChar': per_char}
