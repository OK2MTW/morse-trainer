# SPDX-License-Identifier: EUPL-1.2
"""Z-18c: fingerprint of the deployed files outside git – are /etc copies the same as deploy/ in the repository?

  python -m tools.deployed            compare deployed files with deploy/ (exit 1 on a difference)
  python -m tools.deployed --record   print the manifest of the deployed files (JSON); deploy/install.sh and
                                      deploy/pinggy-setup.sh store it as /etc/morse-trainer/deployed.json

States of a file:
  ok           deployed = what deploy/ would install now
  outdated     deployed = the manifest of the last installation, but deploy/ changed since → run sudo deploy/install.sh
  edited       deployed differs from the manifest → changed by hand after the installation (or a different install)
  differs      differs from deploy/ and there is no manifest to tell why
  missing      not deployed (optional files only as a note)
Also: the running service version vs. server/app.py (restart needed?) and systemd NeedDaemonReload.
Everything checked is world-readable – no root needed. Private keys and pinggy.env are never read.
"""
import argparse
import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
ETC = Path("/etc")
MANIFEST = "morse-trainer/deployed.json"   # relative to ETC


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render_unit(text, root=ROOT):
    """The same substitution as install_unit in deploy/common.sh (@USER@ = owner of the directory)."""
    owner = pwd.getpwuid(root.stat().st_uid)
    return (text.replace("@USER@", owner.pw_name).replace("@DIR@", str(root))
            .replace("@HOME@", owner.pw_dir))


def public_host(site_env_text):
    """PUBLIC_HOST as load_site_env in deploy/common.sh derives it from MORSE_PUBLIC_URL."""
    m = re.search(r"^MORSE_PUBLIC_URL=(.*)$", site_env_text, re.M)
    url = m.group(1).strip() if m else ""
    return re.split(r"[:/]", re.sub(r"^https?://", "", url), maxsplit=1)[0]


def targets(root=ROOT, etc=ETC):
    """(deployed path, expected bytes or None when it cannot be derived, optional) for every deployed file."""
    dep = root / "deploy"
    out = [
        (etc / "systemd/system/morse-trainer.service",
         render_unit((dep / "morse-trainer.service").read_text(encoding="utf-8"), root).encode(), False),
        (etc / "systemd/system/morse-pinggy.service",
         render_unit((dep / "morse-pinggy.service").read_text(encoding="utf-8"), root).encode(), True),
        (etc / "nginx/sites-available/morse-trainer", (dep / "nginx-morse-trainer.conf").read_bytes(), False),
        (etc / "morse-trainer/pinggy-proxy.conf", (dep / "pinggy-proxy.conf").read_bytes(), False),
    ]
    site_env = etc / "morse-trainer/site.env"
    host_map = None
    if site_env.is_file():
        host = public_host(site_env.read_text(encoding="utf-8"))
        host_map = (f"{host} 1;\n" if host else "").encode()
    out.append((etc / "morse-trainer/pinggy-host.map", host_map, False))
    return out


def read(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def git_state(root=ROOT):
    def run(*args):
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    return {"commit": run("rev-parse", "--short", "HEAD"),
            "dirty": bool(run("status", "--porcelain", "--", "deploy"))}


def record(root=ROOT, etc=ETC):
    files = {}
    for path, _expected, _opt in targets(root, etc):
        data = read(path)
        if data is not None:
            files[str(path)] = sha(data)
    return {"version": 1, **git_state(root), "files": files}


def file_state(deployed, expected, manifest_sha, optional):
    if deployed is None:
        return "missing-optional" if optional else "missing"
    if expected is not None and deployed == expected:
        return "ok"
    if manifest_sha is None:
        return "differs"
    if sha(deployed) != manifest_sha:
        return "edited"
    return "outdated"


def check(root=ROOT, etc=ETC):
    """List of (path, state); also the links nginx needs."""
    try:
        manifest = json.loads((etc / MANIFEST).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        manifest = None
    known = (manifest or {}).get("files", {})
    res = []
    for path, expected, optional in targets(root, etc):
        st = file_state(read(path), expected, known.get(str(path)) if manifest else None, optional)
        res.append((str(path), st))
    enabled = etc / "nginx/sites-enabled/morse-trainer"
    ok_link = enabled.is_symlink() and os.readlink(enabled) == str(etc / "nginx/sites-available/morse-trainer")
    res.append((str(enabled), "ok" if ok_link else "not-linked"))
    default = etc / "nginx/sites-enabled/default"
    res.append((str(default), "ok" if not default.exists() and not default.is_symlink() else "present"))
    return manifest, res


def app_version(root=ROOT):
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / "server/app.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def running_version(url="http://127.0.0.1:8080/api/health"):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.load(r).get("version")
    except (OSError, ValueError):
        return None


def need_daemon_reload(unit="morse-trainer"):
    try:
        r = subprocess.run(["systemctl", "show", unit, "-p", "NeedDaemonReload", "--value"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() == "yes" if r.returncode == 0 else None


HINT = {
    "outdated": "deploy/ changed since the installation → sudo deploy/install.sh",
    "edited": "changed by hand after the installation – compare with deploy/ (diff) before install.sh overwrites it",
    "differs": "differs from deploy/ (no manifest yet – sudo deploy/install.sh records one)",
    "missing": "not deployed → sudo deploy/install.sh",
    "missing-optional": "not deployed (optional)",
    "not-linked": "nginx site not enabled → sudo deploy/install.sh",
    "present": "default nginx site enabled → sudo deploy/install.sh removes it",
}
FAIL = {"outdated", "edited", "differs", "missing", "not-linked", "present"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record", action="store_true", help="print the manifest of the deployed files (JSON)")
    a = ap.parse_args(argv)
    if a.record:
        print(json.dumps(record(), indent=1, sort_keys=True))
        return 0
    manifest, res = check()
    bad = False
    if manifest:
        print(f"manifest: commit {manifest.get('commit') or '?'}{' (deploy/ dirty)' if manifest.get('dirty') else ''}")
    else:
        print("manifest: none (/etc/" + MANIFEST + ")")
    for path, st in res:
        bad |= st in FAIL
        print(f"  {st:16} {path}" + (f"  – {HINT[st]}" if st in HINT else ""))
    want, run = app_version(), running_version()
    if run is None:
        print(f"  {'not-running':16} service (repo {want})")
        bad = True
    elif run != want:
        print(f"  {'old-version':16} service runs {run}, repo {want} → restart (or install.sh if deploy/ changed)")
        bad = True
    else:
        print(f"  {'ok':16} service {run}")
    if need_daemon_reload():
        print(f"  {'daemon-reload':16} systemd unit changed on disk but not reloaded → sudo deploy/install.sh")
        bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
