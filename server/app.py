# SPDX-License-Identifier: EUPL-1.2
"""Morse trenažer – backend (servíruje frontend + API)."""
import json
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from server import auth, db, site
from server.api import bp as api_bp

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VERSION = "0.8.8"
# Adresy konkrétní instalace nejsou v kódu (E3): server/site.py ← /etc/morse-trainer/site.env
HOME_URL, PUBLIC_URL, PUBLIC_HOSTS = site.HOME_URL, site.PUBLIC_URL, site.PUBLIC_HOSTS

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
db.init_app(app)
app.register_blueprint(api_bp)


@app.before_request
def before():
    auth.check_origin()
    auth.load_session()


@app.after_request
def security_headers(resp):
    if getattr(g, "refresh_cookie", None):
        auth.set_cookie(resp, g.refresh_cookie)
    # Vše hostujeme sami → přísná CSP bez externích zdrojů.
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(403)
def forbidden(_e):
    return jsonify(error="Požadavek odmítnut (jiný původ)."), 403


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="Požadavek je příliš velký."), 413


@app.get("/api/health")
def health():
    return jsonify(status="ok", version=VERSION)


@app.get("/site-config.js")
def site_config():
    """Domácí a venkovní adresa pro web/js/site.js (ES modul, CSP 'self')."""
    js = ("// SPDX-License-Identifier: EUPL-1.2\n// Vygenerováno serverem z /etc/morse-trainer/site.env\n"
          f"export const HOME_URL = {json.dumps(HOME_URL)};\nexport const PUBLIC_URL = {json.dumps(PUBLIC_URL)};\n")
    resp = app.response_class(js, mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html", max_age=0)


@app.get("/<path:path>")
def static_files(path):
    if path.startswith("api/"):
        return jsonify(error="Neznámé API."), 404
    # Service worker musí mít vždy čerstvou verzi, ostatní krátká cache (častý vývoj).
    max_age = 0 if path in ("sw.js", "manifest.webmanifest") else 60
    if path == "manifest.webmanifest" and (auth.is_public() or request.host.split(":")[0] in PUBLIC_HOSTS):
        path = "manifest-venku.webmanifest"  # 0.8.2: venkovní adresa = samostatná aplikace „Morse venku“
    resp = send_from_directory(WEB, path, max_age=max_age)
    if path == "sw.js":
        resp.headers["Service-Worker-Allowed"] = "/"
    return resp


if __name__ == "__main__":  # vývojový běh: python -m server.app
    app.run(host="127.0.0.1", port=8080, debug=False)
