# SPDX-License-Identifier: EUPL-1.2
"""Passwords (argon2id), session cookie, CSRF, roles and limiting login attempts."""
import hashlib
import os
import secrets
import ipaddress
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import abort, current_app, g, jsonify, request

from server.db import get_db
from server.i18n import t

# OWASP minimum for argon2id: m=19 MiB, t=2, p=1. The service has MemoryMax=120M → only one password is hashed at a time.
_cost = int(os.environ.get("MORSE_ARGON2_MEMORY", 19456))
PH = PasswordHasher(time_cost=2, memory_cost=_cost, parallelism=1)
_hash_lock = threading.Semaphore(1)
# Hash for a "non-existent user" so that the answer takes the same time (does not reveal whether a nickname exists).
_DUMMY_HASH = PH.hash(secrets.token_hex(16))

COOKIE = "__Host-sid"  # __Host- = Secure only, Path=/, no Domain
SESSION_DAYS = 90      # sliding – a phone with the PWA should not be logged out all the time
# Roles – stored values (DB, API, links), Czech words: administrator "admin", coach "trener", student "zak".
ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT = "admin", "trener", "zak"
ROLES = (ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT)
PW_MIN, PW_MAX = 10, 32   # E3: password rules (same as web/js/pwrules.js)
LOGIN_PW_MAX = 128        # do not cut a login to PW_MAX (old longer passwords, forced change)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ---------- passwords ----------
def hash_password(pw):
    with _hash_lock:
        return PH.hash(pw)


def verify_password(pw_hash, pw):
    """Returns (ok, new_hash_or_None) – a new hash if the argon2 parameters have changed."""
    with _hash_lock:
        try:
            PH.verify(pw_hash or _DUMMY_HASH, pw)
        except (VerificationError, InvalidHashError):
            return False, None
        if pw_hash is None:
            return False, None
        return True, (PH.hash(pw) if PH.check_needs_rehash(pw_hash) else None)


def password_rules(pw, nick=None):
    """E3: codes of unmet rules (empty = the password is fine). Same as web/js/pwrules.js (RULES[].id)."""
    if not isinstance(pw, str):
        pw = ""
    bad = []
    if not PW_MIN <= len(pw) <= PW_MAX:
        bad.append("length")
    if not any(c.islower() for c in pw):
        bad.append("lower")
    if not any(c.isupper() for c in pw):
        bad.append("upper")
    if not any(c.isdecimal() for c in pw):
        bad.append("digit")
    if not any(not c.isalnum() for c in pw):
        bad.append("special")
    nick = (nick or "").strip().lower()
    if len(nick) >= 3 and nick in pw.lower():
        bad.append("nick")
    return bad


def password_problem(pw, nick=None):
    """Translated message about unmet password rules, or None."""
    bad = password_rules(pw, nick)
    if not bad:
        return None
    rules = ", ".join(t(f"pw.rule.{code}", min=PW_MIN, max=PW_MAX) for code in bad)
    return t("pw.mustHave", rules=rules)


# ---------- limiting attempts (in process memory, in addition to nginx limit_req) ----------
_fails = {}
_bans = {}   # E3: IP → end of the block (monotonic)
_fails_lock = threading.Lock()
FAIL_WINDOW = 15 * 60
# limit by key prefix: nickname strictly (applies even to an attack from many IPs), IP more loosely (shared network)
FAIL_LIMITS = {"nick": 8, "ip": 30, "inv": 20}
BAN_SECONDS = 24 * 3600  # E3: an IP that exhausts the "ip" limit is blocked for 24 h


def client_net(addr=None):
    """0.9.7 (Z-03): key for limiting attempts – IPv4 as is, IPv6 as its /64 block (a mobile network gives the whole block
    to one device, so changing the address inside it must not bypass the limit or the 24 h block)."""
    addr = request.remote_addr if addr is None else addr
    try:
        ip = ipaddress.ip_address(addr or "")
    except ValueError:
        return addr or "?"
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


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
        if len(_fails) > 5000:  # memory protection
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


# ---------- public entry (E3) ----------
PUBLIC_HEADER = "X-Morse-Entry"  # nginx of the public entry (127.0.0.1:8090) sets "public", the client cannot forge it


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
    """Fills g.user and g.session from the cookie (or None)."""
    g.user = g.session = None
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 100:
        return
    db = get_db()
    row = db.execute(
        "SELECT s.*, u.nick, u.role, u.disabled, u.age_group, u.pw_change, u.debug_log, u.news_seen, u.key_lab, u.created_at AS u_created FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.id_hash = ?", (sha256(token),)).fetchone()
    t = now()
    if row is None or row["expires_at"] < iso(t) or row["disabled"]:
        return
    if row["role"] == ROLE_ADMIN and is_public():
        return  # E3: administration only from the home network
    g.session = row
    g.user = {"id": row["user_id"], "nick": row["nick"], "role": row["role"], "age_group": row["age_group"],
              "pw_change": bool(row["pw_change"]), "debug": bool(row["debug_log"]),
              "news_seen": row["news_seen"], "created_at": row["u_created"],
              "key_lab": bool(row["key_lab"]) or row["role"] == ROLE_COACH}
    # sliding validity – written at most once an hour (saves the SD card)
    if row["last_seen"] < iso(t - timedelta(hours=1)):
        db.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE id_hash = ?",
                   (iso(t), iso(t + timedelta(days=SESSION_DAYS)), row["id_hash"]))
        g.refresh_cookie = token


def same_origin():
    """Requests changing data must come from our page (in addition to SameSite=Strict)."""
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # older browsers / curl – protected by the CSRF token and SameSite
    host = request.headers.get("Host", "")
    return origin in (f"https://{host}", f"http://{host}")


# 0.8.1: "not logged in / wrong password" = 403 + {"auth": true}, NOT 401. After a 401 response Chrome drops the stored
# Basic auth password (Pinggy, stage E2) – even when the app sent the 401 – and keeps asking for the domain password.
AUTH_STATUS = 403


def auth_error(msg=None):
    return jsonify(error=msg or t("err.notLoggedIn"), auth=True), AUTH_STATUS


# E3: until the user changes the password (pw_change), only this is allowed
PW_CHANGE_ALLOWED = {"api.change_password", "api.logout", "api.logout_all"}


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return auth_error()
            if g.user["pw_change"] and request.endpoint not in PW_CHANGE_ALLOWED:
                return jsonify(error=t("err.pwChangeFirst"), pw_change=True), 403
            if roles and g.user["role"] not in roles:
                return jsonify(error=t("err.forbidden")), 403
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                sent = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(sent, g.session["csrf"]):
                    return jsonify(error=t("err.csrf")), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def check_origin():
    if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin():
        # 0.9.4: log why (validation #10 – an invitation check was rejected once and the cause was unknown);
        # Origin and Host are not secret, the body (token) is never logged
        current_app.logger.warning("origin rejected: %s %s origin=%r host=%r referer=%r", request.method, request.path,
                                   request.headers.get("Origin"), request.headers.get("Host"),
                                   (request.headers.get("Referer") or "")[:100])
        abort(403)
