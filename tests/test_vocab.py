# SPDX-License-Identifier: EUPL-1.2
"""0.10.0 vocabulary: every code has a meaning in every language, codes pass the server check, answers are distinct."""
import json
import re
import unittest
from pathlib import Path

from server.api import VOCAB_CODE, VOCAB_LISTS

WEB = Path(__file__).resolve().parent.parent / "web"
JS = (WEB / "js" / "vocab.js").read_text()
ITEMS = {}
EXTRA = set()  # items outside the CTU list
for k, name in (("abbr", "ABBR_TABLE"), ("q", "Q_TABLE"), ("pfx", "PFX_TABLE")):
    ITEMS[k] = {}
    for line in re.search(rf"const {name} = `(.*?)`", JS, re.S).group(1).strip().splitlines():
        code, show, quiz, *flag = (x.strip() for x in line.split("|"))
        ITEMS[k][code] = (show, quiz.split())
        if flag == ["+"]:
            EXTRA.add((k, code))
LISTS = {k: list(v) for k, v in ITEMS.items()}
PFX = ITEMS["pfx"]
LANGS = {p.stem: json.loads(p.read_text()) for p in (WEB / "i18n").glob("*.json") if p.stem != "languages"}


class VocabTest(unittest.TestCase):
    def test_lists_match_server(self):
        self.assertEqual(tuple(LISTS), VOCAB_LISTS)
        self.assertIn("export const VOCAB_LISTS = ['abbr', 'q', 'pfx'];", JS)

    def test_codes(self):
        for k, codes in LISTS.items():
            self.assertGreaterEqual(len(codes), 25, k)
            self.assertEqual(len(codes), len(set(codes)), k)
            for c in codes:
                self.assertTrue(VOCAB_CODE.match(c), c)
        self.assertTrue(all(c.startswith("Q") for c in LISTS["q"]))

    def test_meanings_in_all_languages_and_distinct(self):
        for lang, d in LANGS.items():
            for k, codes in LISTS.items():
                vals = []
                for c in codes:
                    key = f"vocab.{k}.{c}"
                    self.assertIn(key, d, (lang, key))
                    self.assertTrue(d[key].strip(), key)
                    vals.append(d[key])
                dup = {v for v in vals if vals.count(v) > 1}
                self.assertEqual(dup, set(), (lang, k))  # three choices must never show two equal answers

    def test_prefix_series(self):
        """0.10.1: every quiz prefix belongs to exactly one country, is a valid code and appears in the series text."""
        seen = {}
        for code, (show, quiz) in PFX.items():
            self.assertTrue(any(p.replace('/', '').startswith(code) for p in quiz), code)  # the item code is one of its prefixes (UA → UA3)
            self.assertTrue(show and not re.search(r"[a-zá-ž]", show), (code, show))  # language-neutral
            for p in quiz:
                self.assertTrue(VOCAB_CODE.match(p), p)
                self.assertNotIn(p, seen, (p, code, seen.get(p)))
                seen[p] = code
        self.assertEqual(len(PFX), 85)  # CTU exam lists 06-2025: 85 countries/regions
        self.assertEqual(set(PFX["OK"][1]), {"OK", "OL"})
        self.assertTrue({"K", "W", "N", "AA"} <= set(PFX["K"][1]))
        self.assertNotIn("OX", PFX["OZ"][1])  # Greenland is its own region
        self.assertNotIn("TK", PFX["F"][1])   # Corsica
        self.assertNotIn("BV", PFX["BY"][1])  # Taiwan
        self.assertIn("DR", PFX["DL"][1])     # Germany DA–DR

    def test_official_lists(self):
        """0.10.6: CTU exam lists (classes A + N): forms of every item are valid, unique and contain the item code."""
        official = {k: [c for c in ITEMS[k] if (k, c) not in EXTRA] for k in ITEMS}
        self.assertEqual((len(official["abbr"]), len(official["q"]), len(official["pfx"])), (153, 25, 85))
        self.assertEqual(len(ITEMS["q"]), 39)  # 0.13.7: Q-kodex of the Czech Radio Club
        self.assertTrue({("abbr", "TU"), ("abbr", "5NN"), ("q", "QRQ")} <= EXTRA)  # Martin 2026-11-07: extras back
        for k in ("abbr", "q"):
            seen = {}
            for code, (show, quiz) in ITEMS[k].items():
                self.assertIn(code, [f.rstrip("?") for f in quiz], code)  # results are stored under the code
                self.assertEqual(show.replace(" ", "").split(","), quiz, code)  # the overview shows all forms
                for f in quiz:
                    self.assertTrue(VOCAB_CODE.match(f), f)
                    self.assertNotIn(f, seen, (f, code))
                    seen[f] = code
        self.assertEqual(ITEMS["abbr"]["TNX"][1], ["TNX", "TKS"])
        self.assertEqual(ITEMS["q"]["QRO"][1], ["QRO", "QRO?"])
        self.assertEqual(ITEMS["q"]["QST"][1], ["QST"])  # no question form
        cs = LANGS["cs"]
        self.assertEqual(cs["vocab.q.QRM"], "Vaše vysílání ruší jiné stanice")
        self.assertEqual(cs["vocab.abbr.KN"], "přecházím na poslech pro určitou stanici")
        # no stale meanings of removed items
        for lang, d in LANGS.items():
            for key in d:
                m = re.match(r"vocab\.(abbr|q|pfx)\.(.+)$", key)
                if m:
                    self.assertIn(m.group(2), ITEMS[m.group(1)], (lang, key))

    def test_q_questions(self):
        """0.13.7: every Q code with a question form (QRO?) has a question meaning in every language, all distinct."""
        for lang, d in LANGS.items():
            want = {c for c, (show, quiz) in ITEMS["q"].items() if f"{c}?" in quiz}
            have = {k[len("vocab.qq."):] for k in d if k.startswith("vocab.qq.")}
            self.assertEqual(have, want, lang)
            vals = [d[f"vocab.qq.{c}"] for c in want]
            self.assertEqual(len(vals), len(set(vals)), lang)
            self.assertTrue(all(v.rstrip(")").rstrip().endswith("?") for v in vals), lang)
        self.assertIn("vocab.qq.", (WEB / "js" / "vocab.js").read_text())


    def test_quiz_sound(self):
        """0.10.8: the quiz plays the shown code in Morse (checkbox in the quiz); prosigns as one sign known to morse-pro."""
        ui = (WEB / "js" / "vocabui.js").read_text()
        html = (WEB / "index.html").read_text()
        mp = (WEB / "vendor" / "morse-pro" / "morse-pro.js").read_text()
        self.assertIn('id="vocab-sound"', html)
        self.assertIn('id="vocab-replay"', html)
        for code, sign in re.findall(r"(\w+): '(<\w+>)'", re.search(r"const PROSIGNS = \{(.*?)\}", JS).group(1)):  # 0.10.9: moved to vocab.js
            self.assertIn(code, ITEMS["abbr"], code)
            self.assertIn(f"'{sign}'", mp, sign)
        self.assertIn("PROSIGNS[shown]", ui)
        self.assertIn("player, ensureAudio", (WEB / "js" / "main.js").read_text())

if __name__ == "__main__":
    unittest.main()
