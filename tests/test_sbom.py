# SPDX-License-Identifier: EUPL-1.2
"""Z-18: the SBOM (sbom.cdx.json) matches the installed components, licences are EUPL-compatible, credits are complete."""
import json
import re
import unittest
from pathlib import Path

from tools import sbom

ROOT = Path(__file__).resolve().parent.parent


class SbomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items, cls.problems = sbom.collect()
        cls.names = {c["name"].lower() for c, _, _ in cls.items}

    def test_licences_compatible(self):
        self.assertEqual(self.problems, [])

    def test_licence_expressions(self):
        self.assertTrue(sbom.licence_ok("BSD-3-Clause OR Apache-2.0"))
        self.assertFalse(sbom.licence_ok("GPL-3.0-only"))
        self.assertFalse(sbom.licence_ok("MIT AND GPL-3.0-only"))
        self.assertFalse(sbom.licence_ok(None))

    def test_requirements_and_imports_present(self):
        for req in ("flask", "waitress", "argon2-cffi", "werkzeug", "jinja2", "pycparser", "morse-pro", "nginx"):
            self.assertIn(req, self.names)
        self.assertNotIn("setuptools", self.names)  # start-up .pth hook, not a dependency

    def test_file_up_to_date(self):
        text = sbom.build(self.items)
        self.assertEqual((ROOT / "sbom.cdx.json").read_text(encoding="utf-8"), text,
                         "sbom.cdx.json is out of date – run: .venv/bin/python -m tools.sbom --write")
        doc = json.loads(text)
        self.assertEqual((doc["bomFormat"], doc["specVersion"]), ("CycloneDX", "1.5"))
        self.assertNotIn(str(Path.home()), text)  # no local paths

    def test_credits_complete(self):
        """Every component is named in README.md and on the About page (CLAUDE.md: licences of dependencies)."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        about = re.sub(r"<[^>]+>", " ", (ROOT / "web" / "o-aplikaci.html").read_text(encoding="utf-8")).lower()
        for c, lic, _ in self.items:
            n = c["name"].lower()
            self.assertIn(n, readme, f"README.md does not credit {c['name']}")
            self.assertIn(n, about, f"o-aplikaci.html does not credit {c['name']}")
            if lic and lic not in ("blessing",):
                self.assertIn(lic.lower(), readme, f"README.md lacks the licence {lic} of {c['name']}")
