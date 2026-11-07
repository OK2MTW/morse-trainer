# SPDX-License-Identifier: EUPL-1.2
"""Python port of the masking in web/js/band.js (M9 part 2): which characters the band made unreadable.
When band.js changes, update this copy too (test_band.py checks the constants)."""
import math
import re
from pathlib import Path

BAND_JS = (Path(__file__).resolve().parent.parent / 'web/js/band.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): float(m.group(2)) for m in re.finditer(r'(?:export )?const ([A-Z_]+) = ([0-9.]+);', BAND_JS)}
MASK_SNR, MASK_QRM_HZ = CONSTS['MASK_SNR'], CONSTS['MASK_QRM_HZ']
MASK_QRM_RATIO, MASK_QRN_RATIO = CONSTS['MASK_QRM_RATIO'], CONSTS['MASK_QRN_RATIO']
SIGNAL, REF_BW = CONSTS['SIGNAL'], CONSTS['REF_BW']


def fade_at(f, t):
    return f['base'] + sum(l['amp'] * math.sin(2 * math.pi * l['rate'] * (t - l['start'])) for l in f['lfo'])


def bandpass_gain(off, freq, bw):
    f, q = freq + off, freq / bw
    h = 1 / math.sqrt(1 + q * q * (f / freq - freq / f) ** 2)
    return h * h


def mask_chars(spans, env):
    noise_rel = (env.get('noise') or 0) * math.sqrt(env['filterBw'] / REF_BW)
    crash_rel = 0.577 * math.sqrt(0.64 * env['filterBw'] / (env['sampleRate'] / 2)) / (SIGNAL * math.sqrt(0.5))
    out = []
    for a0, b0 in spans:
        fm = min(fade_at(env['main'], a0), fade_at(env['main'], (a0 + b0) / 2), fade_at(env['main'], b0))
        res = None
        if noise_rel > 0 and fm < MASK_SNR * noise_rel:
            res = 'f'
        for q in env.get('qrm') or []:
            if res or abs(q['off']) >= MASK_QRM_HZ:
                continue
            g = q['level'] / SIGNAL * bandpass_gain(q['off'], env['freq'], env['filterBw'])
            if any(a < b0 and b > a0 and g * fade_at(q['fade'], (max(a, a0) + min(b, b0)) / 2) >= MASK_QRM_RATIO * fm
                   for a, b in q['keys']):
                res = 'm'
        for t, peak, decay in env.get('qrn') or []:
            r0 = peak * crash_rel / fm
            if res or r0 < MASK_QRN_RATIO or t >= b0:
                continue
            if t + decay / 3 * math.log(r0 / MASK_QRN_RATIO) > a0:
                res = 'n'
        out.append(res)
    return out
