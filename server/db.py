# SPDX-License-Identifier: EUPL-1.2
"""SQLite: připojení na požadavek, schéma a migrace přes PRAGMA user_version."""
import os
import sqlite3
from pathlib import Path

from flask import g

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MORSE_DB", ROOT / "data" / "morse.db"))

# Každá položka = jedna migrace (index + 1 = user_version). Nikdy neměnit, jen přidávat.
MIGRATIONS = [
    """
    CREATE TABLE users (
        id            INTEGER PRIMARY KEY,
        nick          TEXT NOT NULL UNIQUE COLLATE NOCASE,
        pw_hash       TEXT NOT NULL,
        role          TEXT NOT NULL CHECK (role IN ('admin', 'trener', 'zak')),
        age_group     TEXT CHECK (age_group IN ('do15', '15-17', '18-59', '60+')),
        parent_consent_at TEXT,            -- jen u dětí do 15 let
        created_at    TEXT NOT NULL,
        last_login_at TEXT,
        disabled      INTEGER NOT NULL DEFAULT 0,
        invited_by    INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE invites (
        id          INTEGER PRIMARY KEY,
        token_hash  TEXT NOT NULL UNIQUE,  -- SHA-256 tokenu, samotný token se neukládá
        role        TEXT NOT NULL CHECK (role IN ('admin', 'trener', 'zak')),
        note        TEXT,                  -- pro koho (vidí jen admin/trenér)
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
        device     TEXT,                   -- 'mobil' / 'pc' (jen pro přehled přihlášení)
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
        introduced TEXT NOT NULL,          -- JSON pole znaků
        updated_at TEXT NOT NULL
    );
    CREATE TABLE lessons (
        id        INTEGER PRIMARY KEY,
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        client_id TEXT NOT NULL,           -- UUID z prohlížeče → opakované odeslání je neškodné
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
        detail    TEXT,                    -- JSON: statistika po znacích, záměny (pro M3)
        UNIQUE (user_id, client_id)
    );
    CREATE INDEX lessons_user_at ON lessons(user_id, at);
    """,
    # 2: počítadlo resetů výcviku – zařízení se starší hodnotou nesmí nahrát starý pokrok ani lekce
    """
    ALTER TABLE users ADD COLUMN train_epoch INTEGER NOT NULL DEFAULT 0
    """,
    # 3 (M4): výsledek dotazníku (bez odpovědí – jen archetyp, modifikátory, preference) a dosažená úroveň U1–U6
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
    # 4 (M7): režim lekce – 'znak' (čeká na odpověď, TTR) / 'skluz' (proud, hodnocení zarovnáním)
    """
    ALTER TABLE lessons ADD COLUMN mode TEXT NOT NULL DEFAULT 'znak'
    """,
    # 5 (E3): pravidla hesla – stávající účty si musí heslo změnit (pw_change = 1), odkaz pro nové heslo
    # = pozvánka s reset_user (trénink zůstane)
    """
    ALTER TABLE users ADD COLUMN pw_change INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE invites ADD COLUMN reset_user INTEGER REFERENCES users(id) ON DELETE CASCADE
    """,
]


def connect(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)  # autocommit, transakce ručně
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
            # executescript by transakci commitnul předčasně → příkazy po jednom (v SQL nesmí být ';' v komentářích)
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
