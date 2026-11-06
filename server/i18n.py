# SPDX-License-Identifier: EUPL-1.2
"""Server-side translations (I18N, 0.9.0).

Texts live in server/i18n/<lang>.json: flat keys "area.key", parameters {name}, plurals as a dict
{"one": …, "few": …, "many": …, "other": …} chosen by parameter n. Fallback: language → en → key.
Adding a language = adding its JSON file (and a plural rule below if it differs from English).

Request language: X-Lang header (sent by web/js/api.js), the "lang" cookie, the user's stored setting,
Accept-Language, otherwise English. Outside a request (tests, CLI) English, or what use_lang() sets.
"""
import contextlib
import contextvars
import json
import re
from pathlib import Path

from flask import g, has_request_context, request

DIR = Path(__file__).with_name("i18n")
DEFAULT = "en"
DICTS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DIR.glob("*.json"))}
LANGS = tuple(sorted(DICTS))
_override = contextvars.ContextVar("i18n_lang", default=None)


def _plural_cs(n):
    if n == 1:
        return "one"
    if isinstance(n, int) or float(n).is_integer():
        return "few" if 2 <= n <= 4 else "other"
    return "many"


def _plural_en(n):
    return "one" if n == 1 else "other"


PLURAL = {"cs": _plural_cs, "en": _plural_en}


def supported(code):
    return isinstance(code, str) and code in DICTS


def accept_language(header):
    """Best supported language from an Accept-Language header (or None)."""
    best, best_q = None, 0.0
    for part in (header or "").split(","):
        bits = part.strip().split(";")
        code = bits[0].strip().lower().split("-")[0]
        q = 1.0
        for b in bits[1:]:
            if b.strip().startswith("q="):
                try:
                    q = float(b.strip()[2:])
                except ValueError:
                    q = 0.0
        if supported(code) and q > best_q:
            best, best_q = code, q
    return best


def _user_lang():
    user = getattr(g, "user", None)
    if not user:
        return None
    from server.db import get_db  # late import: db imports nothing from here, but keep startup light
    row = get_db().execute("SELECT data FROM settings WHERE user_id = ?", (user["id"],)).fetchone()
    try:
        lang = json.loads(row["data"]).get("lang") if row else None
    except ValueError:
        return None
    return lang if supported(lang) else None


def detect():
    """Language of the current request."""
    for code in (request.headers.get("X-Lang", "").strip().lower(), request.cookies.get("lang", "")):
        if supported(code):
            return code
    return _user_lang() or accept_language(request.headers.get("Accept-Language")) or DEFAULT


def current():
    lang = _override.get()
    if lang:
        return lang
    if has_request_context():
        if "lang" not in g:
            g.lang = detect()
        return g.lang
    return DEFAULT


@contextlib.contextmanager
def use_lang(lang):
    """Temporarily translate into lang (tests, CLI)."""
    token = _override.set(lang if supported(lang) else DEFAULT)
    try:
        yield
    finally:
        _override.reset(token)


def fmt_num(x, digits=1):
    """Rounded number with the language's decimal separator, without a trailing .0 (1.5 → "1,5" in Czech)."""
    s = str(round(x, digits))
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(".", t("fmt.decimal"))


def _fmt(v):
    if isinstance(v, float):
        return fmt_num(v, 3)
    return str(v)


def t(key, **params):
    """Translated text for key in the current language."""
    lang = current()
    d = DICTS.get(lang, {})
    if key not in d:
        lang, d = DEFAULT, DICTS.get(DEFAULT, {})
    if key not in d:
        return key
    v = d[key]
    if isinstance(v, dict):
        n = params.get("n", 0)
        v = v.get(PLURAL.get(lang, _plural_en)(n), v.get("other", ""))
    return re.sub(r"\{(\w+)\}", lambda m: _fmt(params[m.group(1)]) if m.group(1) in params else m.group(0), v)
