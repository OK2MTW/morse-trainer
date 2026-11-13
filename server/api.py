# SPDX-License-Identifier: EUPL-1.2
"""REST API: accounts, invitations, settings, progress, lessons, export and deletion of data."""
import json
import re
import secrets
from datetime import timedelta

from flask import Blueprint, Response, g, jsonify, request, send_file

from server import admission, auth, i18n
from server.auth import ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT, iso, login_required, now, sha256
from server import coach, firmware, sending, visits
from server.coach import MODE_CHAR, MODE_COPY, MODE_HEAD
from server.cwroom import is_minor
from server.db import get_db
from server.i18n import t

bp = Blueprint("api", __name__, url_prefix="/api")

# the same order as web/js/charset.js
KOCH_ORDER = list("KMURESNAPTLWI.JZ=FOYVG5/Q92H38B?47C1D60X-(+&,':)\"@!")  # as web/js/charset.js
assert len(KOCH_ORDER) == 51 and len(set(KOCH_ORDER)) == 51
CHARSET = set(KOCH_ORDER)

AGE_UNDER_15 = "do15"  # stored value ("do 15" = under 15)
AGE_GROUPS = (AGE_UNDER_15, "15-17", "18-59", "60+")
NICK_RE = re.compile(r"^[\w][\w .\-]{1,22}[\w.]$")  # 3–24 characters, letters incl. diacritics, digits, space . - _
INVITE_DAYS = 7
MAX_LESSONS_RETURNED = 500

# Settings synchronized between devices (volume stays separate on each device).
SETTINGS_RULES = {"wpm": (12, 40), "fwpm": (3, 40), "freq": (350, 900), "lessonMin": (1, 10),
                  "autoSpeed": (0, 1),   # M6: the coach controls the pace (1 = yes)
                  "extraChars": (0, 1)}  # 0.9.6: learn also the optional extension (rare punctuation)


def err(msg, code=400):
    return jsonify(error=msg), code


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


DEVICES = ("mobil", "pc")  # stored values: phone/tablet ("mobil"), computer


def device_of(value):
    return value if value in DEVICES else None


def user_json(row_or_dict):
    u = dict(row_or_dict)
    return {"id": u["id"], "nick": u["nick"], "role": u["role"], "age_group": u.get("age_group"),
            "pw_change": bool(u.get("pw_change", 0)), "debug": bool(u.get("debug_log", 0)),
            "news_seen": u.get("news_seen", 0), "created_at": u.get("created_at")}


# ================= login =================
@bp.get("/me")
def me():
    visits.record(get_db(), g.user is not None)  # 0.14.5: every page load asks /api/me
    if g.user is None:
        return auth.auth_error()
    firmware.check_soon()  # 0.15.2: the app opened by a logged-in user = a login → new HW key firmware? (throttled)
    return jsonify(user=g.user, csrf=g.session["csrf"])


@bp.post("/login")
def login():
    d = body()
    nick = str(d.get("nick", "")).strip()[:40]
    pw = str(d.get("password", ""))[:auth.LOGIN_PW_MAX + 1]
    ip = auth.client_net()
    keys = (f"ip:{ip}", f"nick:{nick.lower()}")
    if auth.too_many(*keys):
        return err(t("err.tooManyLogins"), 429)
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE nick = ?", (nick,)).fetchone()
    # Z-19: a full server refuses before argon2 (CPU); an unknown nick is checked as a newcomer (no nick probing)
    if not admission.active.admit(row["id"] if row else None, row["role"] if row else None, auth.is_public(),
                                  touch=False):
        return admission.busy_response()
    ok, new_hash = auth.verify_password(row["pw_hash"] if row else None, pw)
    if not ok or row["disabled"]:
        auth.note_fail(*keys)
        return auth.auth_error(t("err.badLogin"))
    auth.clear_fails(*keys)
    if row["role"] == ROLE_ADMIN and auth.is_public():
        return err(t("err.adminHomeOnly"), 403)
    if new_hash:
        db.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (new_hash, row["id"]))
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso(now()), row["id"]))
    admission.active.touch(row["id"], auth.is_public())
    resp = jsonify(user=user_json(row))
    csrf = auth.create_session(resp, row["id"], device_of(d.get("device")))
    resp.set_data(json.dumps({"user": user_json(row), "csrf": csrf}))
    firmware.check_soon()  # 0.15.2: every login asks GitHub for a new HW key firmware (background, throttled)
    return resp


NEWS_ID_MAX = 100000


@bp.post("/news/seen")
@login_required()
def news_seen():
    """0.9.3: the user dismissed the what's-new overview up to this entry (never goes back – several devices)."""
    nid = body().get("id")
    if not isinstance(nid, int) or isinstance(nid, bool) or not 0 <= nid <= NEWS_ID_MAX:
        return err(t("err.badNews"), 400)
    db = get_db()
    db.execute("UPDATE users SET news_seen = MAX(news_seen, ?) WHERE id = ?", (nid, g.user["id"]))
    seen = db.execute("SELECT news_seen FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
    return jsonify(news_seen=seen)


# Online users = the register of active users of the admission control (Z-19, server/admission.py): anyone who sent an
# API request within its window (in memory only, nothing stored). The app polls /online every 60 s while visible.
@bp.get("/online")
@login_required()
def online():
    """0.9.6: number of users active right now (the badge on the user icon) – only a count, no names."""
    return jsonify(online=admission.active.counts()[0])


@bp.post("/logout")
@login_required()
def logout():
    get_db().execute("DELETE FROM sessions WHERE id_hash = ?", (g.session["id_hash"],))
    resp = jsonify(ok=True)
    auth.clear_cookie(resp)
    return resp


@bp.post("/logout-all")
@login_required()
def logout_all():
    get_db().execute("DELETE FROM sessions WHERE user_id = ?", (g.user["id"],))
    resp = jsonify(ok=True)
    auth.clear_cookie(resp)
    return resp


@bp.post("/password")
@login_required()
def change_password():
    d = body()
    db = get_db()
    row = db.execute("SELECT pw_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    old = str(d.get("old", ""))[:auth.LOGIN_PW_MAX + 1]
    ok, _ = auth.verify_password(row["pw_hash"], old)
    if not ok:
        return err(t("err.currentPassword"), 403)
    new = d.get("new")
    if (p := auth.password_problem(new, g.user["nick"])):
        return err(p)
    if new == old:
        return err(t("err.samePassword"))
    db.execute("UPDATE users SET pw_hash = ?, pw_change = 0 WHERE id = ?", (auth.hash_password(new), g.user["id"]))
    # log out the other devices, keep this one
    db.execute("DELETE FROM sessions WHERE user_id = ? AND id_hash != ?", (g.user["id"], g.session["id_hash"]))
    return jsonify(ok=True)


# ================= invitations and registration =================
def find_invite(token):
    if not isinstance(token, str) or not (20 <= len(token) <= 64):
        return None
    row = get_db().execute("SELECT * FROM invites WHERE token_hash = ?", (sha256(token),)).fetchone()
    if row is None or row["used_by"] is not None or row["used_at"] is not None or row["expires_at"] < iso(now()):
        return None
    return row


@bp.post("/invite/check")
def invite_check():
    ip = auth.client_net()
    if auth.too_many(f"inv:{ip}"):
        return err(t("err.tooManyAttempts"), 429)
    inv = find_invite(body().get("token"))
    if inv is None:
        auth.note_fail(f"inv:{ip}")
        return err(t("err.inviteInvalid"), 404)
    reset = None
    if inv["reset_user"]:
        reset = get_db().execute("SELECT nick FROM users WHERE id = ?", (inv["reset_user"],)).fetchone()["nick"]
    return jsonify(role=inv["role"], expires_at=inv["expires_at"], reset=reset)


def create_user(db, nick, pw, role, age_group=None, consent=False, invited_by=None):
    """Shared by registration and the CLI. Returns (id, None) or (None, error)."""
    nick = (nick or "").strip()
    if not NICK_RE.match(nick):
        return None, t("err.nick")
    if (p := auth.password_problem(pw, nick)):
        return None, p
    if age_group not in AGE_GROUPS:
        age_group = None
    if age_group == AGE_UNDER_15 and not consent:
        return None, t("err.parentConsent")
    if db.execute("SELECT 1 FROM users WHERE nick = ?", (nick,)).fetchone():
        return None, t("err.nickTaken")
    ts = iso(now())
    cur = db.execute(
        "INSERT INTO users (nick, pw_hash, role, age_group, parent_consent_at, created_at, invited_by, pw_change) "
        "VALUES (?,?,?,?,?,?,?,0)",
        (nick, auth.hash_password(pw), role, age_group, ts if age_group == AGE_UNDER_15 else None, ts, invited_by))
    return cur.lastrowid, None


@bp.post("/register")
def register():
    d = body()
    ip = auth.client_net()
    if auth.too_many(f"inv:{ip}"):
        return err(t("err.tooManyAttempts"), 429)
    if not admission.active.admit(None, None, auth.is_public(), touch=False):   # Z-19: before argon2
        return admission.busy_response()
    db = get_db()
    inv = find_invite(d.get("token"))
    if inv is None or inv["reset_user"]:
        auth.note_fail(f"inv:{ip}")
        return err(t("err.inviteInvalid"), 404)
    db.execute("BEGIN IMMEDIATE")
    try:
        # "claim" the invitation in a transaction → it cannot be used twice concurrently
        taken = db.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL",
                           (iso(now()), inv["id"])).rowcount
        if not taken:
            db.execute("ROLLBACK")
            return err(t("err.inviteUsed"), 409)
        uid, problem = create_user(db, d.get("nick"), d.get("password"), inv["role"], d.get("age_group"),
                                   bool(d.get("parent_consent")), inv["created_by"])
        if problem:
            db.execute("ROLLBACK")
            return err(problem)
        db.execute("UPDATE invites SET used_by = ? WHERE id = ?", (uid, inv["id"]))
        if inv["group_id"] is not None:  # 0.13.0: the invitation puts the student into the trainer's group
            db.execute("UPDATE users SET group_id = ? WHERE id = ?", (inv["group_id"], uid))
        db.execute("UPDATE users SET last_login_at = created_at WHERE id = ?", (uid,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    admission.active.touch(uid, auth.is_public())
    resp = jsonify()
    csrf = auth.create_session(resp, uid, device_of(d.get("device")))
    resp.set_data(json.dumps({"user": user_json(row), "csrf": csrf}))
    return resp, 201


# ================= forgotten password (E3): a link from an administrator / coach, the training stays =================
RESET_DAYS = 3


@bp.post("/users/<int:uid>/password-link")
@login_required(ROLE_ADMIN, ROLE_COACH)
def password_link(uid):
    db = get_db()
    row = db.execute("SELECT id, nick, role, invited_by FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or (g.user["role"] != ROLE_ADMIN and row["invited_by"] != g.user["id"]):
        return err(t("err.userNotFound"), 404)
    token, expires = create_reset_link(db, row, g.user["id"])
    return jsonify(token=token, nick=row["nick"], expires_at=expires), 201


def create_reset_link(db, user_row, created_by):
    """Shared by the API and the CLI: revokes the user's older unused links, returns (token, expiry)."""
    db.execute("DELETE FROM invites WHERE reset_user = ? AND used_at IS NULL", (user_row["id"],))
    token = secrets.token_urlsafe(24)
    ts = now()
    expires = iso(ts + timedelta(days=RESET_DAYS))
    db.execute("INSERT INTO invites (token_hash, role, note, created_by, created_at, expires_at, reset_user) "
               "VALUES (?,?,?,?,?,?,?)",
               (sha256(token), user_row["role"], t("invite.resetNote", nick=user_row["nick"])[:60], created_by, iso(ts), expires,
                user_row["id"]))
    return token, expires


@bp.post("/password/reset")
def password_reset():
    d = body()
    ip = auth.client_net()
    if auth.too_many(f"inv:{ip}"):
        return err(t("err.tooManyAttempts"), 429)
    db = get_db()
    inv = find_invite(d.get("token"))
    if inv is None or not inv["reset_user"]:
        auth.note_fail(f"inv:{ip}")
        return err(t("err.linkInvalid"), 404)
    row = db.execute("SELECT * FROM users WHERE id = ?", (inv["reset_user"],)).fetchone()
    if row["disabled"]:
        return err(t("err.accountBlocked"), 403)
    if row["role"] == ROLE_ADMIN and auth.is_public():
        return err(t("err.adminPwHomeOnly"), 403)
    pw = d.get("password")
    if (p := auth.password_problem(pw, row["nick"])):
        return err(p)
    db.execute("BEGIN IMMEDIATE")
    try:
        taken = db.execute("UPDATE invites SET used_at = ?, used_by = ? WHERE id = ? AND used_at IS NULL",
                           (iso(now()), row["id"], inv["id"])).rowcount
        if not taken:
            db.execute("ROLLBACK")
            return err(t("err.linkUsed"), 409)
        db.execute("UPDATE users SET pw_hash = ?, pw_change = 0, last_login_at = ? WHERE id = ?",
                   (auth.hash_password(pw), iso(now()), row["id"]))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))  # log out everywhere
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    auth.clear_fails(f"nick:{row['nick'].lower()}")
    row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    resp = jsonify()
    csrf = auth.create_session(resp, row["id"], device_of(d.get("device")))
    resp.set_data(json.dumps({"user": user_json(row), "csrf": csrf}))
    return resp


@bp.post("/invites")
@login_required(ROLE_ADMIN, ROLE_COACH)
def invite_create():
    d = body()
    role = d.get("role", ROLE_STUDENT)
    if role not in auth.ROLES:
        return err(t("err.unknownRole"))
    if g.user["role"] != ROLE_ADMIN and role != ROLE_STUDENT:
        return err(t("err.coachInvitesStudents"), 403)
    days = d.get("days", INVITE_DAYS)
    days = days if isinstance(days, int) and 1 <= days <= 30 else INVITE_DAYS
    note = str(d.get("note", "")).strip()[:60] or None
    group = d.get("group_id")
    if group is not None:
        if role != ROLE_STUDENT or own_group(get_db(), group) is None:
            return err(t("err.groupNotFound"), 404)
    token = secrets.token_urlsafe(24)
    ts = now()
    cur = get_db().execute(
        "INSERT INTO invites (token_hash, role, note, created_by, created_at, expires_at, group_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (sha256(token), role, note, g.user["id"], iso(ts), iso(ts + timedelta(days=days)), group))
    return jsonify(id=cur.lastrowid, token=token, role=role, expires_at=iso(ts + timedelta(days=days))), 201


@bp.get("/invites")
@login_required(ROLE_ADMIN, ROLE_COACH)
def invite_list():
    sql = ("SELECT i.id, i.role, i.note, i.created_at, i.expires_at, i.used_at, u.nick AS used_by_nick, "
           "c.nick AS created_by_nick, i.group_id, gr.name AS group_name FROM invites i "
           "LEFT JOIN users u ON u.id = i.used_by LEFT JOIN users c ON c.id = i.created_by "
           "LEFT JOIN coach_groups gr ON gr.id = i.group_id")
    args = ()
    if g.user["role"] != ROLE_ADMIN:
        sql += " WHERE i.created_by = ?"
        args = (g.user["id"],)
    rows = get_db().execute(sql + " ORDER BY i.id DESC LIMIT 50", args).fetchall()
    ts = iso(now())
    out = []
    for r in rows:
        x = dict(r)
        # I18N (0.9.0): a state code, the client translates it (previously a Czech word)
        x["state"] = "used" if r["used_at"] else ("expired" if r["expires_at"] < ts else "valid")
        out.append(x)
    return jsonify(invites=out)


@bp.delete("/invites/<int:inv_id>")
@login_required(ROLE_ADMIN, ROLE_COACH)
def invite_delete(inv_id):
    sql = "DELETE FROM invites WHERE id = ? AND used_at IS NULL"
    args = [inv_id]
    if g.user["role"] != ROLE_ADMIN:
        sql += " AND created_by = ?"
        args.append(g.user["id"])
    n = get_db().execute(sql, args).rowcount
    return jsonify(ok=True) if n else err(t("err.inviteNotFound"), 404)


@bp.get("/visits")
@login_required(ROLE_ADMIN)
def visits_summary():
    """0.14.5: visit counter for the administrator (User management)."""
    days = request.args.get("days", "14")
    days = max(1, min(visits.MAX_DAYS, int(days))) if days.isdigit() else 14
    return jsonify(visits.summary(get_db(), days))


@bp.get("/visits/public")
def visits_public():
    """0.14.6: public visit counter (login page and home), no login needed."""
    return jsonify(visits.public(get_db()))


# ================= HW key firmware (0.15.0) =================
def _fw_allowed():
    return g.user["key_lab"] or g.user["role"] == ROLE_ADMIN


@bp.get("/fw")
@login_required()
def fw_info():
    """The newest CwKey release the Pi has downloaded and checked (server/firmware.py), for the key page."""
    if not _fw_allowed():
        return err(t("err.forbidden"), 403)
    rels = firmware.releases()
    out = {"release": rels[0] if rels else None, "older": [{k: r[k] for k in ("version", "released", "family", "targets")}
                                                          for r in rels[1:]]}   # 0.15.1: a way back
    if g.user["role"] == ROLE_ADMIN:
        out["sync"] = firmware.state()
    return jsonify(out)


@bp.get("/fw/<version>/<name>")
@login_required()
def fw_file(version, name):
    if not _fw_allowed():
        return err(t("err.forbidden"), 403)
    path = firmware.file_path(version, name)
    if path is None:
        return err(t("err.fwNotFound"), 404)
    return send_file(path, mimetype="application/octet-stream", as_attachment=True, download_name=name, max_age=0)


@bp.post("/fw/check")
@login_required(ROLE_ADMIN)
def fw_check():
    """The administrator asks for a check now (otherwise once a day)."""
    return jsonify(firmware.sync_now())


# ================= user management =================
@bp.get("/users")
@login_required(ROLE_ADMIN, ROLE_COACH)
def users_list():
    sql = ("SELECT u.id, u.nick, u.role, u.age_group, u.created_at, u.last_login_at, u.disabled, u.group_id, "
           "u.cw_off, u.cw_kids, u.key_lab, u.invited_by, (SELECT c.nick FROM users c WHERE c.id = u.invited_by) AS coach_nick, "
           "(SELECT COUNT(*) FROM lessons l WHERE l.user_id = u.id) AS lessons, "
           "(SELECT MAX(at) FROM lessons l WHERE l.user_id = u.id) AS last_lesson, "
           "(SELECT level FROM progress p WHERE p.user_id = u.id) AS level FROM users u")
    args = ()
    if g.user["role"] != ROLE_ADMIN:  # a coach sees only their own students
        sql += " WHERE u.invited_by = ?"
        args = (g.user["id"],)
    db = get_db()
    users = []
    for r in db.execute(sql + " ORDER BY u.nick COLLATE NOCASE", args):
        x = dict(r)
        x["minor"] = is_minor(x)  # 0.13.0: the room rules for children (shown in User management)
        users.append(x)
    kids = db.execute("SELECT cw_kids FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
    return jsonify(users=users, kids=bool(kids))



# ================= trainer groups (0.13.0) =================
GROUP_NAME_MAX = 40


def own_group(db, gid):
    """The group if it belongs to the logged-in trainer (an administrator manages all groups)."""
    if not isinstance(gid, int) or isinstance(gid, bool):
        return None
    row = db.execute("SELECT * FROM coach_groups WHERE id = ?", (gid,)).fetchone()
    if row is None or (g.user["role"] != ROLE_ADMIN and row["coach_id"] != g.user["id"]):
        return None
    return row


def group_name(d):
    name = " ".join(str(d.get("name", "")).split())[:GROUP_NAME_MAX]
    return name or None


@bp.get("/groups")
@login_required(ROLE_ADMIN, ROLE_COACH)
def groups_list():
    sql = ("SELECT gr.id, gr.name, gr.coach_id, (SELECT COUNT(*) FROM users u WHERE u.group_id = gr.id) AS members "
           "FROM coach_groups gr")
    args = ()
    if g.user["role"] != ROLE_ADMIN:
        sql += " WHERE gr.coach_id = ?"
        args = (g.user["id"],)
    return jsonify(groups=[dict(r) for r in get_db().execute(sql + " ORDER BY gr.name COLLATE NOCASE", args)])


@bp.post("/groups")
@login_required(ROLE_COACH)
def group_create():
    name = group_name(body())
    if not name:
        return err(t("err.groupName"))
    db = get_db()
    if db.execute("SELECT 1 FROM coach_groups WHERE coach_id = ? AND name = ?", (g.user["id"], name)).fetchone():
        return err(t("err.groupExists"), 409)
    cur = db.execute("INSERT INTO coach_groups (coach_id, name, created_at) VALUES (?,?,?)",
                     (g.user["id"], name, iso(now())))
    return jsonify(id=cur.lastrowid, name=name), 201


@bp.patch("/groups/<int:gid>")
@login_required(ROLE_ADMIN, ROLE_COACH)
def group_rename(gid):
    db = get_db()
    row = own_group(db, gid)
    name = group_name(body())
    if row is None:
        return err(t("err.groupNotFound"), 404)
    if not name:
        return err(t("err.groupName"))
    if db.execute("SELECT 1 FROM coach_groups WHERE coach_id = ? AND name = ? AND id != ?",
                  (row["coach_id"], name, gid)).fetchone():
        return err(t("err.groupExists"), 409)
    db.execute("UPDATE coach_groups SET name = ? WHERE id = ?", (name, gid))
    return jsonify(ok=True)


@bp.delete("/groups/<int:gid>")
@login_required(ROLE_ADMIN, ROLE_COACH)
def group_delete(gid):
    """Deletes only the group – its students and invitations stay (group_id → NULL)."""
    db = get_db()
    if own_group(db, gid) is None:
        return err(t("err.groupNotFound"), 404)
    db.execute("DELETE FROM coach_groups WHERE id = ?", (gid,))
    cw_room_changed()
    return jsonify(ok=True)


@bp.put("/users/<int:uid>/group")
@login_required(ROLE_ADMIN, ROLE_COACH)
def user_group(uid):
    """Puts a student into a group of their trainer (group_id null = out of every group)."""
    db = get_db()
    row = db.execute("SELECT role, invited_by FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or row["role"] != ROLE_STUDENT or (g.user["role"] != ROLE_ADMIN
                                                      and row["invited_by"] != g.user["id"]):
        return err(t("err.userNotFound"), 404)
    gid = body().get("group_id")
    if gid is not None:
        grp = own_group(db, gid)
        if grp is None or grp["coach_id"] != row["invited_by"]:  # only a group of the student's own trainer
            return err(t("err.groupNotFound"), 404)
    db.execute("UPDATE users SET group_id = ? WHERE id = ?", (gid, uid))
    cw_room_changed()
    return jsonify(ok=True)


@bp.put("/users/<int:uid>/key-lab")
@login_required(ROLE_ADMIN, ROLE_COACH)
def user_key_lab(uid):
    """0.14.4: opens (or closes) the telegraph key page to one student of the trainer (coaches always have it)."""
    db = get_db()
    row = db.execute("SELECT role, invited_by FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or row["role"] != ROLE_STUDENT or (g.user["role"] != ROLE_ADMIN
                                                      and row["invited_by"] != g.user["id"]):
        return err(t("err.userNotFound"), 404)
    db.execute("UPDATE users SET key_lab = ? WHERE id = ?", (1 if body().get("on") else 0, uid))
    return jsonify(ok=True)


def cw_room_changed():
    from server.cw import room  # late import: server.cw imports nothing from here, but keep the module order free
    room.invalidate()


def admins_left(db, except_id):
    return db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0 AND id != ?",
                      (except_id,)).fetchone()[0]


@bp.patch("/users/<int:uid>")
@login_required(ROLE_ADMIN)
def user_update(uid):
    d = body()
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone() is None:
        return err(t("err.userNotFound"), 404)
    demote = ("role" in d and d["role"] != ROLE_ADMIN) or d.get("disabled")
    if demote and uid == g.user["id"] and admins_left(db, uid) == 0:
        return err(t("err.lastAdmin"))
    if "role" in d:
        if d["role"] not in auth.ROLES:
            return err(t("err.unknownRole"))
        db.execute("UPDATE users SET role = ? WHERE id = ?", (d["role"], uid))
        cw_room_changed()
    if "disabled" in d:
        db.execute("UPDATE users SET disabled = ? WHERE id = ?", (1 if d["disabled"] else 0, uid))
        cw_room_changed()
        if d["disabled"]:
            db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    return jsonify(ok=True)


# ================= user data =================
def clean_settings(s):
    out = {}
    if not isinstance(s, dict):
        return out
    for k, (lo, hi) in SETTINGS_RULES.items():
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = int(round(v))
    if i18n.supported(s.get("lang")):  # I18N: UI language follows the account
        out["lang"] = s["lang"]
    if "fwpm" in out and "wpm" in out and out["fwpm"] > out["wpm"]:
        out["fwpm"] = out["wpm"]
    return out


def reset_training(db, uid):
    """Deletes lessons and progress (settings stay) and increments the reset counter. Returns the new epoch."""
    db.execute("DELETE FROM lessons WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM traces WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM progress WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM vocab WHERE user_id = ?", (uid,))  # 0.10.0: vocabulary is part of the training
    db.execute("DELETE FROM vocab_sessions WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM send_lessons WHERE user_id = ?", (uid,))  # 0.17.0: sending lessons too
    db.execute("UPDATE users SET train_epoch = train_epoch + 1 WHERE id = ?", (uid,))
    # the questionnaire (preferences) stays like settings, the reached level goes back to U1
    db.execute("UPDATE coach SET ulevel = 1, ulevel_at = NULL WHERE user_id = ?", (uid,))
    return db.execute("SELECT train_epoch FROM users WHERE id = ?", (uid,)).fetchone()[0]


def stale_epoch(db, uid, sent):
    """True if the device sends data from before a training reset."""
    if sent is None:
        return False
    cur = db.execute("SELECT train_epoch FROM users WHERE id = ?", (uid,)).fetchone()[0]
    return sent != cur


def stale():
    return t("err.stale")


def load_user_data(db, uid, limit=MAX_LESSONS_RETURNED, detail=False, after=None):
    """after (Z-20, 0.17.1) = the server sequence of the last lesson the client has → only newer ones ("partial")."""
    s = db.execute("SELECT data, updated_at FROM settings WHERE user_id = ?", (uid,)).fetchone()
    p = db.execute("SELECT level, introduced, updated_at FROM progress WHERE user_id = ?", (uid,)).fetchone()
    cols = "client_id AS id, at, device, mode, level, dur_s AS durS, trials, correct, acc, ttr, wpm, fwpm, detail"
    if after is None:
        lessons = db.execute(f"SELECT {cols} FROM (SELECT * FROM lessons WHERE user_id = ? ORDER BY at DESC LIMIT ?) "
                             "ORDER BY at", (uid, limit)).fetchall()
    else:
        lessons = db.execute(f"SELECT {cols} FROM lessons WHERE user_id = ? AND id > ? ORDER BY at LIMIT ?",
                             (uid, after, limit)).fetchall()
    seq = db.execute("SELECT MAX(id) FROM lessons WHERE user_id = ?", (uid,)).fetchone()[0] or 0
    out_lessons = []
    for r in lessons:
        x = dict(r)
        if detail:  # per-character detail only in the export (the normal sync should be light)
            x["detail"] = json.loads(x["detail"]) if x["detail"] else None
        else:
            del x["detail"]
        out_lessons.append(x)
    epoch = db.execute("SELECT train_epoch FROM users WHERE id = ?", (uid,)).fetchone()[0]
    return {
        "epoch": epoch,
        "settings": json.loads(s["data"]) if s else None,
        "settings_updated_at": s["updated_at"] if s else None,
        "progress": ({"level": p["level"], "introduced": json.loads(p["introduced"]), "updated_at": p["updated_at"]}
                     if p else None),
        "lessons": out_lessons,
        "seq": seq,
        **({"partial": True} if after is not None else {}),
    }


@bp.get("/data")
@login_required()
def data_get():
    a = request.args.get("after", "")
    after = int(a) if a.isdigit() and len(a) <= 12 else None
    return jsonify(load_user_data(get_db(), g.user["id"], after=after))


@bp.put("/settings")
@login_required(ROLE_COACH, ROLE_STUDENT)  # the administrator does not train
def settings_put():
    s = clean_settings(body().get("settings"))
    if not s:
        return err(t("err.noSettings"))
    db = get_db()
    old = db.execute("SELECT data FROM settings WHERE user_id = ?", (g.user["id"],)).fetchone()
    merged = {**(json.loads(old["data"]) if old else {}), **s}
    ts = iso(now())
    db.execute("INSERT INTO settings (user_id, data, updated_at) VALUES (?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
               (g.user["id"], json.dumps(merged), ts))
    return jsonify(settings=merged, updated_at=ts)


@bp.put("/progress")
@login_required(ROLE_COACH, ROLE_STUDENT)
def progress_put():
    d = body()
    level = d.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 2 <= level <= len(KOCH_ORDER):
        return err(t("err.badLevel"))
    intro = d.get("introduced", [])
    if not isinstance(intro, list):
        return err(t("err.badChars"))
    db = get_db()
    if stale_epoch(db, g.user["id"], d.get("epoch")):
        return err(stale(), 409)
    old = db.execute("SELECT introduced FROM progress WHERE user_id = ?", (g.user["id"],)).fetchone()
    # "introduced" characters are only merged – an offline device must not "undo" an introduction
    known = set(json.loads(old["introduced"])) if old else set()
    known |= {c for c in intro if isinstance(c, str) and c in CHARSET}
    introduced = [c for c in KOCH_ORDER if c in known]
    ts = iso(now())
    db.execute("INSERT INTO progress (user_id, level, introduced, updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET level = excluded.level, introduced = excluded.introduced, "
               "updated_at = excluded.updated_at",
               (g.user["id"], level, json.dumps(introduced), ts))
    return jsonify(level=level, introduced=introduced, updated_at=ts)


def num(v, lo, hi, kind=float):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        return None
    return kind(round(v)) if kind is int else float(v)


FATIGUE_KINDS = {"ttr", "acc"}
FATIGUE_ACTIONS = {"pause", "end", "continue"}
# 0.9.7 (Z-06): "aborted" = the page was closed/reloaded during the lesson → saved without advancing
ADV_REASONS = {"ok", "few", "acc", "ttrUnstable", "newFew", "newAcc", "newSlow", "confirm", "full", "aborted"}


def clean_detail(det):
    """Per-character statistics and confusions – only known characters and numbers, limited size."""
    if not isinstance(det, dict):
        return None
    per = []
    for r in (det.get("perChar") or [])[:60]:
        if isinstance(r, dict) and r.get("ch") in CHARSET:
            per.append({"ch": r["ch"], "n": num(r.get("n"), 0, 10000, int) or 0,
                        "acc": num(r.get("acc"), 0, 1), "ttr": num(r.get("ttr"), 0, 60000, int)})
    conf = []
    for c in (det.get("confusions") or [])[:30]:
        if isinstance(c, dict) and isinstance(c.get("pair"), str) and len(c["pair"]) <= 5:
            conf.append({"pair": c["pair"], "n": num(c.get("n"), 0, 10000, int) or 0})
    out = {"perChar": per, "confusions": conf}
    if det.get("aborted") is True:  # 0.9.7 (Z-06)
        out["aborted"] = True
    if det.get("entry") is True:  # Z-14 (0.10.16): entry test of returning operators – analyses of thresholds skip it
        out["entry"] = True
    # M4: difficulty control, warm-up, reason of the decision to advance
    if num(det.get("diff"), 0, 5) is not None:
        out["diff"] = num(det.get("diff"), 0, 5)
    log = []
    for e in (det.get("diffLog") or [])[:60] if isinstance(det.get("diffLog"), list) else []:
        if isinstance(e, list) and len(e) == 2 and num(e[0], 0, 10000, int) is not None and num(e[1], 0, 5) is not None:
            log.append([num(e[0], 0, 10000, int), num(e[1], 0, 5)])
    if log:
        out["diffLog"] = log
    w = det.get("warmup")
    if isinstance(w, dict) and num(w.get("n"), 1, 10000, int):
        out["warmup"] = {"n": num(w.get("n"), 1, 10000, int), "acc": num(w.get("acc"), 0, 1),
                         "ttr": num(w.get("ttr"), 0, 60000, int), "gapH": num(w.get("gapH"), 0, 100000)}
    # M5: fatigue in a lesson (baseline, events with the user's choice) and pauses
    f = det.get("fatigue")
    if isinstance(f, dict):
        b = f.get("base") if isinstance(f.get("base"), dict) else {}
        ev = []
        for e in (f.get("events") or [])[:20] if isinstance(f.get("events"), list) else []:
            if isinstance(e, dict) and e.get("kind") in FATIGUE_KINDS and num(e.get("t"), 0, 100000, int) is not None:
                ev.append({"t": num(e.get("t"), 0, 100000, int), "kind": e["kind"],
                           "ttrUp": num(e.get("ttrUp"), 0, 100), "accDrop": num(e.get("accDrop"), -1, 1),
                           "action": e.get("action") if e.get("action") in FATIGUE_ACTIONS else None})
        out["fatigue"] = {"base": {"acc": num(b.get("acc"), 0, 1), "ttr": num(b.get("ttr"), 0, 60000, int),
                                   "n": num(b.get("n"), 0, 10000, int)}, "events": ev}
    ps = []
    for e in (det.get("pauses") or [])[:50] if isinstance(det.get("pauses"), list) else []:
        if isinstance(e, list) and len(e) == 2 and num(e[0], 0, 100000, int) is not None \
                and num(e[1], 0, 86400, int) is not None:
            ps.append([num(e[0], 0, 100000, int), num(e[1], 0, 86400, int)])
    if ps:
        out["pauses"] = ps
    # M6: lengthening of gaps in a lesson [trial, step] and the fluency block (not counted in the lesson)
    gl = []
    for e in (det.get("gapLog") or [])[:30] if isinstance(det.get("gapLog"), list) else []:
        if isinstance(e, list) and len(e) == 2 and num(e[0], 0, 10000, int) is not None \
                and num(e[1], 0, 5, int) is not None:
            gl.append([num(e[0], 0, 10000, int), num(e[1], 0, 5, int)])
    if gl:
        out["gapLog"] = gl
    fl = det.get("fluency")
    if isinstance(fl, dict) and num(fl.get("n"), 1, 10000, int):
        out["fluency"] = {"n": num(fl.get("n"), 1, 10000, int), "acc": num(fl.get("acc"), 0, 1),
                          "ttr": num(fl.get("ttr"), 0, 60000, int), "wpm": num(fl.get("wpm"), 5, 60, int),
                          "fwpm": num(fl.get("fwpm"), 1, 60, int)}
    if det.get("adv") in ADV_REASONS:
        out["adv"] = det["adv"]
    return out


LESSON_MODES = (MODE_CHAR, MODE_COPY, MODE_HEAD)   # 0.10.14: head copy (U6)
TRACE_KEY = "klic"   # 0.12.3: tones keyed on the key page, sent on request for tuning the decoder (validation #31)
HEAD_FIELDS = ("from", "to", "RST", "NAME", "QTH", "RIG", "PWR", "ANT", "WX", "TEMP")  # = web/js/head.js
COPY_CONTENTS = ("groups", "pseudo", "words", "abbr", "calls", "long", "mix", "qso")  # M8 (U4); M9 (U5): qso
COPY_FATIGUE_KINDS = {"acc", "miss"}  # M8: fatigue in copy behind – accuracy drop / losing the stream


def clean_copy_detail(det):
    """Detail of a copy-behind lesson (M7): alignment summary, lag, words, confusions – only numbers and known values."""
    if not isinstance(det, dict) or not isinstance(det.get("copy"), dict):
        return None
    c = det["copy"]
    out = {"step": num(c.get("step"), 1, 50, int), "content": c.get("content") if c.get("content") in COPY_CONTENTS else None,
           "gapX": num(c.get("gapX"), 0.5, 10)}
    if c.get("band") in coach.COPY_BANDS:  # M9 (U5): band situation of the step
        out["band"] = c["band"]
    # M8 (optional – M7 lessons do not have them): step speed, timing of marks, lag in words
    for k, lo, hi, typ in (("wpm", 5, 60, int), ("markLag", 1, 5, int), ("lagW", 0, 100, float), ("lagWP90", 0, 100, int)):
        if c.get(k) is not None:
            out[k] = num(c.get(k), lo, hi, typ)
    for k in ("ok", "sub", "del", "ins", "n", "rounds", "lagChP90", "lagChMax"):
        out[k] = num(c.get(k), 0, 100000, int)
    if c.get("mask") is not None:  # M9 part 2: characters masked by the band (not counted in ok/n)
        out["mask"] = num(c.get("mask"), 0, 100000, int)
    out["acc"] = num(c.get("acc"), 0, 1)
    out["lagMs"] = num(c.get("lagMs"), -60000, 60000, int)
    out["lagP90"] = num(c.get("lagP90"), -60000, 60000, int)
    out["lagCh"] = num(c.get("lagCh"), 0, 1000)
    out["drift"] = num(c.get("drift"), -1000, 1000)
    w = c.get("words") if isinstance(c.get("words"), dict) else {}
    out["words"] = {"n": num(w.get("n"), 0, 100000, int) or 0, "ok": num(w.get("ok"), 0, 100000, int) or 0}
    conf = []
    for x in (c.get("confusions") or [])[:30] if isinstance(c.get("confusions"), list) else []:
        if isinstance(x, dict) and isinstance(x.get("pair"), str) and len(x["pair"]) <= 5:
            conf.append({"pair": x["pair"], "n": num(x.get("n"), 0, 10000, int) or 0})
    out["confusions"] = conf
    res = {"copy": out}
    if det.get("aborted") is True:  # 0.9.7 (Z-06): page closed/reloaded, only the finished lines
        res["aborted"] = True
    ps = []
    for e in (det.get("pauses") or [])[:50] if isinstance(det.get("pauses"), list) else []:
        if isinstance(e, list) and len(e) == 2 and num(e[0], 0, 100000, int) is not None \
                and num(e[1], 0, 86400, int) is not None:
            ps.append([num(e[0], 0, 100000, int), num(e[1], 0, 86400, int)])
    if ps:
        res["pauses"] = ps
    f = det.get("fatigue")  # M8: fatigue in copy behind (evaluated per line)
    if isinstance(f, dict):
        b = f.get("base") if isinstance(f.get("base"), dict) else {}
        ev = []
        for e in (f.get("events") or [])[:20] if isinstance(f.get("events"), list) else []:
            if isinstance(e, dict) and e.get("kind") in COPY_FATIGUE_KINDS and num(e.get("t"), 0, 100000, int) is not None:
                ev.append({"t": num(e.get("t"), 0, 100000, int), "kind": e["kind"],
                           "accDrop": num(e.get("accDrop"), -1, 1), "missUp": num(e.get("missUp"), -1, 1),
                           "action": e.get("action") if e.get("action") in FATIGUE_ACTIONS else None})
        res["fatigue"] = {"base": {"acc": num(b.get("acc"), 0, 1), "miss": num(b.get("miss"), 0, 1),
                                   "n": num(b.get("n"), 0, 100000, int)}, "events": ev}
    return res


def clean_head_detail(det):
    """Detail of a head-copy lesson (U6): step, speed, band, questions per field – only numbers and known values."""
    if not isinstance(det, dict) or not isinstance(det.get("head"), dict):
        return None
    h = det["head"]
    out = {"step": num(h.get("step"), 1, len(coach.HEAD_STEPS), int), "wpm": num(h.get("wpm"), 5, 60, int),
           "q": num(h.get("q"), 0, 100000, int), "ok": num(h.get("ok"), 0, 100000, int),
           "rounds": num(h.get("rounds"), 0, 10000, int)}
    if h.get("band") in coach.COPY_BANDS:
        out["band"] = h["band"]
    f = h.get("fields") if isinstance(h.get("fields"), dict) else {}
    out["fields"] = {k: [num(v[0], 0, 100000, int) or 0, num(v[1], 0, 100000, int) or 0]
                     for k, v in f.items() if k in HEAD_FIELDS and isinstance(v, list) and len(v) == 2}
    res = {"head": out}
    if det.get("aborted") is True:
        res["aborted"] = True
    return res


@bp.post("/lessons")
@login_required(ROLE_COACH, ROLE_STUDENT)
def lessons_post():
    d = body()
    items = d.get("lessons")
    if not isinstance(items, list) or len(items) > 200:
        return err(t("err.lessonList"))
    db = get_db()
    if stale_epoch(db, g.user["id"], d.get("epoch")):
        return err(stale(), 409)
    saved = []
    db.execute("BEGIN")
    try:
        for x in items:
            if not isinstance(x, dict):
                continue
            cid, at = x.get("id"), x.get("at")
            if not (isinstance(cid, str) and 8 <= len(cid) <= 64 and isinstance(at, str) and 10 <= len(at) <= 40):
                continue
            level = num(x.get("level"), 2, len(KOCH_ORDER), int)
            trials = num(x.get("trials"), 0, 100000, int)
            correct = num(x.get("correct"), 0, 100000, int)
            if level is None or trials is None or correct is None or correct > trials:
                continue
            mode = x.get("mode", MODE_CHAR)
            if mode not in LESSON_MODES:
                continue
            detail = (clean_detail if mode == MODE_CHAR else clean_copy_detail if mode == MODE_COPY
                      else clean_head_detail)(x.get("detail"))
            db.execute(
                "INSERT INTO lessons (user_id, client_id, at, device, mode, level, dur_s, trials, correct, acc, ttr, "
                "wpm, fwpm, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id, client_id) DO NOTHING",
                (g.user["id"], cid, at, device_of(x.get("device")), mode, level, num(x.get("durS"), 0, 86400, int),
                 trials, correct, num(x.get("acc"), 0, 1),
                 num(x.get("ttr"), 0, 60000, int) if mode == MODE_CHAR else None,
                 num(x.get("wpm"), 5, 60, int), num(x.get("fwpm"), 1, 60, int),
                 json.dumps(detail) if detail else None))
            saved.append(cid)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return jsonify(saved=saved)


# ================= debug trace of the training (V1) =================
TRACE_MAX = 200_000        # bytes of JSON per lesson
TRACE_KEEP_DAYS = 180      # owner's decision 2026-11-05: until revoked, at most 6 months
ERRORS_MAX = 20


def purge_debug(db):
    """Deletes debug data older than TRACE_KEEP_DAYS (called on every write – cheap, there is an index)."""
    limit = iso(now() - timedelta(days=TRACE_KEEP_DAYS))
    db.execute("DELETE FROM traces WHERE received < ?", (limit,))
    db.execute("DELETE FROM client_errors WHERE received < ?", (limit,))


def debug_enabled():
    return bool(g.user and g.user.get("debug"))


@bp.post("/trace")
@login_required(ROLE_COACH, ROLE_STUDENT)
def trace_post():
    if not debug_enabled():
        return jsonify(ok=False, debug=False)  # tracing off → the client drops it
    d = body()
    data = d.get("data")
    kind = d.get("kind")
    at = d.get("at")
    lesson_id = d.get("lesson_id")
    if (kind not in (*LESSON_MODES, TRACE_KEY) or not isinstance(at, str) or not 10 <= len(at) <= 40
            or not isinstance(data, dict)
            or (lesson_id is not None and not (isinstance(lesson_id, str) and 8 <= len(lesson_id) <= 64))):
        return err(t("err.badTrace"))
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > TRACE_MAX:
        return err(t("err.traceTooBig"), 413)
    db = get_db()
    db.execute("INSERT INTO traces (user_id, lesson_id, kind, at, received, data) VALUES (?,?,?,?,?,?)",
               (g.user["id"], lesson_id, kind, at, iso(now()), raw))
    purge_debug(db)
    return jsonify(ok=True)


@bp.post("/client-errors")
@login_required()
def client_errors_post():
    # 0.9.4 (validation Z-05): application errors are collected from all accounts (technical data only, 180 days);
    # the training trace itself stays limited to accounts with tracing enabled
    items = body().get("errors")
    if not isinstance(items, list):
        return err(t("err.errorList"))
    db = get_db()
    ts = iso(now())
    for x in items[:ERRORS_MAX]:
        if not isinstance(x, dict):
            continue
        clean = {k: str(x.get(k, ""))[:2000 if k == "stack" else 300] for k in ("msg", "src", "line", "stack", "ver", "view", "ua")}
        at = str(x.get("at", ts))[:40]
        db.execute("INSERT INTO client_errors (user_id, at, received, data) VALUES (?,?,?,?)",
                   (g.user["id"], at, ts, json.dumps(clean, ensure_ascii=False)))
    purge_debug(db)
    return jsonify(ok=True, debug=debug_enabled())


# ================= character statistics (M3) =================
STATS_LESSONS = 20   # from how many recent lessons the statistics are computed
STATS_RECENT = 5     # "recent" = the last N lessons, "before" = the rest (for the trend arrow)


def wmedian(pairs):
    """Weighted median of (value, weight) pairs."""
    pairs = sorted((v, w) for v, w in pairs if v is not None and w > 0)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def agg(items):
    """items = [{n, acc, ttr}] from individual lessons → {n, acc (weighted by n), ttr (weighted median)}."""
    n = sum(x["n"] for x in items)
    if not n:
        return None
    acc_items = [x for x in items if x["acc"] is not None]
    an = sum(x["n"] for x in acc_items)
    acc = sum(x["acc"] * x["n"] for x in acc_items) / an if an else None
    ttr = wmedian((x["ttr"], round(x["n"] * (x["acc"] if x["acc"] is not None else 1))) for x in items)
    return {"n": n, "acc": round(acc, 4) if acc is not None else None, "ttr": ttr}


def char_stats(rows):
    """rows = lessons (oldest first) with the detail field → per-character statistics."""
    per, conf = {}, {}
    total = len(rows)
    for i, r in enumerate(rows):
        try:
            det = json.loads(r["detail"]) if r["detail"] else None
        except ValueError:
            det = None
        if not det:
            continue
        recent = i >= total - STATS_RECENT
        for x in det.get("perChar") or []:
            if not x.get("n"):
                continue
            item = {"at": r["at"], "n": x["n"], "acc": x.get("acc"), "ttr": x.get("ttr"), "recent": recent}
            per.setdefault(x["ch"], []).append(item)
        for c in det.get("confusions") or []:
            sent, _, ans = c.get("pair", "").partition("\u2192")
            if sent in CHARSET and ans:
                d = conf.setdefault(sent, {})
                d[ans] = d.get(ans, 0) + (c.get("n") or 0)
    out = {}
    for ch, items in per.items():
        s = agg(items) or {"n": 0, "acc": None, "ttr": None}
        s["recent"] = agg([x for x in items if x["recent"]])
        s["before"] = agg([x for x in items if not x["recent"]])
        s["hist"] = [{k: x[k] for k in ("at", "n", "acc", "ttr")} for x in items]
        s["conf"] = [{"ans": a, "n": n} for a, n in sorted(conf.get(ch, {}).items(), key=lambda kv: -kv[1]) if n][:5]
        out[ch] = s
    return out


@bp.get("/stats")
@login_required(ROLE_COACH, ROLE_STUDENT)
def stats_get():
    rows = get_db().execute(
        "SELECT at, detail FROM (SELECT at, detail FROM lessons WHERE user_id = ? AND mode = ? ORDER BY at DESC LIMIT ?) "
        "ORDER BY at", (g.user["id"], MODE_CHAR, STATS_LESSONS)).fetchall()
    return jsonify(lessons=len(rows), chars=char_stats(rows))


# ================= coach (M4): questionnaire, plan, level =================
def coach_row(db, uid):
    r = db.execute("SELECT archetype, modifiers, prefs, answered_at, ulevel, ulevel_at FROM coach WHERE user_id = ?",
                   (uid,)).fetchone()
    if r is None:
        return {"archetype": None, "modifiers": [], "prefs": {}, "answered_at": None, "ulevel": 1, "ulevel_at": None}
    return {"archetype": r["archetype"], "modifiers": json.loads(r["modifiers"]), "prefs": json.loads(r["prefs"]),
            "answered_at": r["answered_at"], "ulevel": r["ulevel"], "ulevel_at": r["ulevel_at"]}


@bp.get("/coach/questions")
@login_required(ROLE_COACH, ROLE_STUDENT)
def coach_questions():
    return jsonify(questions=coach.questions_json())


@bp.post("/coach/profile")
@login_required(ROLE_COACH, ROLE_STUDENT)
def coach_profile():
    """Answers → archetype + modifiers + preferences. The answers are not stored (they may be sensitive)."""
    d = body()
    if not isinstance(d.get("answers"), dict):
        return err(t("err.noAnswers"))
    p = coach.profile_from_answers(d["answers"])
    ts = iso(now())
    db = get_db()
    db.execute("INSERT INTO coach (user_id, archetype, modifiers, prefs, answered_at, updated_at) VALUES (?,?,?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET archetype = excluded.archetype, modifiers = excluded.modifiers, "
               "prefs = excluded.prefs, answered_at = excluded.answered_at, updated_at = excluded.updated_at",
               (g.user["id"], p["archetype"], json.dumps(p["modifiers"]), json.dumps(p["prefs"]), ts, ts))
    return jsonify(coach_info(db, g.user["id"]))


def coach_info(db, uid):
    c = coach_row(db, uid)
    c["archetypeName"] = coach.archetype_name(c["archetype"])
    c["modifierNames"] = [coach.modifier_name(m) for m in c["modifiers"] if m in coach.MODIFIERS]
    lessons = [dict(r) for r in db.execute(
        "SELECT at, mode, level, dur_s, trials, acc, ttr, wpm, fwpm, device, detail FROM lessons WHERE user_id = ? ORDER BY at",
        (uid,)).fetchall()]
    p = db.execute("SELECT level FROM progress WHERE user_id = ?", (uid,)).fetchone()
    level = p["level"] if p else 2
    c["level"] = level
    c["plan"] = coach.plan_estimate(lessons, level, c["archetype"], c["prefs"])
    lv = coach.level_info(lessons, level, c["ulevel"])
    if lv["ulevel"] > c["ulevel"]:  # the reached level is stored (back only by a training reset)
        ts = iso(now())
        db.execute("INSERT INTO coach (user_id, ulevel, ulevel_at, updated_at) VALUES (?,?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET ulevel = excluded.ulevel, ulevel_at = excluded.ulevel_at, "
                   "updated_at = excluded.updated_at", (uid, lv["ulevel"], ts, ts))
        c["ulevel"], c["ulevel_at"], c["ulevelNew"] = lv["ulevel"], ts, True
    c["levelInfo"] = lv
    c["plateau"] = coach.plateau(lessons, level)
    # M6: pace (Farnsworth / character speed). The coach writes a change straight into the settings unless the user turned it off.
    srow = db.execute("SELECT data FROM settings WHERE user_id = ?", (uid,)).fetchone()
    sdata = json.loads(srow["data"]) if srow else {}
    cur = {"wpm": sdata.get("wpm", 20), "fwpm": sdata.get("fwpm", 15)}
    sp = coach.speed_advice(lessons, level, c["ulevel"], cur, c["plateau"])
    sp["auto"] = sdata.get("autoSpeed", 1) != 0
    if sp["change"] and sp["auto"]:
        merged = {**sdata, **clean_settings(sp["change"]["to"])}
        ts = iso(now())
        db.execute("INSERT INTO settings (user_id, data, updated_at) VALUES (?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                   (uid, json.dumps(merged), ts))
        sp["change"]["applied"] = True
    elif sp["change"]:
        sp["wpm"], sp["fwpm"] = cur["wpm"], cur["fwpm"]  # only a proposal – the settings stay
        sp["tempo"] = coach.tempo_text(cur["wpm"], cur["fwpm"])
        sp["change"]["applied"] = False
    c["speed"] = sp
    c["copy"] = coach.copy_advice(lessons, c["ulevel"])  # M7: copy behind (U3)
    c["head"] = coach.head_advice(lessons, c["ulevel"])  # 0.10.14: head copy (trial from U4, U5 → U6)
    c["dashboard"] = coach.dashboard(lessons, level, c["prefs"], now().timestamp() * 1000)
    return c


@bp.get("/coach")
@login_required(ROLE_COACH, ROLE_STUDENT)
def coach_get():
    db = get_db()
    uid = g.user["id"]
    key = coach_signature(db, uid)
    hit = _COACH_CACHE.get(uid)
    if hit and hit[0] == key:
        return jsonify(hit[1])
    c = coach_info(db, uid)
    _COACH_CACHE.pop(uid, None)
    _COACH_CACHE[uid] = (key, c)
    while len(_COACH_CACHE) > COACH_CACHE_MAX:
        _COACH_CACHE.pop(next(iter(_COACH_CACHE)))
    return jsonify(c)


# Z-20 (0.17.1): /api/coach is linear in the history – the result is kept per user until any of its inputs changes
# (lessons, progress, the coach row, settings, the reset counter, the language) or the hour turns (the dashboard
# counts days). The signature is read before computing, so a result that wrote a change (pace, level) is never reused.
COACH_CACHE_MAX = 200
_COACH_CACHE = {}


def coach_signature(db, uid):
    les = db.execute("SELECT COUNT(*), MAX(id), MAX(at) FROM lessons WHERE user_id = ?", (uid,)).fetchone()
    pro = db.execute("SELECT level, introduced, updated_at FROM progress WHERE user_id = ?", (uid,)).fetchone()
    co = db.execute("SELECT archetype, modifiers, prefs, answered_at, ulevel, ulevel_at, updated_at FROM coach "
                    "WHERE user_id = ?", (uid,)).fetchone()
    st = db.execute("SELECT data, updated_at FROM settings WHERE user_id = ?", (uid,)).fetchone()
    ep = db.execute("SELECT train_epoch FROM users WHERE id = ?", (uid,)).fetchone()
    return (tuple(les), tuple(pro) if pro else None, tuple(co) if co else None, tuple(st) if st else None,
            ep[0] if ep else None, i18n.current(), now().strftime("%Y-%m-%dT%H"))


# ================= training reset =================
@bp.post("/training/reset")
@login_required(ROLE_COACH, ROLE_STUDENT)
def training_reset_own():
    db = get_db()
    row = db.execute("SELECT pw_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    ok, _ = auth.verify_password(row["pw_hash"], str(body().get("password", "")))
    if not ok:
        return err(t("err.wrongPassword"), 403)
    return jsonify(epoch=reset_training(db, g.user["id"]))


@bp.post("/users/<int:uid>/reset-training")
@login_required(ROLE_ADMIN, ROLE_COACH)
def training_reset_user(uid):
    db = get_db()
    row = db.execute("SELECT role, invited_by FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None or (g.user["role"] != ROLE_ADMIN and row["invited_by"] != g.user["id"]):
        return err(t("err.userNotFound"), 404)
    if row["role"] == ROLE_ADMIN:
        return err(t("err.adminNoTraining"))
    return jsonify(epoch=reset_training(db, uid))


# ================= GDPR: export and deletion =================
# ================= vocabulary (0.10.0): abbreviations, Q codes, call sign prefixes =================
VOCAB_LISTS = ("abbr", "q", "pfx")
VOCAB_CODE = re.compile(r"^[A-Z0-9/?]{1,8}$")
VOCAB_SESSIONS_RETURNED = 30


def vocab_data(db, uid, sessions=VOCAB_SESSIONS_RETURNED):
    """Per list: totals and items {code: [n, wrong, last_ok]}; the last sessions (newest first)."""
    lists = {k: {"n": 0, "wrong": 0, "items": {}} for k in VOCAB_LISTS}
    for r in db.execute("SELECT list, code, n, wrong, last_ok FROM vocab WHERE user_id = ?", (uid,)):
        x = lists[r["list"]]
        x["items"][r["code"]] = [r["n"], r["wrong"], r["last_ok"]]
        x["n"] += r["n"]
        x["wrong"] += r["wrong"]
    ses = db.execute("SELECT client_id, at, lists, dur_s, n, wrong, detail FROM vocab_sessions WHERE user_id = ? "
                     "ORDER BY at DESC LIMIT ?", (uid, sessions)).fetchall()
    return {"lists": lists, "sessions": [{"id": s["client_id"], "at": s["at"], "lists": s["lists"].split(","),
                                          "durS": s["dur_s"], "n": s["n"], "wrong": s["wrong"],
                                          "detail": json.loads(s["detail"] or "{}")} for s in ses]}


@bp.get("/vocab")
@login_required(ROLE_COACH, ROLE_STUDENT)
def vocab_get():
    return jsonify(vocab_data(get_db(), g.user["id"]))


@bp.post("/vocab")
@login_required(ROLE_COACH, ROLE_STUDENT)
def vocab_post():
    """Finished vocabulary sessions {sessions: [{id, at, durS, items: [[list, code, n, wrong, last_ok], ...]}]}.
    Sending again is harmless (client id). Returns the saved ids (also those already stored)."""
    d = body()
    sent = d.get("sessions")
    if not isinstance(sent, list) or len(sent) > 50:
        return err(t("err.vocabList"), 400)
    db = get_db()
    uid = g.user["id"]
    if stale_epoch(db, uid, d.get("epoch")):
        return err(stale(), 409)
    saved = []
    db.execute("BEGIN")
    try:
        for s in sent:
            if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not 8 <= len(s["id"]) <= 64:
                continue
            at = s.get("at") if isinstance(s.get("at"), str) and len(s.get("at")) <= 40 else iso(now())
            items = []
            for it in (s.get("items") or [])[:400] if isinstance(s.get("items"), list) else []:
                if not (isinstance(it, list) and len(it) == 5 and it[0] in VOCAB_LISTS and isinstance(it[1], str)
                        and VOCAB_CODE.match(it[1])):
                    continue
                n, wrong = num(it[2], 1, 1000, int), num(it[3], 0, 1000, int)
                if n is None or wrong is None or wrong > n:
                    continue
                items.append((it[0], it[1], n, wrong, 1 if it[4] else 0))
            if not items:
                continue
            per = {}
            for lst, _, n, wrong, _ in items:
                p = per.setdefault(lst, [0, 0])
                p[0] += n
                p[1] += wrong
            cur = db.execute("INSERT OR IGNORE INTO vocab_sessions (user_id, client_id, at, lists, dur_s, n, wrong, detail) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             (uid, s["id"], at, ",".join(k for k in VOCAB_LISTS if k in per), num(s.get("durS"), 0, 86400, int),
                              sum(p[0] for p in per.values()), sum(p[1] for p in per.values()), json.dumps(per)))
            if cur.rowcount:  # counted only once per session
                for lst, code, n, wrong, last_ok in items:
                    db.execute("INSERT INTO vocab (user_id, list, code, n, wrong, last_ok, last_at) VALUES (?,?,?,?,?,?,?) "
                               "ON CONFLICT(user_id, list, code) DO UPDATE SET n = n + excluded.n, "
                               "wrong = wrong + excluded.wrong, last_ok = excluded.last_ok, last_at = excluded.last_at",
                               (uid, lst, code, n, wrong, last_ok, at))
            saved.append(s["id"])
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return jsonify(saved=saved)


# ================= sending lessons (0.17.0, D4 / A-15) =================
@bp.get("/send")
@login_required(ROLE_COACH, ROLE_STUDENT)
def send_get():
    if not g.user["key_lab"]:
        return err(t("err.forbidden"), 403)
    return jsonify(sending.send_data(get_db(), g.user["id"]))


@bp.post("/send")
@login_required(ROLE_COACH, ROLE_STUDENT)
def send_post():
    """Finished sending lessons {lessons: [{id, at, step, tasks, acc, wpm, detail}], epoch} → the saved ids and the
    new state. Sending again is harmless (client id)."""
    if not g.user["key_lab"]:
        return err(t("err.forbidden"), 403)
    d = body()
    sent = d.get("lessons")
    if not isinstance(sent, list) or len(sent) > 50:
        return err(t("err.sendList"), 400)
    db = get_db()
    uid = g.user["id"]
    if stale_epoch(db, uid, d.get("epoch")):
        return err(stale(), 409)
    saved = []
    db.execute("BEGIN")
    try:
        for s in sent:
            row = sending.clean_lesson(s, num)
            if not row:
                continue
            cid, at, step, tasks, acc, wpm, detail = row
            at = at if isinstance(at, str) and len(at) <= 40 else iso(now())
            db.execute("INSERT OR IGNORE INTO send_lessons (user_id, client_id, mode, at, step, tasks, acc, wpm, detail) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (uid, cid, sending.MODE_SEND, at, step, tasks, acc, wpm, detail))
            saved.append(cid)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return jsonify(saved=saved, **sending.send_data(db, uid))


@bp.get("/export")
@login_required()
def export():
    db = get_db()
    u = db.execute("SELECT nick, role, age_group, parent_consent_at, created_at, last_login_at FROM users "
                   "WHERE id = ?", (g.user["id"],)).fetchone()
    sessions = db.execute("SELECT device, created_at, last_seen FROM sessions WHERE user_id = ?",
                          (g.user["id"],)).fetchall()
    data = {
        "export": {"app": t("app.name"), "at": iso(now()), "format": 1},
        "account": dict(u),
        "sessions": [dict(s) for s in sessions],
        **load_user_data(db, g.user["id"], limit=1_000_000, detail=True),
        "coach": coach_row(db, g.user["id"]),
        "vocab": vocab_data(db, g.user["id"], sessions=1_000_000),
        "cw": cw_export(db, g.user["id"]),
        "send": sending.send_data(db, g.user["id"], limit=1_000_000),
    }
    traces = db.execute("SELECT lesson_id, kind, at, data FROM traces WHERE user_id = ? ORDER BY at",
                        (g.user["id"],)).fetchall()
    errors = db.execute("SELECT at, data FROM client_errors WHERE user_id = ? ORDER BY at", (g.user["id"],)).fetchall()
    if traces or errors:  # V1: debug trace (only for accounts with tracing enabled)
        data["debug"] = {"traces": [{**dict(r), "data": json.loads(r["data"])} for r in traces],
                         "errors": [{"at": r["at"], **json.loads(r["data"])} for r in errors]}
    resp = Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json")
    resp.headers["Content-Disposition"] = f'attachment; filename="{t("export.filename")}"'
    return resp


def cw_export(db, uid):
    """0.13.10: what the trainer groups and the CW Chat keep about the user (the room itself lives only in memory)."""
    me = db.execute("SELECT u.cw_off, u.cw_kids, g.name AS grp, c.nick AS coach FROM users u "
                    "LEFT JOIN coach_groups g ON g.id = u.group_id LEFT JOIN users c ON c.id = u.invited_by "
                    "WHERE u.id = ?", (uid,)).fetchone()
    blocked = db.execute("SELECT u.nick, b.created_at FROM cw_blocks b JOIN users u ON u.id = b.blocked_id "
                         "WHERE b.user_id = ? ORDER BY b.created_at", (uid,)).fetchall()
    groups = db.execute("SELECT name, created_at FROM coach_groups WHERE coach_id = ? ORDER BY name", (uid,)).fetchall()
    return {"coach": me["coach"], "group": me["grp"], "room_off": bool(me["cw_off"]), "kids": bool(me["cw_kids"]),
            "blocked": [dict(r) for r in blocked], "own_groups": [dict(r) for r in groups]}


@bp.post("/account/delete")
@login_required()
def account_delete():
    db = get_db()
    row = db.execute("SELECT pw_hash, role FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    ok, _ = auth.verify_password(row["pw_hash"], str(body().get("password", "")))
    if not ok:
        return err(t("err.wrongPassword"), 403)
    if row["role"] == ROLE_ADMIN and admins_left(db, g.user["id"]) == 0:
        return err(t("err.lastAdmin"))
    # ON DELETE CASCADE deletes sessions, settings, progress, lessons and unused invitations
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    resp = jsonify(ok=True)
    auth.clear_cookie(resp)
    return resp
