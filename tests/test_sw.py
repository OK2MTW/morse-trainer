# SPDX-License-Identifier: EUPL-1.2
"""Service worker (0.9.7, Z-08): the cache-first app must not get stuck on an old version or miss a file offline."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import swhash  # noqa: E402

# the version is read from the source – importing server.app would open a database (tests must not touch the live one)
VERSION = re.search(r'VERSION = "([^"]+)"', (Path(__file__).resolve().parent.parent / "server" / "app.py").read_text()).group(1)


class ServiceWorkerTest(unittest.TestCase):
    def test_hash_up_to_date(self):
        self.assertEqual(swhash.current_hash(), swhash.stored_hash(),
                         "web/ changed – run: python3 tests/swhash.py --write")

    def test_version_matches_server(self):
        self.assertIn(f"const VERSION = '{VERSION}';", swhash.SW.read_text())

    def test_assets_complete(self):
        """Every module, translation and vendor script is cached – a missing one breaks the app offline."""
        listed = set(swhash.assets())
        web = swhash.WEB
        need = {"/" + str(p.relative_to(web)) for pat in ("js/*.js", "i18n/*.json", "vendor/morse-pro/*.js", "css/*.css")
                for p in web.glob(pat)}
        self.assertEqual(need - listed, set())
        for p in listed - swhash.NOT_FILES:
            self.assertTrue((web / p.lstrip("/")).is_file(), p)

    def test_imports_are_listed(self):
        """Static imports between modules point only to cached files."""
        listed = set(swhash.assets())
        for f in (swhash.WEB / "js").glob("*.js"):
            for imp in re.findall(r"^import [^;]*? from '([^']+)';", f.read_text(), re.M):
                path = imp if imp.startswith("/") else "/" + str((Path("/js") / imp).resolve().relative_to("/"))
                self.assertIn(path, listed, f"{f.name} imports {imp}")


if __name__ == "__main__":
    unittest.main()
