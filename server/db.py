# SPDX-License-Identifier: EUPL-1.2
"""SQLite: a connection per request, schema and migrations via PRAGMA user_version."""
import os
import sqlite3
import sys
from pathlib import Path

from flask import g

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MORSE_DB", ROOT / "data" / "morse.db"))

# Each item = one migration (index + 1 = user_version). Never change the statements, only append.
# (I18N 0.9.0: only the SQL comments were translated to English.)
MIGRATIONS = [
    """
    CREATE TABLE users (
        id            INTEGER PRIMARY KEY,
        nick          TEXT NOT NULL UNIQUE COLLATE NOCASE,
        pw_hash       TEXT NOT NULL,
        role          TEXT NOT NULL CHECK (role IN ('admin', 'trener', 'zak')),
        age_group     TEXT CHECK (age_group IN ('do15', '15-17', '18-59', '60+')),
        parent_consent_at TEXT,            -- only for children under 15
        created_at    TEXT NOT NULL,
        last_login_at TEXT,
        disabled      INTEGER NOT NULL DEFAULT 0,
        invited_by    INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE invites (
        id          INTEGER PRIMARY KEY,
        token_hash  TEXT NOT NULL UNIQUE,  -- SHA-256 of the token, the token itself is not stored
        role        TEXT NOT NULL CHECK (role IN ('admin', 'trener', 'zak')),
        note        TEXT,                  -- for whom (seen only by admin/coach)
        created_by  INTEGER REFERENCES users(id) ON DELETE CASCADE,
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL,
        used_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
        used_at     TEXT
    );
    CREATE TABLE sessions (
        id_hash    TEXT PRIMARY KEY,       -- SHA-256 hodnoty cookie
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf       TEXT NOT NULL,
        device     TEXT,                   -- 'mobil' (phone) / 'pc' (only for the overview of logins)
        created_at TEXT NOT NULL,
        last_seen  TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX sessions_user ON sessions(user_id);
    CREATE TABLE settings (
        user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        data       TEXT NOT NULL,          -- JSON
        updated_at TEXT NOT NULL
    );
    CREATE TABLE progress (
        user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        level      INTEGER NOT NULL,
        introduced TEXT NOT NULL,          -- JSON array of characters
        updated_at TEXT NOT NULL
    );
    CREATE TABLE lessons (
        id        INTEGER PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL,           -- UUID from the browser → sending again is harmless
        at        TEXT NOT NULL,
        device    TEXT,
        level     INTEGER NOT NULL,
        dur_s     INTEGER,
        trials    INTEGER NOT NULL,
        correct   INTEGER NOT NULL,
        acc       REAL,
        ttr       INTEGER,
        wpm       INTEGER,
        fwpm      INTEGER,
        detail    TEXT,                    -- JSON: per-character statistics, confusions (for M3)
        UNIQUE (user_id, client_id)
    );
    CREATE INDEX lessons_user_at ON lessons(user_id, at);
    """,
    # 2: training reset counter – a device with an older value must not upload old progress or lessons
    """
    ALTER TABLE users ADD COLUMN train_epoch INTEGER NOT NULL DEFAULT 0
    """,
    # 3 (M4): questionnaire result (without answers – only archetype, modifiers, preferences) and the reached level U1–U6
    """
    CREATE TABLE coach (
        user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        archetype   TEXT,
        modifiers   TEXT NOT NULL DEFAULT '[]',
        prefs       TEXT NOT NULL DEFAULT '{}',
        answered_at TEXT,
        ulevel      INTEGER NOT NULL DEFAULT 1,
        ulevel_at   TEXT,
        updated_at  TEXT NOT NULL
    )
    """,
    # 4 (M7): lesson mode – 'znak' (character: waits for an answer, TTR) / 'skluz' (copy behind: a stream, scored by alignment)
    """
    ALTER TABLE lessons ADD COLUMN mode TEXT NOT NULL DEFAULT 'znak'
    """,
    # 5 (E3): password rules – existing accounts must change their password (pw_change = 1), a new-password link
    # = an invitation with reset_user (the training stays)
    """
    ALTER TABLE users ADD COLUMN pw_change INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE invites ADD COLUMN reset_user INTEGER REFERENCES users(id) ON DELETE CASCADE
    """,
    # 6 (V1): debug trace of the training – only for accounts with debug_log = 1 (enabled by the admin), deleted after 180 days
    """
    ALTER TABLE users ADD COLUMN debug_log INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE traces (
        id        INTEGER PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        lesson_id TEXT,                    -- client_id of the lesson (lessons.client_id), NULL for an aborted lesson
        kind      TEXT NOT NULL,           -- znak / skluz
        at        TEXT NOT NULL,           -- start of the lesson (client time)
        received  TEXT NOT NULL,
        data      TEXT NOT NULL            -- JSON: meta + events [t_ms, type, data]
    );
    CREATE INDEX traces_user_at ON traces (user_id, at);
    CREATE TABLE client_errors (
        id       INTEGER PRIMARY KEY,
        user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        at       TEXT NOT NULL,
        received TEXT NOT NULL,
        data     TEXT NOT NULL             -- JSON: message, source, line, stack, version, view
    )
    """,
    # 7 (0.9.3): what's new – the id of the last news entry the user has dismissed (contents live in web/js/news.js)
    """
    ALTER TABLE users ADD COLUMN news_seen INTEGER NOT NULL DEFAULT 0
    """,
    # 8 (0.9.5): test account – synthetic history and reset by the CLI are allowed only here (protects real accounts)
    """
    ALTER TABLE users ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0
    """,
    # 9 (0.10.0): vocabulary – abbreviations, Q codes and call sign prefixes (list = abbr / q / pfx), per item counts
    # and the sessions (multiple choice, no time limit)
    """
    CREATE TABLE vocab (
        user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        list     TEXT NOT NULL CHECK (list IN ('abbr', 'q', 'pfx')),
        code     TEXT NOT NULL,
        n        INTEGER NOT NULL DEFAULT 0,
        wrong    INTEGER NOT NULL DEFAULT 0,
        last_ok  INTEGER,               -- the last answer was right (1) / wrong (0)
        last_at  TEXT,
        PRIMARY KEY (user_id, list, code)
    );
    CREATE TABLE vocab_sessions (
        id        INTEGER PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL,
        at        TEXT NOT NULL,
        lists     TEXT NOT NULL,         -- e.g. "abbr,q"
        dur_s     INTEGER,
        n         INTEGER NOT NULL,
        wrong     INTEGER NOT NULL,
        detail    TEXT,                  -- JSON {list: [n, wrong]}
        UNIQUE (user_id, client_id)
    );
    CREATE INDEX vocab_sessions_user_at ON vocab_sessions (user_id, at)
    """,
    # 10 (0.13.0): trainer groups and the CW room – a trainer sorts students (and invitations) into groups; deleting
    # a group keeps its students. The trainer switches the room off for a student (cw_off) and on for the children
    # of their groups (cw_kids); blocks between users are permanent (nothing else of the room is stored)
    """
    CREATE TABLE coach_groups (
        id         INTEGER PRIMARY KEY,
        coach_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name       TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (coach_id, name)
    );
    ALTER TABLE users ADD COLUMN group_id INTEGER REFERENCES coach_groups(id) ON DELETE SET NULL;
    ALTER TABLE invites ADD COLUMN group_id INTEGER REFERENCES coach_groups(id) ON DELETE SET NULL;
    ALTER TABLE users ADD COLUMN cw_off INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN cw_kids INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE cw_blocks (
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, blocked_id)
    )
    """,
    # 11 (0.14.4): the trainer opens the telegraph key page (key lab) to one student – otherwise coaches only
    """
    ALTER TABLE users ADD COLUMN key_lab INTEGER NOT NULL DEFAULT 0
    """,
    # 12 (0.14.5): visit counter (server/visits.py) – a salted hash of the address per day and entry, no IP, no account
    """
    CREATE TABLE visits (
        day    TEXT NOT NULL,             -- YYYY-MM-DD (UTC)
        entry  TEXT NOT NULL,             -- 'lan' | 'public'
        who    TEXT NOT NULL,             -- SHA-256(salt of the month | address)[:16]
        logged INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, entry, who)
    );
    CREATE TABLE visit_salts (
        month TEXT PRIMARY KEY,           -- YYYY-MM
        salt  TEXT NOT NULL
    )
    """,
]


def connect(path=None):
    path = Path(path or DB_PATH)
    # 2026-11-07: a partial test run once wrote test accounts into the live database (a test module imported the app
    # before another one set MORSE_DB). Tests must never touch the real database, whatever the order of imports.
    if "unittest" in sys.modules and path.resolve() == (ROOT / "data" / "morse.db").resolve():
        raise RuntimeError("tests must set MORSE_DB to a temporary database – refusing the live data/morse.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit, transactions by hand
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def migrate(con):
    con.execute("PRAGMA journal_mode = WAL")
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    for i in range(ver, len(MIGRATIONS)):
        con.execute("BEGIN")
        try:
            # executescript would commit the transaction early → statements one by one (no ';' allowed in SQL comments)
            for stmt in MIGRATIONS[i].split(";"):
                if stmt.strip():
                    con.execute(stmt)
            con.execute(f"PRAGMA user_version = {i + 1}")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_app(app):
    con = connect()
    migrate(con)
    con.close()
    app.teardown_appcontext(close_db)
