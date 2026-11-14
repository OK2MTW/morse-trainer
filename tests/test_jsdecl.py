# SPDX-License-Identifier: EUPL-1.2
"""1.0.3: a name declared twice at the top level of a module (import / const / let / function / class) is a
SyntaxError – the browser rejects the whole module graph and the app does not start (1.0.2: fmtMin in main.js).
There is no JS engine on the Pi, so this is checked here."""
import collections
import re
import unittest
from pathlib import Path

JS = sorted((Path(__file__).resolve().parent.parent / 'web/js').glob('*.js'))


def top_level_names(src):
    names = []
    for m in re.finditer(r'^import\s*\{([^}]*)\}\s*from', src, re.M | re.S):
        names += [n.split(' as ')[-1].strip() for n in m.group(1).split(',') if n.strip()]
    names += re.findall(r'^import\s+(\w+)\s+from', src, re.M)
    names += re.findall(r'^(?:export\s+)?(?:const|let|var|function\*?|async function|class)\s+(\w+)', src, re.M)
    return names


class DeclTest(unittest.TestCase):
    def test_no_duplicate_top_level_names(self):
        self.assertTrue(JS)
        bad = {}
        for f in JS:
            dup = [n for n, c in collections.Counter(top_level_names(f.read_text(encoding='utf-8'))).items() if c > 1]
            if dup:
                bad[f.name] = dup
        self.assertEqual(bad, {})

    def test_detects_the_1_0_2_bug(self):
        src = "const fmtMin = (m) => m;\nfunction x() {}\nconst fmtMin = (m) => `${m}`;\n"
        self.assertEqual([n for n, c in collections.Counter(top_level_names(src)).items() if c > 1], ['fmtMin'])


if __name__ == '__main__':
    unittest.main()
