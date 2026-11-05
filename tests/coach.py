# SPDX-License-Identifier: EUPL-1.2
"""Python port web/js/coach.js (trenér nad lekcemi, M4). Konstanty a tabulky čte regexem z JS."""
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COACH_JS = (ROOT / 'web/js/coach.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in
          re.finditer(r'export const ([A-Z_]+) = ([0-9.]+);', COACH_JS)}
CONFIRM_GAP_H = CONSTS['CONFIRM_GAP_H']
CONFIRM_FROM_LEVEL = int(CONSTS['CONFIRM_FROM_LEVEL'])


def parse_ms(iso):
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp() * 1000
    except (ValueError, AttributeError):
        return None


def js_round(x):
    import math
    return math.floor(x + 0.5)


def confirm_gate(history, level, now):
    if level < CONFIRM_FROM_LEVEL:
        return {'ok': True, 'reason': None, 'firstAt': None, 'waitH': 0}
    ats = [t for t in (parse_ms(h['at']) for h in history if h['level'] == level) if t is not None]
    first = min(ats) if ats else now
    age = (now - first) / 3600000
    if age >= CONFIRM_GAP_H:
        return {'ok': True, 'reason': None, 'firstAt': first, 'waitH': 0}
    return {'ok': False, 'reason': 'confirm', 'firstAt': first, 'waitH': js_round((CONFIRM_GAP_H - age) * 10) / 10}

BLOCK_MAX_MIN = CONSTS['BLOCK_MAX_MIN']
SESSION_BREAK_MIN = CONSTS['SESSION_BREAK_MIN']
SESSION_END_MIN = CONSTS['SESSION_END_MIN']
DAY_WARN_MIN = CONSTS['DAY_WARN_MIN']
WARMUP_S = CONSTS['WARMUP_S']
FATIGUE_TTR = CONSTS['FATIGUE_TTR']
FATIGUE_ACC_DROP = CONSTS['FATIGUE_ACC_DROP']


def session_load(history, now, day_start):
    ls = []
    for h in history:
        e = parse_ms(h.get('at'))
        if e is not None and e <= now:
            ls.append({'end': e, 'dur': (h.get('durS') or 0) * 1000})
    ls.sort(key=lambda x: x['end'])
    day = sum(min(x['dur'], x['end'] - day_start) for x in ls if x['end'] >= day_start)
    last = ls[-1] if ls else None
    gap = (now - last['end']) / 3600000 if last else None
    brk = SESSION_BREAK_MIN * 60000
    ses = 0
    if last and now - last['end'] < brk:
        ses = last['dur']
        for i in range(len(ls) - 2, -1, -1):
            if ls[i + 1]['end'] - ls[i + 1]['dur'] - ls[i]['end'] >= brk:
                break
            ses += ls[i]['dur']
    smin = js_round(ses / 6000) / 10
    dmin = js_round(day / 6000) / 10
    return {'sessionMin': smin, 'dayMin': dmin, 'gapH': None if gap is None else js_round(gap * 10) / 10,
            'newSession': ses == 0, 'suggestEnd': smin >= SESSION_END_MIN, 'dayWarn': dmin > DAY_WARN_MIN}


def warmup_stats(trials, gap_h):
    if not trials:
        return None
    ok = sorted(t['ttr'] for t in trials if t['ok'] and t['ttr'] is not None)
    m = len(ok) >> 1
    ttr = None if not ok else ok[m] if len(ok) % 2 else js_round((ok[m - 1] + ok[m]) / 2)
    return {'n': len(trials), 'acc': js_round(sum(1 for t in trials if t['ok']) / len(trials) * 1000) / 1000,
            'ttr': ttr, 'gapH': None if gap_h is None else js_round(gap_h * 10) / 10}


def fatigue_signal(base, cur):
    if not base or not cur or base.get('acc') is None or cur.get('acc') is None:
        return {'tired': False, 'ttrUp': None, 'accDrop': None}
    up = js_round(cur['ttr'] / base['ttr'] * 100) / 100 if base.get('ttr') and cur.get('ttr') else None
    drop = js_round((base['acc'] - cur['acc']) * 1000) / 1000
    return {'tired': (up is not None and up >= FATIGUE_TTR) or drop >= FATIGUE_ACC_DROP - 1e-9,
            'ttrUp': up, 'accDrop': drop}

FATIGUE_BASE_N = int(CONSTS['FATIGUE_BASE_N'])
FATIGUE_WIN_N = int(CONSTS['FATIGUE_WIN_N'])
FATIGUE_HOLD_S = CONSTS['FATIGUE_HOLD_S']
FATIGUE_ACC_FLOOR = CONSTS['FATIGUE_ACC_FLOOR']
FATIGUE_SNOOZE_S = CONSTS['FATIGUE_SNOOZE_S']
REWARM_PAUSE_MIN = CONSTS['REWARM_PAUSE_MIN']
REWARM_S = CONSTS['REWARM_S']


FATIGUE_REF_MIN_N = CONSTS['FATIGUE_REF_MIN_N']
FATIGUE_REL_MIN = int(CONSTS['FATIGUE_REL_MIN'])


def trial_ttr(t, ref, new_char):
    if not t['ok'] or t.get('ttr') is None:
        return None
    if not ref:
        return t['ttr']
    if t.get('ch') == new_char or not ref.get(t.get('ch')):
        return None
    return js_round(t['ttr'] * 1000 / ref[t['ch']])


def part_stats(ts, ref=None, new_char=None):
    ok = sorted(x for x in (trial_ttr(t, ref, new_char) for t in ts) if x is not None)
    m = len(ok) >> 1
    ttr = None if not ok else ok[m] if len(ok) % 2 else js_round((ok[m - 1] + ok[m]) / 2)
    if ref and len(ok) < FATIGUE_REL_MIN:
        ttr = None
    out = {'acc': sum(1 for t in ts if t['ok']) / len(ts), 'ttr': ttr, 'n': len(ts)}
    if ref:
        out['rel'] = True
    return out


def fatigue_ref(prior):
    ref = {c: p['ttr'] for c, p in (prior or {}).items() if p and p.get('ttr') and p.get('n', 0) >= FATIGUE_REF_MIN_N}
    return ref or None


class FatigueMonitor:
    def __init__(self, base=None, ref=None, new_char=None):
        self.ref = ref
        self.new_char = new_char
        self.base = base if base and base['n'] >= FATIGUE_BASE_N and bool(base.get('rel')) == bool(ref) else None
        self.base_trials = []
        self.win = []
        self.since = None
        self.snooze_until = 0
        self.last = {'tired': False, 'held': False, 'ttrUp': None, 'accDrop': None}

    def reset(self):
        self.win = []
        self.since = None

    def snooze(self, active_s):
        self.snooze_until = active_s + FATIGUE_SNOOZE_S
        self.since = None

    def add(self, trial, active_s, count=True):
        none = {'propose': False, 'kind': None, 'ttrUp': None, 'accDrop': None}
        if not count:
            return none
        if not self.base:
            self.base_trials.append(trial)
            if len(self.base_trials) >= FATIGUE_BASE_N:
                self.base = part_stats(self.base_trials, self.ref, self.new_char)
            return none
        self.win.append(trial)
        if len(self.win) > FATIGUE_WIN_N:
            self.win.pop(0)
        if len(self.win) < FATIGUE_WIN_N:
            self.since = None
            return none
        cur = part_stats(self.win, self.ref, self.new_char)
        f = fatigue_signal(self.base, cur)
        ttr_t = f['ttrUp'] is not None and f['ttrUp'] >= FATIGUE_TTR
        acc_t = f['accDrop'] >= FATIGUE_ACC_DROP - 1e-9 and cur['acc'] < FATIGUE_ACC_FLOOR - 1e-9
        self.last = {'tired': ttr_t or acc_t, 'held': False, 'ttrUp': f['ttrUp'], 'accDrop': f['accDrop']}
        if not self.last['tired']:
            self.since = None
            return none
        if self.since is None:
            self.since = active_s
        self.last['held'] = active_s - self.since > FATIGUE_HOLD_S
        propose = self.last['held'] and active_s >= self.snooze_until
        return {'propose': propose, 'kind': 'ttr' if ttr_t else 'acc', 'ttrUp': f['ttrUp'], 'accDrop': f['accDrop']}
