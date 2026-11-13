# SPDX-License-Identifier: EUPL-1.2
"""0.14.5: visit counter – how many different visitors came per day, separately for the home network and the public
entry, and how many of them were never logged in (someone who just found the page).

No IP address is stored: a visitor is a short SHA-256 of the address (IPv6 as its /64, like the login limits) with a
random salt of the month. The salts of past months are deleted, so old records cannot be tied to an address any more;
records have no link to an account. 0.14.6: records are kept permanently (statistics since the start) and a short
public summary (today / in total) is shown to everybody, logged in or not. A visit is counted on GET /api/me – every page load
calls it (also logged out and from the cache-first service worker), robots without JavaScript do not."""
import hashlib
import secrets
import threading
from datetime import timedelta

from server.auth import client_net, is_public, now

MAX_DAYS = 3660                             # longest period of the administrator summary
PUBLIC_CACHE_S = 60
ENTRY_LAN, ENTRY_PUBLIC = "lan", "public"   # stored values

_lock = threading.Lock()
_seen = {"day": None, "keys": set()}        # this process has already written these today (saves the SD card)
_public = {"at": None, "data": None}        # cached public summary (every logged-out page load asks for it)


def _salt(db, month):
    row = db.execute("SELECT salt FROM visit_salts WHERE month = ?", (month,)).fetchone()
    if row:
        return row["salt"]
    db.execute("INSERT OR IGNORE INTO visit_salts (month, salt) VALUES (?, ?)", (month, secrets.token_hex(16)))
    db.execute("DELETE FROM visit_salts WHERE month < ?", (month,))
    return db.execute("SELECT salt FROM visit_salts WHERE month = ?", (month,)).fetchone()["salt"]


def record(db, logged):
    """Counts the current request's visitor for today (at most one write per visitor, day and login state)."""
    day = now().strftime("%Y-%m-%d")
    entry = ENTRY_PUBLIC if is_public() else ENTRY_LAN
    net = client_net()
    key = (entry, net, bool(logged))
    with _lock:
        new_day = _seen["day"] != day
        if new_day:
            _seen["day"], _seen["keys"] = day, set()
        if key in _seen["keys"]:
            return
        _seen["keys"].add(key)
    who = hashlib.sha256(f"{_salt(db, day[:7])}|{net}".encode()).hexdigest()[:16]
    db.execute("INSERT INTO visits (day, entry, who, logged) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(day, entry, who) DO UPDATE SET logged = MAX(logged, excluded.logged)",
               (day, entry, who, int(bool(logged))))


def summary(db, days=14):
    """Per day (newest first): different visitors per entry and how many of them never logged in that day,
    plus the totals of the period (a visitor counted once per month, the salt changes with the month)."""
    since = (now() - timedelta(days=max(1, days) - 1)).strftime("%Y-%m-%d")
    rows = {}
    for r in db.execute("SELECT day, entry, COUNT(*) AS n, SUM(logged = 0) AS anon FROM visits WHERE day >= ? "
                        "GROUP BY day, entry", (since,)):
        d = rows.setdefault(r["day"], {"day": r["day"], ENTRY_LAN: [0, 0], ENTRY_PUBLIC: [0, 0]})
        d[r["entry"]] = [r["n"], r["anon"]]
    total = {ENTRY_LAN: [0, 0], ENTRY_PUBLIC: [0, 0]}
    for r in db.execute("SELECT entry, COUNT(*) AS n, SUM(lg = 0) AS anon FROM (SELECT entry, substr(day, 1, 7) AS m, "
                        "who, MAX(logged) AS lg FROM visits WHERE day >= ? GROUP BY entry, m, who) GROUP BY entry",
                        (since,)):
        total[r["entry"]] = [r["n"], r["anon"]]
    return {"days": [rows[k] for k in sorted(rows, reverse=True)], "total": total, "since": since}


def public(db):
    """0.14.6: for everybody – different visitors today and in total since the first record (a visitor counted once
    per day, both entries together). Cached PUBLIC_CACHE_S seconds."""
    t = now()
    with _lock:
        if _public["at"] is not None and 0 <= (t - _public["at"]).total_seconds() < PUBLIC_CACHE_S:
            return _public["data"]
    day = t.strftime("%Y-%m-%d")
    r = db.execute("SELECT COUNT(DISTINCT day || who) AS total, MIN(day) AS since, "
                   "COUNT(DISTINCT CASE WHEN day = ? THEN who END) AS today FROM visits", (day,)).fetchone()
    data = {"today": r["today"] or 0, "total": r["total"] or 0, "since": r["since"] or day}
    with _lock:
        _public.update(at=t, data=data)
    return data
