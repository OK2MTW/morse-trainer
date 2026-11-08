# SPDX-License-Identifier: EUPL-1.2
"""CW room API (0.13.0): /api/cw/* over plain short requests (no WebSocket, no long polling – a waiting request would
hold one of the four waitress threads). The state lives in server/cwroom.py (memory only)."""
from flask import Blueprint, g, jsonify, request

from server import cwroom
from server.auth import ROLE_ADMIN, ROLE_COACH, iso, login_required, now
from server.db import get_db
from server.i18n import t

bp = Blueprint("cw", __name__, url_prefix="/api/cw")


def load_directory():
    db = get_db()
    users = {r["id"]: dict(r) for r in db.execute(
        "SELECT id, nick, role, age_group, invited_by, group_id, disabled, cw_off, cw_kids FROM users")}
    blocks = {(r[0], r[1]) for r in db.execute("SELECT user_id, blocked_id FROM cw_blocks")}
    return users, blocks


room = cwroom.Room(load_directory)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def problem(code, status=409):
    """Errors carry a code (translated in the client) and the server text as a fallback."""
    return jsonify(error=t(f"cw.err.{code}"), code=code), status


def int_arg(name):
    try:
        return max(0, int(request.args.get(name, 0)))
    except ValueError:
        return 0


def int_field(d, name):
    v = d.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


@bp.get("/state")
@login_required()
def state():
    """The room as I see it: users with status and knocks, my connection, the channel and new received elements
    (`over`/`n` = what I already have, `done` = an over I have played to the end)."""
    return jsonify(room.state(g.user["id"], over=int_arg("over"), n=int_arg("n"), done=int_arg("done")))


@bp.get("/knocks")
@login_required()
def knocks():
    """0.13.6: who is knocking on me – asked every 5 s by the app outside the room tab (memory only)."""
    return jsonify(room.knocks_for(g.user["id"]))


@bp.post("/leave")
@login_required()
def leave():
    room.leave(g.user["id"])
    return jsonify(ok=True)


@bp.post("/knock")
@login_required()
def knock():
    to = int_field(body(), "to")
    p = room.knock(g.user["id"], to) if to else "notFound"
    return problem(p) if p else jsonify(ok=True)


@bp.post("/knock/cancel")
@login_required()
def knock_cancel():
    room.cancel_knock(g.user["id"])
    return jsonify(ok=True)


@bp.post("/answer")
@login_required()
def answer():
    d = body()
    frm = int_field(d, "from")
    p = room.answer(g.user["id"], frm, bool(d.get("accept"))) if frm else "noKnock"
    return problem(p) if p else jsonify(ok=True)


@bp.post("/hangup")
@login_required()
def hangup():
    p = room.hangup(g.user["id"])
    return problem(p) if p else jsonify(ok=True)


@bp.post("/tx")
@login_required()
def tx():
    d = body()
    els = cwroom.clean_elements(d.get("els", []))
    if els is None:
        return problem("badBatch", 400)
    p, res = room.tx(g.user["id"], over=int_field(d, "over") or 0, start=bool(d.get("start")), els=els,
                     end=bool(d.get("end")), done=int_field(d, "done") or 0)
    return problem(p) if p else jsonify(res)


@bp.post("/block")
@login_required()
def block():
    d = body()
    other = int_field(d, "id")
    db = get_db()
    if not other or other == g.user["id"] or db.execute("SELECT 1 FROM users WHERE id = ?", (other,)).fetchone() is None:
        return problem("notFound", 404)
    if d.get("on", True):
        db.execute("INSERT OR IGNORE INTO cw_blocks (user_id, blocked_id, created_at) VALUES (?,?,?)",
                   (g.user["id"], other, iso(now())))
    else:
        db.execute("DELETE FROM cw_blocks WHERE user_id = ? AND blocked_id = ?", (g.user["id"], other))
    room.invalidate()
    return jsonify(ok=True)


# ---------- trainer: the room for the children of the group and for single students ----------
@bp.get("/manage")
@login_required(ROLE_ADMIN, ROLE_COACH)
def manage():
    db = get_db()
    sql = "SELECT id, nick, role, age_group, cw_off FROM users WHERE disabled = 0 AND id != ?"
    args = (g.user["id"],)
    if g.user["role"] != ROLE_ADMIN:
        sql += " AND invited_by = ?"
        args += (g.user["id"],)
    kids = db.execute("SELECT cw_kids FROM users WHERE id = ?", (g.user["id"],)).fetchone()[0]
    return jsonify(kids=bool(kids), users=[{"id": r["id"], "nick": r["nick"], "off": bool(r["cw_off"]),
                                            "minor": cwroom.is_minor(r)}
                                           for r in db.execute(sql + " ORDER BY nick COLLATE NOCASE", args)])


@bp.put("/kids")
@login_required(ROLE_COACH)
def kids():
    get_db().execute("UPDATE users SET cw_kids = ? WHERE id = ?", (1 if body().get("on") else 0, g.user["id"]))
    room.invalidate()
    return jsonify(ok=True)


@bp.put("/access")
@login_required(ROLE_ADMIN, ROLE_COACH)
def access():
    d = body()
    uid = int_field(d, "id")
    db = get_db()
    row = db.execute("SELECT invited_by FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
    if row is None or uid == g.user["id"] or (g.user["role"] != ROLE_ADMIN and row["invited_by"] != g.user["id"]):
        return problem("notFound", 404)
    db.execute("UPDATE users SET cw_off = ? WHERE id = ?", (1 if d.get("off") else 0, uid))
    room.invalidate()
    return jsonify(ok=True)
