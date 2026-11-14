# SPDX-License-Identifier: EUPL-1.2
"""0.17.0 D4 sending lessons (A-15): steps char → group → word → qso, a step up after SEND_PASS_N lessons in a row
on the current step with correctness ≥ SEND_PASS_ACC (as in receiving). The state is computed from the stored
lessons only – nothing else is kept. Gaps are evaluated against the 3/7 norm in the browser (sendeval.js) but never
block the progress."""
import json

MODE_SEND = "vysilani"                    # stored, not translated (as MODE_CHAR / MODE_COPY)
SEND_STEPS = ("char", "group", "word", "qso")
SEND_PASS_ACC = 0.9
SEND_PASS_N = 2
SEND_LESSONS_RETURNED = 20
DETAIL_KEYS = ("ratio", "inGap", "charGap", "wordGap", "stability", "focus", "habits", "conf", "fixes")
DETAIL_MAX = 4000                          # bytes of the JSON detail


def step_state(lessons):
    """lessons = [(step, acc)] in time order → {step, index, streak} (streak = passing lessons in a row on it)."""
    i = 0
    streak = 0
    for step, acc in lessons:
        if step != SEND_STEPS[i]:
            continue                       # practising another step does not count, nor break the streak
        if acc >= SEND_PASS_ACC:
            streak += 1
            if streak >= SEND_PASS_N and i < len(SEND_STEPS) - 1:
                i += 1
                streak = 0
        else:
            streak = 0
    return {"step": SEND_STEPS[i], "index": i, "streak": streak, "need": SEND_PASS_N, "acc": SEND_PASS_ACC}


def clean_lesson(s, num):
    """A lesson from the client → a row tuple (client_id, at, step, tasks, acc, wpm, detail) or None when invalid."""
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not 8 <= len(s["id"]) <= 64:
        return None
    if s.get("step") not in SEND_STEPS:
        return None
    tasks = num(s.get("tasks"), 1, 500, int)   # 1.1.5: a round of the char drill = attempts (≥ 3 per character)
    acc = num(s.get("acc"), 0, 1, float)
    if tasks is None or acc is None:
        return None
    wpm = num(s.get("wpm"), 1, 80, float)
    det = s.get("detail") if isinstance(s.get("detail"), dict) else {}
    det = {k: det[k] for k in DETAIL_KEYS if k in det}
    detail = json.dumps(det, ensure_ascii=False)
    if len(detail) > DETAIL_MAX:
        detail = "{}"
    return (s["id"], s.get("at"), s["step"], tasks, round(acc, 4), None if wpm is None else round(wpm, 1), detail)


def send_data(db, uid, limit=SEND_LESSONS_RETURNED):
    """The step state and the last lessons (newest first)."""
    rows = db.execute("SELECT step, acc FROM send_lessons WHERE user_id = ? ORDER BY at, id", (uid,)).fetchall()
    last = db.execute("SELECT client_id, at, step, tasks, acc, wpm, detail FROM send_lessons WHERE user_id = ? "
                      "ORDER BY at DESC, id DESC LIMIT ?", (uid, limit)).fetchall()
    return {"state": step_state([(r["step"], r["acc"]) for r in rows]), "count": len(rows),
            "lessons": [{"id": r["client_id"], "at": r["at"], "step": r["step"], "tasks": r["tasks"], "acc": r["acc"],
                         "wpm": r["wpm"], "detail": json.loads(r["detail"] or "{}")} for r in last]}
