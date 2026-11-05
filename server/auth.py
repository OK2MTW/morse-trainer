# SPDX-License-Identifier: EUPL-1.2
"""Hesla (argon2id), session cookie, CSRF, role a omezení pokusů o přihlášení."""
import hashlib
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import abort, g, jsonify, request

from server.db import get_db

# OWASP minimum pro argon2id: m=19 MiB, t=2, p=1. Služba má MemoryMax=120M → hashujeme vždy jen jedno heslo naráz.
_cost = int(os.environ.get("MORSE_ARGON2_MEMORY", 19456))
PH = PasswordHasher(time_cost=2, memory_cost=_cost, parallelism=1)
_hash_lock = threading.Semaphore(1)
# Hash pro „neexistujícího uživatele“, aby odpověď trvala stejně dlouho (neprozradí, zda přezdívka existuje).
_DUMMY_HASH = PH.hash(secrets.token_hex(16))

COOKIE = "__Host-sid"  # __Host- = jen Secure, Path=/, bez Domain
SESSION_DAYS = 90      # klouzavě – telefon s PWA nemá být pořád odhlášený
ROLES = ("admin", "trener", "zak")
PW_MIN, PW_MAX = 10, 32   # E3: pravidla hesla (shodně s web/js/pwrules.js)
LOGIN_PW_MAX = 128        # přihlášení nekrátit na PW_MAX (stará delší hesla, vynucená změna)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ---------- hesla ----------
def hash_password(pw):
    with _hash_lock:
        return PH.hash(pw)


def verify_password(pw_hash, pw):
    """Vrátí (ok, nový_hash_nebo_None) – nový hash, pokud se změnily parametry argon2."""
    with _hash_lock:
        try:
            PH.verify(pw_hash or _DUMMY_HASH, pw)
        except (VerificationError, InvalidHashError):
            return False, None
        if pw_hash is None:
            return False, None
        return True, (PH.hash(pw) if PH.check_needs_rehash(pw_hash) else None)


def password_rules(pw, nick=None):
    """E3: seznam nesplněných pravidel (prázdný = heslo vyhovuje). Shodně s web/js/pwrules.js."""
    if not isinstance(pw, str):
        pw = ""
    bad = []
    if not PW_MIN <= len(pw) <= PW_MAX:
        bad.append(f"{PW_MIN} až {PW_MAX} znaků")
    if not any(c.islower() for c in pw):
        bad.append("malé písmeno")
    if not any(c.isupper() for c in pw):
        bad.append("velké písmeno")
    if not any(c.isdecimal() for c in pw):
        bad.append("číslici")
    if not any(not c.isalnum() for c in pw):
        bad.append("speciální znak (např. ! ? - _ . # @)")
    nick = (nick or "").strip().lower()
    if len(nick) >= 3 and nick in pw.lower():
        bad.append("neobsahovat přezdívku")
    return bad


def password_problem(pw, nick=None):
    bad = password_rules(pw, nick)
    return f"Heslo musí mít: {', '.join(bad)}." if bad else None


# ---------- omezení pokusů (v paměti procesu, doplněk k nginx limit_req) ----------
_fails = {}
_bans = {}   # E3: IP → konec blokace (monotonic)
_fails_lock = threading.Lock()
FAIL_WINDOW = 15 * 60
# limit podle předpony klíče: přezdívka přísně (platí i při útoku z mnoha IP), IP volněji (sdílená síť)
FAIL_LIMITS = {"nick": 8, "ip": 30, "inv": 20}
BAN_SECONDS = 24 * 3600  # E3: IP, která vyčerpá limit „ip“, je zablokovaná na 24 h


def too_many(*keys):
    t = time.monotonic()
    with _fails_lock:
        for k in keys:
            ip = "ip:" + k.split(":", 1)[1] if k.startswith(("ip:", "inv:")) else None
            if ip and _bans.get(ip, 0) > t:
                return True
            lst = [x for x in _fails.get(k, []) if t - x < FAIL_WINDOW]
            _fails[k] = lst
            if len(lst) >= FAIL_LIMITS.get(k.split(":", 1)[0], 8):
                return True
    return False


def note_fail(*keys):
    t = time.monotonic()
    with _fails_lock:
        if len(_fails) > 5000:  # ochrana paměti
            _fails.clear()
        if len(_bans) > 5000:
            for k in [k for k, v in _bans.items() if v <= t]:
                del _bans[k]
        for k in keys:
            lst = _fails.setdefault(k, [])
            lst.append(t)
            kind = k.split(":", 1)[0]
            if kind in ("ip", "inv") and len([x for x in lst if t - x < FAIL_WINDOW]) >= FAIL_LIMITS[kind]:
                _bans["ip:" + k.split(":", 1)[1]] = t + BAN_SECONDS


def clear_fails(*keys):
    with _fails_lock:
        for k in keys:
            _fails.pop(k, None)


# ---------- veřejný vstup (E3) ----------
PUBLIC_HEADER = "X-Morse-Entry"  # nginx veřejného vstupu (127.0.0.1:8090) nastaví „public“, klient ho nepodvrhne


def is_public():
    return request.headers.get(PUBLIC_HEADER) == "public"


# ---------- session ----------
def create_session(resp, user_id, device=None):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    t = now()
    db = get_db()
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(t),))
    db.execute(
        "INSERT INTO sessions (id_hash, user_id, csrf, device, created_at, last_seen, expires_at) VALUES (?,?,?,?,?,?,?)",
        (sha256(token), user_id, csrf, device, iso(t), iso(t), iso(t + timedelta(days=SESSION_DAYS))),
    )
    set_cookie(resp, token)
    return csrf


def set_cookie(resp, token):
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, path="/", secure=True,
                    httponly=True, samesite="Strict")


def clear_cookie(resp):
    resp.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Strict")


def load_session():
    """Naplní g.user a g.session podle cookie (nebo None)."""
    g.user = g.session = None
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 100:
        return
    db = get_db()
    row = db.execute(
        "SELECT s.*, u.nick, u.role, u.disabled, u.age_group, u.pw_change FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.id_hash = ?", (sha256(token),)).fetchone()
    t = now()
    if row is None or row["expires_at"] < iso(t) or row["disabled"]:
        return
    if row["role"] == "admin" and is_public():
        return  # E3: správa jen z domácí sítě
    g.session = row
    g.user = {"id": row["user_id"], "nick": row["nick"], "role": row["role"], "age_group": row["age_group"],
              "pw_change": bool(row["pw_change"])}
    # klouzavá platnost – zapisujeme nejvýš jednou za hodinu (šetří SD kartu)
    if row["last_seen"] < iso(t - timedelta(hours=1)):
        db.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE id_hash = ?",
                   (iso(t), iso(t + timedelta(days=SESSION_DAYS)), row["id_hash"]))
        g.refresh_cookie = token


def same_origin():
    """Požadavky měnící data musí přijít z naší stránky (doplněk k SameSite=Strict)."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # starší prohlížeče / curl – chrání CSRF token a SameSite
    host = request.headers.get("Host", "")
    return origin in (f"https://{host}", f"http://{host}")


# 0.8.1: „nepřihlášen / špatné heslo“ = 403 + {"auth": true}, NE 401. Chrome po odpovědi 401 zahodí uložené
# heslo Basic auth (Pinggy, etapa E2) – i když 401 poslala aplikace – a dokola se ptá na heslo k doméně.
AUTH_STATUS = 403


def auth_error(msg="Nejsi přihlášený."):
    return jsonify(error=msg, auth=True), AUTH_STATUS


# E3: dokud si uživatel nezmění heslo (pw_change), smí jen tohle
PW_CHANGE_ALLOWED = {"api.change_password", "api.logout", "api.logout_all"}


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return auth_error()
            if g.user["pw_change"] and request.endpoint not in PW_CHANGE_ALLOWED:
                return jsonify(error="Nejdřív si nastav nové heslo.", pw_change=True), 403
            if roles and g.user["role"] not in roles:
                return jsonify(error="Na tohle nemáš oprávnění."), 403
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                sent = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(sent, g.session["csrf"]):
                    return jsonify(error="Neplatný CSRF token – obnov stránku."), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def check_origin():
    if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin():
        abort(403)
