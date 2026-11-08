# SPDX-License-Identifier: EUPL-1.2
"""Z-19 steps 2+3 (0.10.19): admission control – who already trains keeps the full service, a NEW user over the limit
gets 503 "full" (the client trains offline and syncs later, see web/js/api.js).

Active user = sent any API request within WINDOW_S (the app polls /api/online every 60 s while visible). The register
is in memory only (nothing in the database, empty after a restart) and also gives the online count (0.9.6).
Limits from /etc/morse-trainer/site.env (0 = no limit): MORSE_MAX_ACTIVE for all entries together and a lower
MORSE_MAX_ACTIVE_PUBLIC for the public entry → users in the home network (club room) are never locked out by the
internet. Coach and administrator are never refused. Numbers: docs/kapacita.md.
"""
import random
import threading
import time

from flask import jsonify

from server import site
from server.auth import ROLE_ADMIN, ROLE_COACH
from server.i18n import t

WINDOW_S = 180
EXEMPT_ROLES = (ROLE_ADMIN, ROLE_COACH)
RETRY_MIN_S, RETRY_MAX_S = 30, 90   # Retry-After spread so that refused clients do not come back together


def _limit(name, default):
    try:
        return max(0, int(site.get(name) or default))
    except ValueError:
        return default


MAX_ACTIVE = _limit("MORSE_MAX_ACTIVE", 80)
MAX_ACTIVE_PUBLIC = _limit("MORSE_MAX_ACTIVE_PUBLIC", 40)


class Register:
    def __init__(self, window=WINDOW_S):
        self.window = window
        self._seen = {}            # uid → (last request, came via the public entry)
        self._lock = threading.Lock()

    def _prune(self, at):
        for k in [k for k, (ts, _p) in self._seen.items() if at - ts > self.window]:
            del self._seen[k]

    def clear(self):
        with self._lock:
            self._seen.clear()

    def counts(self, at=None):
        """(all active, active via the public entry)."""
        at = time.monotonic() if at is None else at
        with self._lock:
            self._prune(at)
            return len(self._seen), sum(1 for _ts, p in self._seen.values() if p)

    def seen(self, uid, at=None):
        """CW room (0.13.0): was the user active in the app within the window?"""
        at = time.monotonic() if at is None else at
        with self._lock:
            v = self._seen.get(uid)
            return v is not None and at - v[0] <= self.window

    def touch(self, uid, public, at=None):
        at = time.monotonic() if at is None else at
        with self._lock:
            self._seen[uid] = (at, public)

    def admit(self, uid, role, public, at=None, touch=True, max_all=None, max_public=None):
        """True = may continue (and with touch it is marked active now). uid None = not known yet (login of an
        unknown nick, registration) – checked as a newcomer, never marked."""
        at = time.monotonic() if at is None else at
        max_all = MAX_ACTIVE if max_all is None else max_all
        max_public = MAX_ACTIVE_PUBLIC if max_public is None else max_public
        with self._lock:
            self._prune(at)
            ok = (role in EXEMPT_ROLES or (uid is not None and uid in self._seen)
                  or ((not max_all or len(self._seen) < max_all)
                      and (not public or not max_public
                           or sum(1 for _ts, p in self._seen.values() if p) < max_public)))
            if ok and touch and uid is not None:
                self._seen[uid] = (at, public)
            return ok


active = Register()


def busy_response():
    """503 + Retry-After; `error` is the translated text, `busy` lets the client back off (web/js/api.js)."""
    n, _pub = active.counts()
    retry = random.randint(RETRY_MIN_S, RETRY_MAX_S)
    resp = jsonify(error=t("err.busy", n=n), busy=True, active=n, retry=retry)
    resp.status_code = 503
    resp.headers["Retry-After"] = str(retry)
    return resp
