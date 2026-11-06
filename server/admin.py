# SPDX-License-Identifier: EUPL-1.2
"""Command-line administration (on the Pi, as the owner of the application directory):

  .venv/bin/python -m server.admin invite [admin|trener|zak] [note]   → prints the invitation link
  .venv/bin/python -m server.admin users
  .venv/bin/python -m server.admin reset-link NICK      → new-password link (forgotten password, training stays)
  .venv/bin/python -m server.admin password NICK        → temporary password (asks), logs out everywhere, forces a change
  .venv/bin/python -m server.admin role NICK ROLE       → ROLE = admin | trener (coach) | zak (student)
  .venv/bin/python -m server.admin debug [NICK on|off]  → debug trace of the training (no arguments = state)
  .venv/bin/python -m server.admin debug-delete NICK|--all     → deletes debug traces and app errors
  .venv/bin/python -m server.admin reset-training NICK|--all   → deletes lessons and progress, accounts stay
  .venv/bin/python -m server.admin test-history NICK [--level 3|4] [--copy-step N]
      → only for a test account without its own lessons: creates a history (full set, 20/20 WPM, 95 %) → level U3;
        --level 4 adds 2 copy-behind sessions on step 6 meeting the U4 criterion → U4 and step 7;
        --copy-step N also adds a copy-behind lesson on step N (1–13, from 7 on it means U4). A training reset deletes it.

Czech command names still work as aliases (pozvanka, uzivatele, obnova, heslo, ladeni zap|vyp, ladeni-smazat
--vsichni, reset-vycviku --vsichni, test-historie --uroven --skluz-krok).
"""
import getpass
import json
import secrets
import sys
from datetime import timedelta

from server import auth
from server import coach, site
from server.api import KOCH_ORDER, RESET_DAYS, create_reset_link, reset_training
from server.auth import ROLE_ADMIN, ROLE_STUDENT, iso, now, sha256
from server.coach import MODE_CHAR, MODE_COPY
from server.db import connect, migrate

# Czech aliases (older notes and instructions) → English commands and options
ALIASES = {"pozvanka": "invite", "uzivatele": "users", "obnova": "reset-link", "heslo": "password",
           "ladeni": "debug", "ladeni-smazat": "debug-delete", "reset-vycviku": "reset-training",
           "test-historie": "test-history"}
ARG_ALIASES = {"zap": "on", "vyp": "off", "--vsichni": "--all", "--uroven": "--level", "--skluz-krok": "--copy-step"}
# Link hashes are stored in links already sent – the app accepts these and the English #invite= / #reset=
INVITE_HASH, RESET_HASH = "pozvanka", "heslo"


def print_links(token, hash_name, admin_role):
    """Prints the home and outside link (the administrator only from the home network)."""
    for label, url in (("home", site.HOME_URL), ("outside", site.PUBLIC_URL)):
        if url and not (label == "outside" and admin_role):
            print(f"  {label}: {url}#{hash_name}={token}")
    if not site.HOME_URL and not site.PUBLIC_URL:
        print(f"  (no addresses in /etc/morse-trainer/site.env) token: #{hash_name}={token}")


def main(argv):
    con = connect()
    migrate(con)
    argv = [ALIASES.get(argv[0], argv[0])] + [ARG_ALIASES.get(a, a) for a in argv[1:]] if argv else []
    cmd = argv[0] if argv else ""
    if cmd == "invite":
        role = argv[1] if len(argv) > 1 else ROLE_STUDENT
        if role not in auth.ROLES:
            sys.exit(f"The role must be one of: {', '.join(auth.ROLES)}")
        note = " ".join(argv[2:])[:60] or None
        token = secrets.token_urlsafe(24)
        ts = now()
        con.execute("INSERT INTO invites (token_hash, role, note, created_by, created_at, expires_at) "
                    "VALUES (?,?,?,NULL,?,?)", (sha256(token), role, note, iso(ts), iso(ts + timedelta(days=7))))
        print(f"Invitation ({role}, valid for 7 days, only once):")
        print_links(token, INVITE_HASH, role == ROLE_ADMIN)
    elif cmd == "users":
        for r in con.execute("SELECT id, nick, role, age_group, created_at, last_login_at, disabled FROM users "
                             "ORDER BY id"):
            print(f"{r['id']:>3}  {r['nick']:<24} {r['role']:<7} {r['age_group'] or '-':<6} "
                  f"created {r['created_at'][:10]}  last login {(r['last_login_at'] or '-')[:16]}"
                  f"{'  BLOCKED' if r['disabled'] else ''}")
    elif cmd == "password" and len(argv) == 2:
        row = con.execute("SELECT id, nick FROM users WHERE nick = ?", (argv[1],)).fetchone()
        if not row:
            sys.exit("User not found.")
        pw = getpass.getpass("New password: ")
        if (p := auth.password_problem(pw, row["nick"])):
            sys.exit(p)
        if pw != getpass.getpass("Again: "):
            sys.exit("The passwords do not match.")
        con.execute("UPDATE users SET pw_hash = ?, pw_change = 1 WHERE id = ?", (auth.hash_password(pw), row["id"]))
        con.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        print("Password changed, the user is logged out on all devices. After logging in they must set their own.")
    elif cmd == "reset-link" and len(argv) == 2:
        row = con.execute("SELECT id, nick, role FROM users WHERE nick = ?", (argv[1],)).fetchone()
        if not row:
            sys.exit("User not found.")
        token, _ = create_reset_link(con, row, None)
        print(f"New-password link ({row['nick']}, valid for {RESET_DAYS} days, only once; the training stays):")
        print_links(token, RESET_HASH, row["role"] == ROLE_ADMIN)
    elif cmd == "debug" and len(argv) in (1, 3) and (len(argv) == 1 or argv[2] in ("on", "off")):
        if len(argv) == 3:
            n = con.execute("UPDATE users SET debug_log = ? WHERE nick = ?", (int(argv[2] == "on"), argv[1])).rowcount
            if not n:
                sys.exit("User not found.")
        for r in con.execute("SELECT u.nick, u.debug_log, (SELECT COUNT(*) FROM traces t WHERE t.user_id = u.id) AS tr, "
                             "(SELECT COUNT(*) FROM client_errors e WHERE e.user_id = u.id) AS er, "
                             "(SELECT MIN(received) FROM traces t WHERE t.user_id = u.id) AS since FROM users u ORDER BY u.id"):
            print(f"{r['nick']:<24} trace {'ON ' if r['debug_log'] else 'off'}  lessons {r['tr']:>4}  errors {r['er']:>3}"
                  f"  since {(r['since'] or '-')[:10]}")
    elif cmd == "debug-delete" and len(argv) == 2:
        if argv[1] == "--all":
            a = con.execute("DELETE FROM traces").rowcount
            b = con.execute("DELETE FROM client_errors").rowcount
        else:
            row = con.execute("SELECT id FROM users WHERE nick = ?", (argv[1],)).fetchone()
            if not row:
                sys.exit("User not found.")
            a = con.execute("DELETE FROM traces WHERE user_id = ?", (row["id"],)).rowcount
            b = con.execute("DELETE FROM client_errors WHERE user_id = ?", (row["id"],)).rowcount
        print(f"Deleted: {a} lesson traces, {b} errors.")
    elif cmd == "role" and len(argv) == 3 and argv[2] in auth.ROLES:
        n = con.execute("UPDATE users SET role = ? WHERE nick = ?", (argv[2], argv[1])).rowcount
        print("Done." if n else "User not found.")
    elif cmd == "reset-training" and len(argv) == 2:
        if argv[1] == "--all":
            rows = con.execute("SELECT id, nick FROM users WHERE role != ?", (ROLE_ADMIN,)).fetchall()
            if input(f"Reset the training of {len(rows)} users (deletes all lessons and progress)? Type YES: ") not in ("YES", "ANO"):
                sys.exit("Cancelled.")
        else:
            rows = con.execute("SELECT id, nick FROM users WHERE nick = ? AND role != ?", (argv[1], ROLE_ADMIN)).fetchall()
            if not rows:
                sys.exit("User not found (or is an administrator).")
        con.execute("BEGIN")
        for r in rows:
            reset_training(con, r["id"])
        con.execute("COMMIT")
        print(f"Training reset: {', '.join(r['nick'] for r in rows) or 'nobody'}.")
    elif cmd == "test-history" and len(argv) >= 2:
        opts = dict(zip(argv[2::2], argv[3::2]))
        if len(argv) % 2 or set(opts) - {"--level", "--copy-step"}:
            print(__doc__)
            sys.exit(1)
        step = int(opts["--copy-step"]) if opts.get("--copy-step", "").isdigit() else None
        if "--copy-step" in opts and not (step and 1 <= step <= len(coach.COPY_STEPS)):
            sys.exit(f"The step must be 1–{len(coach.COPY_STEPS)}.")
        ul = opts.get("--level", "3")
        if ul not in ("3", "4"):
            sys.exit("The level must be 3 or 4.")
        ul = 4 if step and coach.COPY_STEPS[step - 1]["ulevel"] >= 4 else int(ul)
        row = con.execute("SELECT id FROM users WHERE nick = ? AND role != ?", (argv[1], ROLE_ADMIN)).fetchone()
        if not row:
            sys.exit("User not found (or is an administrator).")
        own = con.execute("SELECT COUNT(*) FROM lessons WHERE user_id = ? AND client_id NOT LIKE 'test-%'",
                          (row["id"],)).fetchone()[0]
        if own:
            sys.exit(f"The user has {own} own lessons – test-history is only for a test account "
                     "(or run reset-training first).")
        con.execute("BEGIN")
        test_history(con, row["id"], step, ul)
        con.execute("COMMIT")
        print(f"Done: history for U{ul}" + (f" and a copy-behind lesson on step {step}" if step else "")
              + ". Log out and in again in the app (or reload the page) so that the data load.")
    else:
        print(__doc__)
        sys.exit(1)


def copy_row(step, hours, t0, acc, words_ok):
    """Synthetic copy-behind lesson on step `step` (80 characters, 24 words)."""
    st = coach.COPY_STEPS[step - 1]
    ok = round(acc * 80)
    det = {"copy": {"step": step, "content": st["content"], "gapX": st["gapX"], "markLag": st["markLag"],
                    "ok": ok, "sub": 80 - ok - 4, "del": 4, "ins": 0, "n": 80, "acc": acc, "lagMs": 350,
                    "lagP90": 900, "lagCh": 0.5, "lagChP90": 1, "lagChMax": 2, "drift": 0, "lagW": 0, "lagWP90": 1,
                    "words": {"n": 24, "ok": words_ok}, "rounds": 4, "confusions": []}}
    if st["wpm"]:
        det["copy"]["wpm"] = st["wpm"]
    w = st["wpm"] or 20
    return (f"test-skluz-{step}-{secrets.token_hex(4)}", iso(t0 - timedelta(hours=hours)), MODE_COPY, 80, ok, acc,
            None, json.dumps(det), w)


def test_history(con, uid, step=None, ulevel=3):
    """Synthetic history for testing copy behind: 2 character sessions at full pace → the coach computes U3 (M7).
    ulevel 4 (M8): also 2 copy-behind sessions on step 6 (92 %, stable lag) → the U3 → U4 criterion."""
    t0 = now()
    per = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 450} for c in KOCH_ORDER]
    rows = []
    for k, hours in enumerate((26, 2)):
        rows.append((f"test-znak-{k}-{secrets.token_hex(4)}", iso(t0 - timedelta(hours=hours)), MODE_CHAR, 510, 485,
                     0.95, 450, json.dumps({"perChar": per, "confusions": []}), 20))
    if ulevel >= 4:
        last_u3 = coach.COPY_U3_LAST
        rows += [copy_row(last_u3, 25, t0, 0.92, 21), copy_row(last_u3, 3, t0, 0.92, 21)]
    if step:  # U3: 85 % (the step holds); U4: 92 % (together with step 6 it still meets the U4 criterion)
        rows.append(copy_row(step, 1, t0, 0.92 if ulevel >= 4 else 0.85, 21 if ulevel >= 4 else 17))
    for cid, at, mode, trials, correct, acc, ttr, det, wpm in rows:
        con.execute("INSERT INTO lessons (user_id, client_id, at, device, mode, level, dur_s, trials, correct, acc, "
                    "ttr, wpm, fwpm, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uid, cid, at, "pc", mode, len(KOCH_ORDER), 600, trials, correct, acc, ttr, wpm, wpm, det))
    ts = iso(t0)
    con.execute("INSERT INTO progress (user_id, level, introduced, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET level = excluded.level, introduced = excluded.introduced, "
                "updated_at = excluded.updated_at", (uid, len(KOCH_ORDER), json.dumps(KOCH_ORDER), ts))
    old = con.execute("SELECT data FROM settings WHERE user_id = ?", (uid,)).fetchone()
    data = {**(json.loads(old["data"]) if old else {}), "wpm": 20, "fwpm": 20}
    con.execute("INSERT INTO settings (user_id, data, updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "data = excluded.data, updated_at = excluded.updated_at", (uid, json.dumps(data), ts))


if __name__ == "__main__":
    main(sys.argv[1:])
