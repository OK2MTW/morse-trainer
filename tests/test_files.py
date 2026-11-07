# SPDX-License-Identifier: EUPL-1.2
"""Z-18: no stray files in the repository – web/ is served live, so an untracked file there would be public."""
import fnmatch
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORED_OK = (".venv/", "data/*.db", "data/*.db-wal", "data/*.db-shm", "data/*.db-journal", "__pycache__/",
              "*/__pycache__/")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=60)


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "not a git checkout")
class FilesTest(unittest.TestCase):
    def test_no_untracked_files(self):
        out = git("ls-files", "--others", "--exclude-standard").stdout.split()
        self.assertEqual(out, [], "untracked files (git add them or remove them – web/ is public): " + ", ".join(out))

    def test_only_expected_ignored(self):
        out = git("ls-files", "--others", "--ignored", "--exclude-standard", "--directory").stdout.split()
        bad = [p for p in out if not any(fnmatch.fnmatch(p, pat) for pat in IGNORED_OK)]
        self.assertEqual(bad, [], "unexpected ignored files: " + ", ".join(bad))
        self.assertFalse([p for p in out if p.startswith("web/")], "ignored files under web/ would be served")
