# SPDX-License-Identifier: EUPL-1.2
"""Command-line administration (on the Pi, as the owner of the application directory):

  .venv/bin/python -m server.admin invite [admin|trener|zak] [note]   → prints the invitation link
  .venv/bin/python -m server.admin users
  .venv/bin/python -m server.admin reset-link NICK      → new-password link (forgotten password, training stays)
  .venv/bin/python -m server.admin password NICK        → temporary password (asks), logs out everywhere, forces a change
  .venv/bin/python -m server.admin role NICK ROLE       → ROLE = admin | trener (coach) | zak (student)
  .venv/bin/python -m server.admin debug [NICK on|off]  → debug trace of the training (no arguments = state)
  .venv/bin/python -m server.admin debug-delete NICK|--all     → deletes debug traces and app errors
  .venv/bin/python -m server.admin visits [DAYS]       → different visitors per day (home network / outside, of them
      never logged in = someone found the page); default 14 days, kept permanently
  .venv/bin/python -m server.admin fw-sync             → downloads the latest HW key firmware release now (data/fw/)
  .venv/bin/python -m server.admin reset-training NICK|--all   → deletes lessons and progress, accounts stay
  .venv/bin/python -m server.admin test-account NICK on|off  → marks a test account (on also enables the debug trace);
      only a new account (or one after reset-training) can be marked – real training stays protected
  .venv/bin/python -m server.admin test-history NICK [--level 2|3|4|5] [--copy-step N] [--reset]
      → only for a test account: a synthetic history (main programme of 44 characters, 95 %) so that new features can be tested ahead of
        real training. --level 2 = main programme at 20/15 WPM (U2, the pace speeds up – M6); 3 (default) = 20/20 WPM → U3;
        4 = also 2 copy-behind sessions on step 6 → U4 and step 7; 5 = also 2 sessions on step 13 (25 WPM) → U5.
        --copy-step N also adds a copy-behind lesson on step N (1–23; from 7 on it means U4, from 14 on U5; not with level 2).
        --reset first deletes the training of the test account (as reset-training), so it can be repeated.
Czech command names still work as aliases (pozvanka, uzivatele, obnova, heslo, ladeni zap|vyp, ladeni-smazat
--vsichni, reset-vycviku --vsichni, test-historie --uroven --skluz-krok).
"""
import getpass
import json
import secrets
import sys
from datetime import timedelta

from server import auth
from server import coach, firmware, site, visits
from server.api import KOCH_ORDER, RESET_DAYS, create_reset_link, reset_training
from server.auth import ROLE_ADMIN, ROLE_STUDENT, iso, now, sha256
from server.coach import MODE_CHAR, MODE_COPY
from server.db import connect, migrate

# Czech aliases (older notes and instructions) → English commands and options
ALIASES = {"pozvanka": "invite", "uzivatele": "users", "obnova": "reset-link", "heslo": "password",
           "ladeni": "debug", "ladeni-smazat": "debug-delete", "reset-vycviku": "reset-training",
           "test-historie": "test-history", "test-ucet": "test-account", "navstevy": "visits"}
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
        for r in con.execute("SELECT id, nick, role, age_group, created_at, last_login_at, disabled, is_test "
                             "FROM users ORDER BY id"):
            print(f"{r['id']:>3}  {r['nick']:<24} {r['role']:<7} {r['age_group'] or '-':<6} "
                  f"created {r['created_at'][:10]}  last login {(r['last_login_at'] or '-')[:16]}"
                  f"{'  BLOCKED' if r['disabled'] else ''}{'  TEST' if r['is_test'] else ''}")
    elif cmd == "fw-sync" and len(argv) == 1:
        print(firmware.sync_now(), firmware.current() and firmware.current()["version"])
    elif cmd == "visits" and (len(argv) == 1 or (len(argv) == 2 and argv[1].isdigit())):
        v = visits.summary(con, int(argv[1]) if len(argv) == 2 else 14)
        print("day          home network (never logged in)   outside (never logged in)")
        for d in v["days"]:
            print(f"{d['day']}   {d['lan'][0]:>4} ({d['lan'][1]:>3})                      "
                  f"{d['public'][0]:>4} ({d['public'][1]:>3})")
        tot = v["total"]
        print(f"since {v['since']} different visitors: home {tot['lan'][0]} ({tot['lan'][1]}), "
              f"outside {tot['public'][0]} ({tot['public'][1]}) – counted once per month")
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
    elif cmd == "test-account" and len(argv) == 3 and argv[2] in ("on", "off"):
        row = con.execute("SELECT id FROM users WHERE nick = ? AND role != ?", (argv[1], ROLE_ADMIN)).fetchone()
        if not row:
            sys.exit("User not found (or is an administrator).")
        if argv[2] == "on":
            own = own_lessons(con, row["id"])
            if own:
                sys.exit(f"The user has {own} own lessons – only a new account can become a test account "
                         "(a real training must not be overwritten; reset-training first if it really is a test account).")
            con.execute("UPDATE users SET is_test = 1, debug_log = 1 WHERE id = ?", (row["id"],))
            print(f"{argv[1]} is a test account (debug trace on). Next: test-history {argv[1]} --level N")
        else:
            con.execute("UPDATE users SET is_test = 0 WHERE id = ?", (row["id"],))
            print(f"{argv[1]} is no longer a test account (the debug trace stays as it was: see debug).")
    elif cmd == "test-history" and len(argv) >= 2:
        reset = "--reset" in argv[2:]
        rest = [a for a in argv[2:] if a != "--reset"]
        opts = dict(zip(rest[0::2], rest[1::2]))
        if len(rest) % 2 or set(opts) - {"--level", "--copy-step"}:
            print(__doc__)
            sys.exit(1)
        step = int(opts["--copy-step"]) if opts.get("--copy-step", "").isdigit() else None
        if "--copy-step" in opts and not (step and 1 <= step <= len(coach.COPY_STEPS)):
            sys.exit(f"The step must be 1–{len(coach.COPY_STEPS)}.")
        ul = opts.get("--level", "3")
        if ul not in ("2", "3", "4", "5"):
            sys.exit("The level must be 2, 3, 4 or 5.")
        ul = int(ul)
        if step and ul == 2:
            sys.exit("--copy-step does not go with level 2 (U2 has no copy behind).")
        if step and ul == 5 and coach.COPY_STEPS[step - 1]["ulevel"] < 5:
            sys.exit("With level 5 the copy step must be a U5 step (14 and more).")
        if step:  # the step decides the level (M9: steps 14+ = U5)
            ul = max(ul, coach.COPY_STEPS[step - 1]["ulevel"])
        row = con.execute("SELECT id, is_test FROM users WHERE nick = ? AND role != ?",
                          (argv[1], ROLE_ADMIN)).fetchone()
        if not row:
            sys.exit("User not found (or is an administrator).")
        if not row["is_test"]:
            sys.exit(f"{argv[1]} is not a test account – first: test-account {argv[1]} on")
        own = own_lessons(con, row["id"])
        if own and not reset:
            sys.exit(f"The test account has {own} own lessons – add --reset (deletes its training first).")
        con.execute("BEGIN")
        if reset:
            reset_training(con, row["id"])
        test_history(con, row["id"], step, ul)
        con.execute("COMMIT")
        print(f"Done: {'training reset, ' if reset else ''}history for U{ul}"
              + (f" and a copy-behind lesson on step {step}" if step else "")
              + ". Log out and in again in the app (or reload the page) so that the data load.")
    else:
        print(__doc__)
        sys.exit(1)


def own_lessons(con, uid):
    """Lessons the user trained (not created by test-history)."""
    return con.execute("SELECT COUNT(*) FROM lessons WHERE user_id = ? AND client_id NOT LIKE 'test-%'",
                       (uid,)).fetchone()[0]


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
            None, json.dumps(det), w, w)


def test_history(con, uid, step=None, ulevel=3):
    """Synthetic history for testing ahead of real training: 2 character sessions with the main programme (44).
    ulevel 2 (M6): at 20/15 WPM → U2 (the coach speeds the gaps up); 3 (M7): at 20/20 WPM → U3;
    4 (M8): also 2 copy-behind sessions on step 6 (92 %, stable lag) → the U3 → U4 criterion;
    5 (0.9.5, for M9): also 2 sessions on the last step (25 WPM, 92 %, words 22/24) → the U4 → U5 criterion."""
    t0 = now()
    fw = 15 if ulevel == 2 else 20
    core = KOCH_ORDER[:coach.CORE_SIZE]  # 0.9.6: the main programme (the extension is off by default)
    per = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 450} for c in core]
    rows = []
    for k, hours in enumerate((60, 50) if ulevel >= 5 else (26, 2)):
        rows.append((f"test-znak-{k}-{secrets.token_hex(4)}", iso(t0 - timedelta(hours=hours)), MODE_CHAR, 510, 485,
                     0.95, 450, json.dumps({"perChar": per, "confusions": []}), 20, fw))
    if ulevel >= 4:
        last_u3 = coach.COPY_U3_LAST
        h = (40, 30) if ulevel >= 5 else (25, 3)  # U5: all step-6 sessions before the step-13 ones
        rows += [copy_row(last_u3, h[0], t0, 0.92, 21), copy_row(last_u3, h[1], t0, 0.92, 21)]
    if ulevel >= 5:
        last = coach.COPY_U4_LAST
        rows += [copy_row(last, 26, t0, 0.92, 22), copy_row(last, 2, t0, 0.92, 22)]
    if step:  # U3: 85 % (the step holds); U4+: 92 % (together with the earlier steps it still meets the criteria)
        rows.append(copy_row(step, 1, t0, 0.92 if ulevel >= 4 else 0.85, 22 if ulevel >= 5 else 21 if ulevel >= 4 else 17))
    for cid, at, mode, trials, correct, acc, ttr, det, wpm, fwpm in rows:
        con.execute("INSERT INTO lessons (user_id, client_id, at, device, mode, level, dur_s, trials, correct, acc, "
                    "ttr, wpm, fwpm, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uid, cid, at, "pc", mode, len(core), 600, trials, correct, acc, ttr, wpm, fwpm, det))
    ts = iso(t0)
    con.execute("INSERT INTO progress (user_id, level, introduced, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET level = excluded.level, introduced = excluded.introduced, "
                "updated_at = excluded.updated_at", (uid, len(core), json.dumps(core), ts))
    old = con.execute("SELECT data FROM settings WHERE user_id = ?", (uid,)).fetchone()
    data = {**(json.loads(old["data"]) if old else {}), "wpm": 20, "fwpm": fw}
    con.execute("INSERT INTO settings (user_id, data, updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "data = excluded.data, updated_at = excluded.updated_at", (uid, json.dumps(data), ts))


if __name__ == "__main__":
    main(sys.argv[1:])
