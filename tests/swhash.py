# SPDX-License-Identifier: EUPL-1.2
"""Hash of the service worker ASSETS (0.9.7, Z-08). The app files are served "cache first", so sw.js must change
whenever any of them changes – otherwise browsers keep the old version.

    python3 tests/swhash.py           prints the current and the stored hash
    python3 tests/swhash.py --write   stores the current hash in web/sw.js (run after every frontend change)
"""
import hashlib
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SW = WEB / "sw.js"
# served by the server (not files in web/) or an alias of index.html
NOT_FILES = {"/", "/site-config.js"}


def assets(sw_text=None):
    text = sw_text if sw_text is not None else SW.read_text()
    block = re.search(r"const ASSETS = \[(.*?)\];", text, re.S).group(1)
    return re.findall(r"'([^']+)'", block)


def current_hash(sw_text=None):
    h = hashlib.sha256()
    for p in sorted(set(assets(sw_text)) - NOT_FILES):
        h.update(p.encode() + b"\0" + (WEB / p.lstrip("/")).read_bytes() + b"\0")
    return h.hexdigest()[:8]


def stored_hash(sw_text=None):
    text = sw_text if sw_text is not None else SW.read_text()
    return re.search(r"const ASSETS_HASH = '([0-9a-f]+)';", text).group(1)


if __name__ == "__main__":
    text = SW.read_text()
    cur, old = current_hash(text), stored_hash(text)
    if "--write" in sys.argv[1:]:
        if cur != old:
            SW.write_text(text.replace(f"const ASSETS_HASH = '{old}';", f"const ASSETS_HASH = '{cur}';"))
        print(f"sw.js ASSETS_HASH = {cur}" + ("" if cur != old else " (unchanged)"))
    else:
        print(f"current {cur}, stored {old}" + ("" if cur == old else "  → run with --write"))
        sys.exit(0 if cur == old else 1)
