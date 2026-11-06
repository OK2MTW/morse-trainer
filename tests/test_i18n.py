# SPDX-License-Identifier: EUPL-1.2
"""I18N: every language file has the same keys, parameters and plural shape; server language detection."""
import json
import re
import unittest
from pathlib import Path

from server import i18n

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / "web" / "i18n", ROOT / "server" / "i18n"]
PARAM = re.compile(r"\{(\w+)\}")
PLURAL_FORMS = {"cs": {"one", "few", "many", "other"}, "en": {"one", "other"}}


def load(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))
            if p.name != "languages.json"}


def params(v):
    texts = v.values() if isinstance(v, dict) else [v]
    return set().union(*(set(PARAM.findall(x)) for x in texts))


class Dictionaries(unittest.TestCase):
    def test_same_keys_params_and_plurals(self):
        for d in DIRS:
            dicts = load(d)
            self.assertIn("en", dicts, d)
            self.assertIn("cs", dicts, d)
            en = dicts["en"]
            for lang, dd in dicts.items():
                with self.subTest(dir=d.name, lang=lang):
                    self.assertEqual(sorted(set(dd) - set(en)), [], "keys missing in en")
                    self.assertEqual(sorted(set(en) - set(dd)), [], f"keys missing in {lang}")
                    for k, v in dd.items():
                        self.assertIsInstance(v, (str, dict), k)
                        self.assertEqual(isinstance(v, dict), isinstance(en[k], dict), f"plural shape differs: {k}")
                        self.assertEqual(params(v), params(en[k]), f"parameters differ: {k}")
                        if isinstance(v, dict):
                            self.assertIn("n", params(v) | {"n"}, k)
                            self.assertEqual(set(v), PLURAL_FORMS.get(lang, {"other"}) | ({"other"} & set(v)),
                                             f"plural forms of {lang}: {k}")
                        else:
                            self.assertTrue(v.strip(), f"empty text: {k}")

    def test_key_format(self):
        for d in DIRS:
            for k in load(d)["en"]:
                self.assertRegex(k, r"^[a-z][A-Za-z0-9]*(\.[A-Za-z0-9_+-]+)+$", f"{d.name}: {k}")

    def test_languages_list(self):
        langs = json.loads((ROOT / "web" / "i18n" / "languages.json").read_text(encoding="utf-8"))
        codes = [x["code"] for x in langs]
        self.assertEqual(sorted(codes), sorted(load(ROOT / "web" / "i18n")))
        self.assertEqual(sorted(codes), sorted(i18n.LANGS))
        for x in langs:
            self.assertTrue(x["name"])

    def test_web_keys_used_exist(self):
        """Every t('key') / data-i18n="key" in the web code exists in en.json (catches typos)."""
        en = load(ROOT / "web" / "i18n")["en"]
        pat = re.compile(r"""\bt\(\s*'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_+-]+)+)'|data-i18n(?:-html)?="([^"]+)"|data-unit-key=\"([^\"]+)\"""")
        attr = re.compile(r'data-i18n-attr="([^"]+)"')
        missing = []
        for p in list((ROOT / "web").glob("*.html")) + list((ROOT / "web" / "js").glob("*.js")):
            if p.name == "i18n.js":  # the module itself only documents the syntax
                continue
            src = p.read_text(encoding="utf-8")
            keys = [next(x for x in m.groups() if x) for m in pat.finditer(src)]
            keys += [pair.split(":", 1)[1].strip() for m in attr.finditer(src) for pair in m.group(1).split(";")]
            missing += [f"{p.name}: {k}" for k in keys if k not in en]
        self.assertEqual(missing, [])

    def test_server_keys_used_exist(self):
        en = load(ROOT / "server" / "i18n")["en"]
        pat = re.compile(r"""\bt\(\s*["']([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9_+-]+)+)["']""")
        missing = [f"{p.name}: {m.group(1)}" for p in (ROOT / "server").glob("*.py")
                   for m in pat.finditer(p.read_text(encoding="utf-8")) if m.group(1) not in en]
        self.assertEqual(missing, [])


CZECH = re.compile(r"[ěščřžýáíéúůťďňóĚŠČŘŽÝÁÍÉÚŮŤĎŇÓ„“]")
CODE_SUFFIXES = {".py", ".js", ".html", ".css", ".sh", ".conf", ".service", ".webmanifest", ".example"}
# texts live only in the dictionaries; docs/ and README are Czech on purpose, vendor code is third-party
SKIP_DIRS = ("web/i18n/", "server/i18n/", "docs/", "web/vendor/", ".git/", ".venv/", "data/")
DOCSTRING = ('"' * 3, "'" * 3)


def code_files():
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and p.suffix in CODE_SUFFIXES and not rel.startswith(SKIP_DIRS) and "__pycache__" not in rel:
            yield rel, p


class NoCzechInCode(unittest.TestCase):
    """Code (identifiers, comments, logs, CLI) is English; Czech texts only in the i18n dictionaries.
    Tests may use Czech test data in string literals (nicknames, passwords, expected Czech translations),
    but not in comments and docstrings."""

    def test_no_czech_outside_dictionaries(self):
        bad = []
        for rel, p in code_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if not CZECH.search(line):
                    continue
                if rel.startswith("tests/"):
                    comment = line.split("#", 1)[1] if "#" in line else ""
                    if not CZECH.search(comment) and not line.strip().startswith(DOCSTRING):
                        continue
                bad.append(f"{rel}:{i}: {line.strip()[:100]}")
        self.assertEqual(bad, [])


class ServerTranslation(unittest.TestCase):
    def test_fallback_and_params(self):
        with i18n.use_lang("cs"):
            self.assertEqual(i18n.t("no.such.key"), "no.such.key")
            self.assertEqual(i18n.fmt_num(1.5), "1,5")
            self.assertEqual(i18n.fmt_num(2.0), "2")
        with i18n.use_lang("en"):
            self.assertEqual(i18n.fmt_num(1.5), "1.5")
        self.assertEqual(i18n.current(), "en")  # default outside a request

    def test_plural_rules(self):
        cs = i18n.PLURAL["cs"]
        self.assertEqual([cs(1), cs(2), cs(4), cs(5), cs(0), cs(1.5)], ["one", "few", "few", "other", "other", "many"])
        self.assertEqual([i18n.PLURAL["en"](1), i18n.PLURAL["en"](2)], ["one", "other"])

    def test_accept_language(self):
        self.assertEqual(i18n.accept_language("cs-CZ,cs;q=0.9,en;q=0.8"), "cs")
        self.assertEqual(i18n.accept_language("de-DE,en;q=0.5,cs;q=0.4"), "en")
        self.assertEqual(i18n.accept_language("de"), None)
        self.assertEqual(i18n.accept_language(""), None)


if __name__ == "__main__":
    unittest.main()
