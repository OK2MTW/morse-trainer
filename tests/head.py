# SPDX-License-Identifier: EUPL-1.2
"""Python port of web/js/head.js (U6 head copy, 0.10.14) – answer normalisation, scoring, templates.
When head.js changes, update this copy too (test_head.py checks the templates and constants)."""
import re
from pathlib import Path

HEAD_JS = (Path(__file__).resolve().parent.parent / 'web/js/head.js').read_text(encoding='utf-8')
HEAD_Q = int(re.search(r'export const HEAD_Q = (\d+);', HEAD_JS).group(1))
HEAD_FIELDS = re.findall(r"'(\w+)'", re.search(r'export const HEAD_FIELDS = \[(.*?)\]', HEAD_JS).group(1))
TEMPLATES = [{'text': m.group(1), 'from': m.group(2), 'to': m.group(4),
              'fields': re.findall(r"'(\w+)'", m.group(5))}
             for m in re.finditer(r"\{ text: '([^']+)', from: '(\w)'(, to: '(\w)')?, fields: \[([^\]]*)\] \}", HEAD_JS)]


def normalize(key, s):
    v = re.sub(r'[^A-Z0-9/?]', '', str(s or '').upper())
    if key == 'PWR':
        v = re.sub(r'W$', '', v)
    if key == 'TEMP':
        v = re.sub(r'C$', '', v)
    return v


def is_correct(key, answer, expected):
    return normalize(key, answer) != '' and normalize(key, answer) == normalize(key, expected)


def score_head(qso, written):
    res = [{'key': k, 'answer': written.get(k, ''), 'expected': qso['answers'][k],
            'ok': is_correct(k, written.get(k), qso['answers'][k])} for k in qso['questions']]
    return {'n': len(res), 'ok': sum(1 for r in res if r['ok']), 'res': res}


def head_summary(rounds):
    fields, n, ok = {}, 0, 0
    for r in rounds:
        for x in r['sc']['res']:
            f = fields.setdefault(x['key'], [0, 0])
            f[0] += 1
            f[1] += 1 if x['ok'] else 0
        n += r['sc']['n']
        ok += r['sc']['ok']
    return {'q': n, 'ok': ok, 'acc': ok / n if n else None, 'rounds': len(rounds), 'fields': fields}
