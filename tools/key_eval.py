# SPDX-License-Identifier: EUPL-1.2
"""1.1 K1: how well the decoder reads a real hand – recordings `klic` and simulated operators (tests/stations.py)
replayed through the decoder port (tests/decoder.py) and the virtual operator's reading (tests/vo.py).

    .venv/bin/python -m tools.key_eval [--db COPY.sqlite] [--seeds 3] [--json] [--reader NAME]

--db = a COPY of the database (sqlite3 backup, never the live file): adds the recordings `klic` from traces.
Metrics (lower = better, all in % of the reference characters, spaces included):
  cer   decoder text vs keyed (what the hand really keyed) – the decoder's error
  chr   the same without spaces – wrong characters only
  vo    the VO's reading (mend_spacing, tolerance mid) vs keyed
  meant the VO's reading vs meant (the hand's errors included)
  cold  cer of the first 3 words of the first over of a session (nothing learned yet)
  b01 / b12 gaps put in a wrong class (inside↔between characters / characters↔words), % of the gaps
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from tests import decoder as D
from tests import stations as S
from tests import vo as V

ROOT = Path(__file__).resolve().parent.parent
HW_WPM = 18           # web/js/keyerui.js HW_WPM
TOL = 'mid'
COLD_WORDS = 3


def edit_distance(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        p, d[0] = d[0], i
        for k in range(1, len(b) + 1):
            p, d[k] = d[k], min(d[k] + 1, d[k - 1] + 1, p + (a[i - 1] != b[k - 1]))
    return d[len(b)]


def norm(text):
    return ' '.join((text or '').upper().split())


# --- readers: (tones, state) → {text, read, gaps}; state carries what the page keeps between overs ---------------

def read_current(tones, state, machine=True, calls=(S.ME, S.VO)):
    """1.0.3: decodeTones (machine stream, the word threshold learned from the earlier overs) → overText →
    mendSpacing, as voui.js decodeOwn / armEnd."""
    dec = D.decode_tones(tones, HW_WPM, S.MORSE, machine=machine, dot=state.get('dot'), word=state.get('word'))
    text = V.over_text(dec['chars'])
    if machine:
        w = D.learned_word_gap(dec)
        if w is not None:
            state['word'] = w
        state['dot'] = dec['dot']
    return {'text': text, 'read': V.mend_spacing(text, TOL, calls), 'gaps': dec['gaps']}


def read_k2(tones, state, machine=True, calls=(S.ME, S.VO)):
    """1.1 K2: as 1.0.3, but the gaps of a machine stream from the gap model (tests/decoder.py GapModel) learned
    over the whole over plus the earlier overs of the session (state['gm'])."""
    if not machine:
        return read_current(tones, state, machine, calls)
    dec = D.decode_tones(tones, HW_WPM, S.MORSE, machine=True, dot=state.get('dot'), model=True,
                         gap_prior=state.get('gm'))
    text = V.over_text(dec['chars'])
    state['dot'] = dec['dot']
    state['gm'] = dec['gm'].learned()
    return {'text': text, 'read': V.mend_spacing(text, TOL, calls), 'gaps': dec['gaps'], 'conf': dec['conf'],
            'dec': dec}


over_units = V.over_units


def read_k3(tones, state, machine=True, calls=(S.ME, S.VO)):
    """1.1 K3: the K2 decoding, the spacing of the over from P(gap)·P(text) (vo.segment) instead of mendSpacing."""
    if not machine:
        return read_current(tones, state, machine, calls)
    res = read_k2(tones, state, machine, calls)
    res['read'] = V.segment(over_units(res['dec']), TOL, calls)
    return res


READERS = {'1.0.3': read_current, '1.1-k2': read_k2, '1.1-k3': read_k3}


# --- metrics ---------------------------------------------------------------------------------------------------

def _first_words(ref, hyp, n):
    """The first n words of ref and the part of hyp with the same number of characters (spaces not counted)."""
    rw = ref.split()[:n]
    need = sum(len(w) for w in rw)
    out, got = [], 0
    for w in hyp.split():
        if got >= need:
            break
        out.append(w)
        got += len(w)
    return ' '.join(rw), ' '.join(out)


def over_metrics(over, res, first=False):
    keyed, meant = norm(over.get('keyed') or over['meant']), norm(over['meant'])
    text, read = norm(res['text']), norm(res['read'])
    m = {'n': len(keyed), 'nc': len(keyed.replace(' ', '')),
         'cer': edit_distance(keyed, text), 'chr': edit_distance(keyed.replace(' ', ''), text.replace(' ', '')),
         'vo': edit_distance(keyed, read), 'meant': edit_distance(meant, read), 'nm': len(meant)}
    if first:
        r, h = _first_words(keyed, text, COLD_WORDS)
        m['cold'], m['ncold'] = edit_distance(r, h), len(r)
    truth = over.get('truth')
    if truth:
        g = res['gaps']
        pairs = [(t, k) for t, k in zip(truth, g) if t is not None and k is not None]
        m['ng'] = len(pairs)
        m['b01'] = sum(1 for t, k in pairs if {t, k} == {0, 1})
        m['b12'] = sum(1 for t, k in pairs if {t, k} == {1, 2})
        m['b02'] = sum(1 for t, k in pairs if {t, k} == {0, 2})
    return m


def add(total, m):
    for k, v in m.items():
        total[k] = total.get(k, 0) + v
    return total


def pct(total):
    """Sums → percentages of the reference lengths."""
    def p(k, n):
        return round(100 * total[k] / total[n], 2) if total.get(n) else None
    return {'cer': p('cer', 'n'), 'chr': p('chr', 'nc'), 'vo': p('vo', 'n'), 'meant': p('meant', 'nm'),
            'cold': p('cold', 'ncold'), 'b01': p('b01', 'ng'), 'b12': p('b12', 'ng')}


# --- data -------------------------------------------------------------------------------------------------------

def _tones(raw):
    out = []
    for t in raw:
        if isinstance(t, dict):
            out.append({'start': t.get('s', t.get('start')), 'end': t.get('e', t.get('end'))})
        else:
            out.append({'start': t[0], 'end': t[1]})
    return out


def file_recordings():
    out = []
    for f in sorted((ROOT / 'tests/data').glob('key_recordings*.json')):
        for i, r in enumerate(json.loads(f.read_text(encoding='utf-8'))['recordings']):
            out.append({'src': f'{f.stem}#{i}', 'type': r.get('type'), 'meant': r['meant'], 'keyed': r.get('keyed'),
                        'tones': _tones(r['tones'])})
    return out


def db_recordings(path):
    """Recordings `klic` from a COPY of the database with a known text (meant) or automatic ones (end.auto)."""
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    out = []
    for tid, at, data in con.execute("SELECT id, at, data FROM traces WHERE kind = 'klic' ORDER BY id"):
        e = json.loads(data).get('end') or {}
        items = e.get('items') if e.get('auto') else [e]
        for k, it in enumerate(items or []):
            tones = _tones(it.get('tones') or [])
            if len(tones) < 2:
                continue
            out.append({'src': f'db#{tid}' + (f'.{k}' if e.get('auto') else ''), 'type': e.get('type', 'hw'),
                        'meant': it.get('meant') or '', 'keyed': None, 'auto': bool(e.get('auto')),
                        'tones': tones, 'at': at})
    return out


# --- evaluation ---------------------------------------------------------------------------------------------------

def eval_stations(reader, seeds=3, stations=S.STATIONS):
    """Per station (all seeds, all overs of a session) and overall → {name: pct}, plus '_all'."""
    rows, all_t = {}, {}
    for st in stations:
        tot = {}
        for seed in range(seeds):
            state = {}
            for i, over in enumerate(S.session(st, seed)):
                add(tot, over_metrics(over, reader(over['tones'], state), first=i == 0))
        rows[st['name']] = pct(tot)
        add(all_t, tot)
    rows['_all'] = pct(all_t)
    return rows


def eval_recordings(reader, recs):
    """Recordings with a known text: cold (nothing learned) and warm (learned from the previous recording of the
    same type – as the next over on the same device)."""
    rows = []
    prev = {}
    for r in recs:
        if not r['meant']:
            continue
        machine = r['type'] == 'hw'
        cold = over_metrics(r, reader(r['tones'], {}, machine=machine), first=True)
        warm_state = dict(prev.get(r['type']) or {})
        warm = over_metrics(r, reader(r['tones'], warm_state, machine=machine), first=True)
        learn = {}
        reader(r['tones'], learn, machine=machine)
        prev[r['type']] = learn
        rows.append({'src': r['src'], 'type': r['type'], 'cold': pct(cold), 'warm': pct(warm)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--db', help='a COPY of the database (sqlite3 backup)')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--reader', default=list(READERS)[-1], choices=list(READERS))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    reader = READERS[a.reader]
    recs = file_recordings() + (db_recordings(a.db) if a.db else [])
    res = {'reader': a.reader, 'stations': eval_stations(reader, a.seeds), 'recordings': eval_recordings(reader, recs),
           'auto': sum(1 for r in recs if r.get('auto'))}
    if a.json:
        json.dump(res, sys.stdout, indent=1)
        print()
        return
    cols = ['cer', 'chr', 'vo', 'meant', 'cold', 'b01', 'b12']

    def fmt(v):
        return f'{v:6.1f}' if v is not None else '     –'
    print(f"reader {a.reader}   simulated operators ({a.seeds} sessions × {len(S.OVERS)} overs), % errors")
    print(f"{'station':12}" + ''.join(f'{c:>7}' for c in cols))
    for name, p in res['stations'].items():
        print(f'{name:12}' + ' '.join(fmt(p[c]) for c in cols))
    print(f"\nrecordings (cold / warm), % errors   [automatic end.auto: {res['auto']}]")
    print(f"{'source':24}{'type':>9}" + ''.join(f'{c:>13}' for c in ['cer', 'vo', 'meant']))
    for r in res['recordings']:
        print(f"{r['src']:24}{r['type']:>9}" + ''.join(
            f"{fmt(r['cold'][c])}/{fmt(r['warm'][c]).strip():<6}" for c in ['cer', 'vo', 'meant']))


if __name__ == '__main__':
    main()
