# SPDX-License-Identifier: EUPL-1.2
"""0.15.0: firmware of the HW key CwKey (github.com/OK2MTW/morse-key-hw) – the Pi follows the GitHub Releases.

Once a day (and on demand by the administrator) the server asks GitHub for the latest release, downloads its
manifest.json and the UF2 images it names, checks everything (size, SHA-256, every UF2 block: magic, family, address
behind the bootloader) and stores the release in data/fw/<version>/. Browsers take the files only from the Pi (same
origin, no CSP exception, GitHub does not see the users). Only UF2 images are taken – the first installation (-full.bin
over ROM DFU) is done on a PC with the vendor tool. The files are not part of the repository (the images contain the
ST USB library under SLA0044); they are kept as downloaded from the HW project."""
import hashlib
import json
import os
import re
import shutil
import struct
import threading
import time
import urllib.request
from pathlib import Path

from server.db import ROOT

REPO = os.environ.get("MORSE_FW_REPO", "OK2MTW/morse-key-hw")
RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
FW_DIR = Path(os.environ.get("MORSE_FW_DIR", ROOT / "data" / "fw"))
CHECK_EVERY_S = 24 * 3600
FIRST_CHECK_S = 120               # after the service starts
TIMEOUT_S = 30
MAX_FILE = 1024 * 1024            # an F411 has 512 kB of flash – anything bigger is not ours
USER_AGENT = "morse-trainer-fw-sync"

UF2_MAGIC0, UF2_MAGIC1, UF2_MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30
UF2_FLAG_FAMILY = 0x00002000
FLASH_END = {"STM32F411CE": 0x08080000}   # others: F401CC/CD/CE – at most 512 kB too (the CE)
FLASH_END_DEFAULT = 0x08080000

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
FILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}\.uf2$")

LOGIN_GAP_S = 600                 # a login triggers a check at most once in 10 min (GitHub: 60 requests / h without a token)

_lock = threading.Lock()
_state = {"checked_at": None, "error": None}
_auto = {"on": False, "running": False, "last": 0.0}   # on = the service (server/wsgi.py) – never in tests


class FwError(Exception):
    pass


def _int(x):
    return int(x, 0) if isinstance(x, str) else int(x)


def check_uf2(data, family, app_base, flash_end=FLASH_END_DEFAULT):
    """Every 512 B block must be a UF2 block of our family that writes only behind the bootloader. Returns the number
    of blocks; raises FwError otherwise (a wrong image would overwrite the bootloader – TinyUF2 writes anywhere)."""
    if not data or len(data) % 512:
        raise FwError("UF2 size is not a multiple of 512")
    n = len(data) // 512
    for i in range(n):
        b = data[i * 512:(i + 1) * 512]
        m0, m1, flags, addr, size, no, total, fam = struct.unpack_from("<8I", b, 0)
        (end,) = struct.unpack_from("<I", b, 508)
        if m0 != UF2_MAGIC0 or m1 != UF2_MAGIC1 or end != UF2_MAGIC_END:
            raise FwError(f"block {i}: bad magic")
        if not flags & UF2_FLAG_FAMILY or fam != family:
            raise FwError(f"block {i}: wrong family")
        if no != i or total != n:
            raise FwError(f"block {i}: wrong numbering")
        if size == 0 or size > 476 or addr < app_base or addr + size > flash_end:
            raise FwError(f"block {i}: address 0x{addr:08x}+{size} outside the application area")
    return n


def check_manifest(m):
    """The parts of manifest.json the application relies on; returns the clean summary served to browsers."""
    ver = str(m.get("version", ""))
    if not VERSION_RE.match(ver):
        raise FwError("manifest: bad version")
    family = _int(m.get("uf2_family_id", "0"))
    targets = []
    for tg in m.get("targets") or []:
        uf2, drive = tg.get("uf2") or {}, tg.get("bootloader_drive") or {}
        name = str(uf2.get("file", ""))
        if not FILE_RE.match(name) or not re.fullmatch(r"[0-9a-f]{64}", str(uf2.get("sha256", ""))):
            raise FwError("manifest: bad uf2 entry")
        targets.append({
            "mcu": str(tg.get("mcu", ""))[:40], "file": name, "size": int(uf2.get("size", 0)),
            "sha256": uf2["sha256"], "app_base": _int(tg.get("uf2_app_base", "0x08010000")),
            "volume_label": str(drive.get("volume_label", ""))[:40],
            "info_model": str(drive.get("info_model", ""))[:80],
            "info_board_id": str(drive.get("info_board_id", ""))[:80],
        })
    if not targets:
        raise FwError("manifest: no targets")
    for tg in targets:
        if tg["app_base"] < 0x08010000:
            raise FwError("manifest: application base inside the bootloader")
    return {"name": str(m.get("name", "CwKey"))[:40], "version": ver, "family": family, "targets": targets}


def _get(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:    # nosec – a fixed https URL of the HW project
        data = r.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise FwError(f"{url}: too large")
    return data


def releases(fw_dir=None):
    """All stored releases, newest first (summary dict + 'released', 'notes')."""
    d = Path(fw_dir or FW_DIR)
    out = []
    for p in d.glob("*/release.json") if d.is_dir() else []:
        try:
            r = json.loads(p.read_text())
            out.append((tuple(int(x) for x in r["version"].split(".")), r))
        except (OSError, ValueError, KeyError):
            continue
    return [r for _, r in sorted(out, key=lambda x: x[0], reverse=True)]


def current(fw_dir=None):
    """The newest stored release or None."""
    r = releases(fw_dir)
    return r[0] if r else None


def file_path(version, name, fw_dir=None):
    """Path of a stored UF2 image, or None (only names listed in that release)."""
    if not VERSION_RE.match(version or "") or not FILE_RE.match(name or ""):
        return None
    d = Path(fw_dir or FW_DIR) / version
    try:
        r = json.loads((d / "release.json").read_text())
    except (OSError, ValueError):
        return None
    return d / name if any(t["file"] == name for t in r["targets"]) and (d / name).is_file() else None


def sync(get=_get, fw_dir=None):
    """Downloads the latest GitHub release if it is not stored yet. Returns (version, 'new' | 'have')."""
    d = Path(fw_dir or FW_DIR)
    rel = json.loads(get(RELEASE_URL, "application/vnd.github+json"))
    if rel.get("draft") or rel.get("prerelease"):
        raise FwError("latest release is a draft / pre-release")
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets") or []}
    if "manifest.json" not in assets:
        raise FwError("release without manifest.json")
    raw = get(assets["manifest.json"])
    summary = check_manifest(json.loads(raw))
    tag = str(rel.get("tag_name", ""))
    if tag.lstrip("v") != summary["version"]:
        raise FwError(f"tag {tag} does not match manifest {summary['version']}")
    target = d / summary["version"]
    if (target / "release.json").is_file():
        return summary["version"], "have"
    tmp = d / f".{summary['version']}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for tg in summary["targets"]:
            if tg["file"] not in assets:
                raise FwError(f"release without {tg['file']}")
            data = get(assets[tg["file"]])
            if len(data) != tg["size"] or hashlib.sha256(data).hexdigest() != tg["sha256"]:
                raise FwError(f"{tg['file']}: size or SHA-256 does not match the manifest")
            tg["blocks"] = check_uf2(data, summary["family"], tg["app_base"], FLASH_END.get(tg["mcu"], FLASH_END_DEFAULT))
            (tmp / tg["file"]).write_bytes(data)
        (tmp / "manifest.json").write_bytes(raw)
        summary["released"] = str(rel.get("published_at", ""))[:20]
        summary["notes"] = str(rel.get("body") or "")[:4000]
        summary["url"] = str(rel.get("html_url", ""))[:200]
        (tmp / "release.json").write_text(json.dumps(summary, indent=1))
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return summary["version"], "new"


def sync_now():
    """One check with the result remembered for the administrator; never raises."""
    with _lock:
        try:
            ver, how = sync()
            _state.update(checked_at=time.time(), error=None)
            return {"version": ver, "result": how}
        except Exception as e:  # noqa: BLE001 – network, GitHub, a broken release: log and try tomorrow
            _state.update(checked_at=time.time(), error=f"{type(e).__name__}: {e}"[:300])
            return {"error": _state["error"]}


def state():
    return dict(_state)


def check_soon():
    """0.15.2: a login (or the app opened by a logged-in user) asks GitHub for a new release in a background thread –
    never blocks the request; throttled to LOGIN_GAP_S; does nothing outside the service."""
    t = time.time()
    with _lock:
        if not _auto["on"] or _auto["running"] or t - _auto["last"] < LOGIN_GAP_S:
            return False
        _auto.update(running=True, last=t)

    def run():
        try:
            r = sync_now()
            if r.get("result") == "new" or r.get("error"):
                print(f"firmware sync (login): {r}", flush=True)
        finally:
            _auto["running"] = False
    threading.Thread(target=run, name="fw-check", daemon=True).start()
    return True


def start_background():
    """Daily check in a daemon thread (server/wsgi.py only – never in tests); enables the check on login."""
    _auto["on"] = True
    def run():
        time.sleep(FIRST_CHECK_S)
        while True:
            r = sync_now()
            print(f"firmware sync: {r}", flush=True)
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=run, name="fw-sync", daemon=True).start()
