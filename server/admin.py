# SPDX-License-Identifier: EUPL-1.2
"""Správa z příkazové řádky (na Pi, jako vlastník adresáře aplikace):

  .venv/bin/python -m server.admin pozvanka [admin|trener|zak] [poznámka]   → vytiskne odkaz
  .venv/bin/python -m server.admin uzivatele
  .venv/bin/python -m server.admin obnova PŘEZDÍVKA       → odkaz pro nové heslo (zapomenuté heslo, trénink zůstane)
  .venv/bin/python -m server.admin heslo PŘEZDÍVKA        → dočasné heslo (zeptá se), odhlásí všude, vynutí změnu
  .venv/bin/python -m server.admin role PŘEZDÍVKA ROLE
  .venv/bin/python -m server.admin reset-vycviku PŘEZDÍVKA | --vsichni   → smaže lekce a pokrok, účty zůstanou
  .venv/bin/python -m server.admin test-historie PŘEZDÍVKA [--uroven 3|4] [--skluz-krok N]
      → jen pro testovací účet bez vlastních lekcí: vyrobí historii (celá sada, 20/20 WPM, 95 %) → úroveň U3;
        --uroven 4 přidá 2 sezení ve skluzu na kroku 6 splňující kritérium U4 → U4 a krok 7;
        --skluz-krok N navíc lekci ve skluzu na kroku N (1–13, od 7 znamená U4). Smaže se resetem výcviku.
"""
import getpass
import json
import secrets
import sys
from datetime import timedelta

from server import auth
from server import coach, site
from server.api import KOCH_ORDER, RESET_DAYS, create_reset_link, reset_training
from server.auth import iso, now, sha256
from server.db import connect, migrate



def main(argv):
    con = connect()
    migrate(con)
    cmd = argv[0] if argv else ""
    if cmd == "pozvanka":
        role = argv[1] if len(argv) > 1 else "zak"
        if role not in auth.ROLES:
            sys.exit(f"Role musí být jedna z: {', '.join(auth.ROLES)}")
        note = " ".join(argv[2:])[:60] or None
        token = secrets.token_urlsafe(24)
        t = now()
        con.execute("INSERT INTO invites (token_hash, role, note, created_by, created_at, expires_at) "
                    "VALUES (?,?,?,NULL,?,?)", (sha256(token), role, note, iso(t), iso(t + timedelta(days=7))))
        print(f"Pozvánka ({role}, platí 7 dní, jen jednou):")
        for label, url in (("doma", site.HOME_URL), ("venku", site.PUBLIC_URL)):
            if url and not (label == "venku" and role == "admin"):  # správce jen z domácí sítě
                print(f"  {label}: {url}#pozvanka={token}")
        if not site.HOME_URL and not site.PUBLIC_URL:
            print(f"  (adresy nejsou v /etc/morse-trainer/site.env) token: #pozvanka={token}")
    elif cmd == "uzivatele":
        for r in con.execute("SELECT id, nick, role, age_group, created_at, last_login_at, disabled FROM users "
                             "ORDER BY id"):
            print(f"{r['id']:>3}  {r['nick']:<24} {r['role']:<7} {r['age_group'] or '-':<6} "
                  f"vytvořen {r['created_at'][:10]}  přihlášen {(r['last_login_at'] or '-')[:16]}"
                  f"{'  ZABLOKOVÁN' if r['disabled'] else ''}")
    elif cmd == "heslo" and len(argv) == 2:
        row = con.execute("SELECT id, nick FROM users WHERE nick = ?", (argv[1],)).fetchone()
        if not row:
            sys.exit("Uživatel nenalezen.")
        pw = getpass.getpass("Nové heslo: ")
        if (p := auth.password_problem(pw, row["nick"])):
            sys.exit(p)
        if pw != getpass.getpass("Znovu: "):
            sys.exit("Hesla se neshodují.")
        con.execute("UPDATE users SET pw_hash = ?, pw_change = 1 WHERE id = ?", (auth.hash_password(pw), row["id"]))
        con.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        print("Heslo změněno, uživatel odhlášen ze všech zařízení. Po přihlášení si musí nastavit vlastní.")
    elif cmd == "obnova" and len(argv) == 2:
        row = con.execute("SELECT id, nick, role FROM users WHERE nick = ?", (argv[1],)).fetchone()
        if not row:
            sys.exit("Uživatel nenalezen.")
        token, _ = create_reset_link(con, row, None)
        print(f"Odkaz pro nové heslo ({row['nick']}, platí {RESET_DAYS} dny, jen jednou; trénink zůstane):")
        for label, url in (("doma", site.HOME_URL), ("venku", site.PUBLIC_URL)):
            if url and not (label == "venku" and row["role"] == "admin"):
                print(f"  {label}: {url}#heslo={token}")
        if not site.HOME_URL and not site.PUBLIC_URL:
            print(f"  token: #heslo={token}")
    elif cmd == "role" and len(argv) == 3 and argv[2] in auth.ROLES:
        n = con.execute("UPDATE users SET role = ? WHERE nick = ?", (argv[2], argv[1])).rowcount
        print("Hotovo." if n else "Uživatel nenalezen.")
    elif cmd == "reset-vycviku" and len(argv) == 2:
        if argv[1] == "--vsichni":
            rows = con.execute("SELECT id, nick FROM users WHERE role != 'admin'").fetchall()
            if input(f"Resetovat výcvik {len(rows)} uživatelů (smaže všechny lekce a pokrok)? Napiš ANO: ") != "ANO":
                sys.exit("Zrušeno.")
        else:
            rows = con.execute("SELECT id, nick FROM users WHERE nick = ? AND role != 'admin'", (argv[1],)).fetchall()
            if not rows:
                sys.exit("Uživatel nenalezen (nebo je správce).")
        con.execute("BEGIN")
        for r in rows:
            reset_training(con, r["id"])
        con.execute("COMMIT")
        print(f"Výcvik resetován: {', '.join(r['nick'] for r in rows) or 'nikdo'}.")
    elif cmd == "test-historie" and len(argv) >= 2:
        opts = dict(zip(argv[2::2], argv[3::2]))
        if len(argv) % 2 or set(opts) - {"--uroven", "--skluz-krok"}:
            print(__doc__)
            sys.exit(1)
        step = int(opts["--skluz-krok"]) if opts.get("--skluz-krok", "").isdigit() else None
        if "--skluz-krok" in opts and not (step and 1 <= step <= len(coach.COPY_STEPS)):
            sys.exit(f"Krok musí být 1–{len(coach.COPY_STEPS)}.")
        ul = opts.get("--uroven", "3")
        if ul not in ("3", "4"):
            sys.exit("Úroveň musí být 3 nebo 4.")
        ul = 4 if step and coach.COPY_STEPS[step - 1]["ulevel"] >= 4 else int(ul)
        row = con.execute("SELECT id FROM users WHERE nick = ? AND role != 'admin'", (argv[1],)).fetchone()
        if not row:
            sys.exit("Uživatel nenalezen (nebo je správce).")
        own = con.execute("SELECT COUNT(*) FROM lessons WHERE user_id = ? AND client_id NOT LIKE 'test-%'",
                          (row["id"],)).fetchone()[0]
        if own:
            sys.exit(f"Uživatel má {own} vlastních lekcí – test-historie je jen pro testovací účet "
                     "(nebo nejdřív reset-vycviku).")
        con.execute("BEGIN")
        test_history(con, row["id"], step, ul)
        con.execute("COMMIT")
        print(f"Hotovo: historie pro U{ul}" + (f" a lekce ve skluzu na kroku {step}" if step else "")
              + ". V aplikaci se odhlas a přihlas (nebo obnov stránku), ať se data načtou.")
    else:
        print(__doc__)
        sys.exit(1)


def copy_row(step, hours, t0, acc, words_ok):
    """Syntetická lekce ve skluzu na kroku step (80 znaků, 24 slov)."""
    st = coach.COPY_STEPS[step - 1]
    ok = round(acc * 80)
    det = {"copy": {"step": step, "content": st["content"], "gapX": st["gapX"], "markLag": st["markLag"],
                    "ok": ok, "sub": 80 - ok - 4, "del": 4, "ins": 0, "n": 80, "acc": acc, "lagMs": 350,
                    "lagP90": 900, "lagCh": 0.5, "lagChP90": 1, "lagChMax": 2, "drift": 0, "lagW": 0, "lagWP90": 1,
                    "words": {"n": 24, "ok": words_ok}, "rounds": 4, "confusions": []}}
    if st["wpm"]:
        det["copy"]["wpm"] = st["wpm"]
    w = st["wpm"] or 20
    return (f"test-skluz-{step}-{secrets.token_hex(4)}", iso(t0 - timedelta(hours=hours)), "skluz", 80, ok, acc,
            None, json.dumps(det), w)


def test_history(con, uid, step=None, ulevel=3):
    """Syntetická historie pro testování skluzu: 2 sezení po znacích na plném tempu → trenér spočítá U3 (M7).
    ulevel 4 (M8): navíc 2 sezení ve skluzu na kroku 6 (92 %, stabilní skluz) → kritérium U3 → U4."""
    t0 = now()
    per = [{"ch": c, "n": 10, "acc": 0.95, "ttr": 450} for c in KOCH_ORDER]
    rows = []
    for k, hours in enumerate((26, 2)):
        rows.append((f"test-znak-{k}-{secrets.token_hex(4)}", iso(t0 - timedelta(hours=hours)), "znak", 510, 485,
                     0.95, 450, json.dumps({"perChar": per, "confusions": []}), 20))
    if ulevel >= 4:
        last_u3 = coach.COPY_U3_LAST
        rows += [copy_row(last_u3, 25, t0, 0.92, 21), copy_row(last_u3, 3, t0, 0.92, 21)]
    if step:  # U3: 85 % (krok trvá); U4: 92 % (s krokem 6 dál splňuje kritérium U4)
        rows.append(copy_row(step, 1, t0, 0.92 if ulevel >= 4 else 0.85, 21 if ulevel >= 4 else 17))
    for cid, at, mode, trials, correct, acc, ttr, det, wpm in rows:
        con.execute("INSERT INTO lessons (user_id, client_id, at, device, mode, level, dur_s, trials, correct, acc, "
                    "ttr, wpm, fwpm, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uid, cid, at, "pc", mode, len(KOCH_ORDER), 600, trials, correct, acc, ttr, wpm, wpm, det))
    t = iso(t0)
    con.execute("INSERT INTO progress (user_id, level, introduced, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET level = excluded.level, introduced = excluded.introduced, "
                "updated_at = excluded.updated_at", (uid, len(KOCH_ORDER), json.dumps(KOCH_ORDER), t))
    old = con.execute("SELECT data FROM settings WHERE user_id = ?", (uid,)).fetchone()
    data = {**(json.loads(old["data"]) if old else {}), "wpm": 20, "fwpm": 20}
    con.execute("INSERT INTO settings (user_id, data, updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "data = excluded.data, updated_at = excluded.updated_at", (uid, json.dumps(data), t))


if __name__ == "__main__":
    main(sys.argv[1:])
