# SPDX-License-Identifier: EUPL-1.2
"""Z-18: software bill of materials (CycloneDX 1.5 JSON) of what the installation really runs – standard library only.

  python -m tools.sbom            summary + licence check (exit 1 on a problem)
  python -m tools.sbom --write    write sbom.cdx.json (deterministic: no timestamp, serial number from the content)
  python -m tools.sbom --check    exit 1 when sbom.cdx.json is out of date or a licence is not compatible with EUPL-1.2

Components:
- Python packages the server really imports (server.wsgi + server.admin in a subprocess with a temporary database) plus
  requirements.txt with their declared dependencies; real installed versions, origin venv (pip) or Debian (apt package).
- vendored morse-pro (commit from ZDROJ.txt, SHA-256 of every file),
- system components: Python, SQLite library, OpenSSL, nginx (dpkg).
"""
import hashlib
import importlib.metadata as md
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sbom.cdx.json"
VENDOR = ROOT / "web" / "vendor" / "morse-pro"

# Licences compatible with EUPL-1.2 for use in this project (CLAUDE.md: MIT/BSD/Apache/OFL/LGPL…; EUPL appendix).
ALLOWED = {"MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ZPL-2.1", "PSF-2.0", "ISC", "blessing",
           "EUPL-1.2", "MPL-2.0", "LGPL-2.1-or-later", "LGPL-3.0-or-later", "CC0-1.0", "Unlicense", "OFL-1.1"}
# Free-text licence fields of package metadata → SPDX (only values seen in practice; unknown = a problem to look at)
LICENSE_TEXT = {"mit": "MIT", "mit license": "MIT", "mit-0": "MIT-0", "bsd-3-clause": "BSD-3-Clause",
                "bsd 3-clause": "BSD-3-Clause", "bsd-2-clause": "BSD-2-Clause", "zpl 2.1": "ZPL-2.1",
                "zpl-2.1": "ZPL-2.1", "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0",
                "apache license, version 2.0": "Apache-2.0", "psf": "PSF-2.0", "isc": "ISC", "mpl-2.0": "MPL-2.0"}
CLASSIFIER = {"License :: OSI Approved :: MIT License": "MIT",
              "License :: OSI Approved :: Apache Software License": "Apache-2.0",
              "License :: OSI Approved :: Zope Public License": "ZPL-2.1",
              "License :: OSI Approved :: ISC License (ISCL)": "ISC"}
# Imported at interpreter start-up by .pth hooks – not dependencies of the application
STARTUP_ONLY = {"setuptools", "logilab-common"}

PROBE = """
import importlib.metadata as md, json, sys
before = set(sys.modules)
sys.path.insert(0, sys.argv[1])
import server.wsgi, server.admin  # noqa: F401 – the production entry point and the admin CLI
pd = md.packages_distributions()
mods = {m.split('.')[0] for m in set(sys.modules) - before}
print(json.dumps(sorted({d for m in mods for d in pd.get(m, [])})))
"""


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def imported_dists():
    """Distributions whose modules the server imports (run in a subprocess, never against the live database)."""
    tmp = tempfile.mkdtemp(prefix="sbom-")
    try:
        env = {**os.environ, "MORSE_DB": str(Path(tmp) / "probe.db")}
        out = subprocess.run([sys.executable, "-I", "-c", PROBE, str(ROOT)], capture_output=True, text=True,
                             env=env, cwd=tmp, timeout=120, check=True).stdout
        return {norm(d) for d in json.loads(out.strip().splitlines()[-1])} - STARTUP_ONLY
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def required_dists():
    """requirements.txt + declared dependencies (without extras and markers that are false here)."""
    req = [re.split(r"[<>=!~;\s\[]", ln.strip())[0] for ln in (ROOT / "requirements.txt").read_text().splitlines()
           if ln.strip() and not ln.lstrip().startswith("#")]
    seen, todo = set(), [norm(r) for r in req]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        try:
            d = md.distribution(n)
        except md.PackageNotFoundError:
            continue
        seen.add(n)
        for r in d.requires or []:
            name, _, marker = r.partition(";")
            if "extra" in marker or not _marker(marker):
                continue
            todo.append(norm(re.split(r"[<>=!~\s\[(]", name.strip())[0]))
    return seen


def _marker(marker):
    """The simple environment markers seen in practice (python_version, implementation_name, platform_system, sys_platform)."""
    import platform
    ok = True
    for m in re.finditer(r'python_version\s*(<|>=|<=|>|==|!=)\s*"([0-9.]+)"', marker):
        have, want = sys.version_info[:2], tuple(int(x) for x in m.group(2).split(".")[:2])
        ok &= {"<": have < want, ">=": have >= want, "<=": have <= want, ">": have > want, "==": have == want,
               "!=": have != want}[m.group(1)]
    env = {"implementation_name": sys.implementation.name, "platform_system": platform.system(),
           "sys_platform": sys.platform}
    for m in re.finditer(r'(implementation_name|platform_system|sys_platform)\s*(==|!=)\s*"([^"]*)"', marker):
        same = env[m.group(1)].lower() == m.group(3).lower()
        ok &= same if m.group(2) == "==" else not same
    return ok


def spdx(d):
    """SPDX licence of a distribution from its metadata (None = unknown)."""
    expr = d.metadata.get("License-Expression")
    if expr:
        return expr.strip()
    txt = (d.metadata.get("License") or "").strip().lower()
    if txt in LICENSE_TEXT:
        return LICENSE_TEXT[txt]
    for c in d.metadata.get_all("Classifier") or []:
        if c in CLASSIFIER:
            return CLASSIFIER[c]
    return None


def dpkg_owner(path):
    """Debian package (name, version) owning a path, or None."""
    try:
        own = subprocess.run(["dpkg-query", "-S", str(path)], capture_output=True, text=True, timeout=30)
        if own.returncode:
            return None
        pkg = own.stdout.split(":", 1)[0].strip()
        ver = subprocess.run(["dpkg-query", "-W", "-f=${Version}", pkg], capture_output=True, text=True, timeout=30)
        return (pkg, ver.stdout.strip()) if ver.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def python_component(name):
    d = md.distribution(name)
    path = Path(str(d._path))  # noqa: SLF001 – the only way to the metadata location in importlib.metadata
    # installed by pip into the running virtual environment (not the Debian system site-packages)
    venv = sys.prefix != sys.base_prefix and str(path).startswith(sys.prefix)
    comp = {"type": "library", "name": d.metadata["Name"], "version": d.version,
            "purl": f"pkg:pypi/{norm(d.metadata['Name'])}@{d.version}"}
    lic = spdx(d)
    props = [{"name": "morse:source", "value": "venv (pip)" if venv else "system (Debian)"}]
    if not venv:
        own = dpkg_owner(path)
        if own:
            props.append({"name": "morse:deb", "value": f"{own[0]} {own[1]}"})
    return comp, lic, props


def system_components():
    import platform
    import sqlite3
    import ssl
    out = [({"type": "platform", "name": "python", "version": platform.python_version(),
             "purl": f"pkg:generic/python@{platform.python_version()}"}, "PSF-2.0"),
           ({"type": "library", "name": "sqlite", "version": sqlite3.sqlite_version,
             "purl": f"pkg:generic/sqlite@{sqlite3.sqlite_version}"}, "blessing")]
    m = re.match(r"OpenSSL (\S+)", ssl.OPENSSL_VERSION)
    if m:
        out.append(({"type": "library", "name": "openssl", "version": m.group(1),
                     "purl": f"pkg:generic/openssl@{m.group(1)}"}, "Apache-2.0"))
    try:
        r = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "nginx"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            v = r.stdout.strip()
            out.append(({"type": "application", "name": "nginx", "version": v, "purl": f"pkg:deb/debian/nginx@{v}"},
                        "BSD-2-Clause"))
    except (OSError, subprocess.SubprocessError):
        pass
    return [(c, lic, [{"name": "morse:source", "value": "system"}]) for c, lic in out]


def vendor_component():
    src = (VENDOR / "ZDROJ.txt").read_text(encoding="utf-8")
    m = re.search(r"(https://github\.com/[\w.-]+/[\w.-]+) @ ([0-9a-f]{7,40})", src)
    lic_text = (VENDOR / "LICENSE").read_text(encoding="utf-8", errors="replace")
    lic = "EUPL-1.2" if "EUROPEAN UNION PUBLIC LICENCE" in lic_text.upper() and "1.2" in lic_text else None
    files = sorted(p for p in VENDOR.iterdir() if p.is_file())
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    comp = {"type": "library", "name": "morse-pro", "version": m.group(2) if m else "unknown",
            "purl": f"pkg:github/scp93ch/morse-pro@{m.group(2)}" if m else None,
            "hashes": [{"alg": "SHA-256", "content": h.hexdigest()}],
            "externalReferences": [{"type": "vcs", "url": m.group(1)}] if m else []}
    props = [{"name": "morse:source", "value": "vendored (web/vendor/morse-pro)"},
             {"name": "morse:modified", "value": "yes – see ZDROJ.txt"}]
    props += [{"name": f"morse:file:{p.name}", "value": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    return comp, lic, props


def app_version():
    return re.search(r'^VERSION = "([^"]+)"', (ROOT / "server" / "app.py").read_text(), re.M).group(1)


def collect():
    """[(component, spdx licence or None, properties)] sorted, problems []."""
    names = sorted(imported_dists() | required_dists())
    items = [python_component(n) for n in names] + [vendor_component()] + system_components()
    items.sort(key=lambda x: (x[0]["type"], x[0]["name"].lower()))
    problems = [f"{c['name']} {c['version']}: licence {lic or 'unknown'} is not on the EUPL-compatible list"
                for c, lic, _ in items if not licence_ok(lic)]
    return items, problems


def licence_ok(expr):
    if not expr:
        return False
    if " OR " in expr:
        return any(licence_ok(x.strip("() ")) for x in expr.split(" OR "))
    if " AND " in expr:
        return all(licence_ok(x.strip("() ")) for x in expr.split(" AND "))
    return expr.strip("() ") in ALLOWED


def build(items):
    comps = []
    for c, lic, props in items:
        comp = {k: v for k, v in c.items() if v not in (None, [])}
        comp["bom-ref"] = comp.get("purl") or f"{c['name']}@{c['version']}"
        comp["licenses"] = [{"expression": lic}] if lic and (" OR " in lic or " AND " in lic) else \
            [{"license": {"id": lic}}] if lic else []
        comp["properties"] = props
        comps.append(comp)
    ver = app_version()
    root_ref = f"pkg:github/OK2MTW/morse-trainer@{ver}"
    doc = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {
            "tools": {"components": [{"type": "application", "name": "tools.sbom (morse-trainer)", "version": ver}]},
            "component": {"type": "application", "name": "morse-trainer", "version": ver, "bom-ref": root_ref,
                          "purl": root_ref, "licenses": [{"license": {"id": "EUPL-1.2"}}]},
        },
        "components": comps,
        "dependencies": [{"ref": root_ref, "dependsOn": [c["bom-ref"] for c in comps]}],
    }
    body = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    doc["serialNumber"] = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, body)}"
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    items, problems = collect()
    text = build(items)
    for c, lic, props in items:
        src = next((p["value"] for p in props if p["name"] == "morse:source"), "")
        print(f"{c['name']:24} {c['version']:22} {lic or '?':28} {src}")
    for p in problems:
        print("PROBLEM:", p)
    if "--write" in argv:
        OUT.write_text(text, encoding="utf-8")
        print(f"written {OUT.relative_to(ROOT)}")
    if "--check" in argv and (not OUT.exists() or OUT.read_text(encoding="utf-8") != text):
        print("sbom.cdx.json is out of date – run: .venv/bin/python -m tools.sbom --write")
        return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
