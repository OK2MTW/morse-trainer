# SPDX-License-Identifier: EUPL-1.2
"""Coach over lessons (M4): questionnaire → archetype + modifiers, calibration, plan estimate, levels U1–U6, plateau.

All are pure functions (no DB and no Flask), tests in tests/test_coach_server.py. Texts for the UI are translated
by server.i18n.t (the request language).
Privacy: questionnaire answers are NOT stored (they may reveal health). Only the result is stored:
archetype, modifiers and preferences. Modifiers are named by need (reading, typing…), not by diagnosis.
"""
import json
from datetime import datetime

from server.i18n import fmt_num, t

# Lesson mode – stored values (DB, API, traces): character by character with an answer ("znak" = character),
# copy behind ("skluz" = lag).
MODE_CHAR = "znak"
MODE_COPY = "skluz"
MODE_HEAD = "hlava"  # U6 (0.10.14): head copy – listen to a QSO without typing, then write its key data

# ================= questionnaire =================
# Each question: id, option values, optionally "when" = (question id, {allowed values}).
# Texts: server/i18n "quiz.q.<id>" (question) and "quiz.q.<id>.<value>" (option).
QUESTIONS = [
    {"id": "age", "options": ["child", "teen", "adult", "senior"]},
    {"id": "exp", "options": ["none", "ear", "table", "active"]},
    {"id": "speed", "when": ("exp", {"ear", "table", "active"}), "options": ["unknown", "slow", "mid", "fast"]},
    {"id": "gaps", "when": ("exp", {"ear", "table", "active"}), "options": ["most", "numpunct", "few", "unknown"]},
    {"id": "time", "options": ["lt10", "10to20", "20to40", "gt40"]},
    {"id": "rhythm", "options": ["daily", "often", "weekend", "irregular"]},
    {"id": "pace", "options": ["slow", "normal", "fast"]},
    {"id": "music", "options": ["yes", "some", "no"]},
    {"id": "reading", "options": ["easy", "slow", "hard"]},
    {"id": "typing", "options": ["easy", "slow", "hard"]},
    {"id": "focus", "options": ["long", "mid", "short"]},
    {"id": "hearing", "options": ["ok", "some", "hard"]},
    {"id": "errors", "options": ["fine", "some", "upset"]},
    {"id": "numbers", "options": ["yes", "basic", "no"]},
]
QMAP = {q["id"]: q for q in QUESTIONS}

ARCHETYPES = {
    # id: (translation key of the name, minutes of net drill per character (from, to) – only an initial estimate
    # before calibration). Names: beginner standard / musical / gradual / little time / intensive, child 8–12,
    # teenager, senior 60+, returning (by ear / "dot counter" / missing numbers), active 10–18 / 20+ WPM, irregular.
    "Z01": ("coach.arch.Z01", (20, 60)),
    "Z02": ("coach.arch.Z02", (12, 40)),
    "Z03": ("coach.arch.Z03", (30, 90)),
    "Z04": ("coach.arch.Z04", (20, 60)),
    "Z05": ("coach.arch.Z05", (15, 45)),
    "Z06": ("coach.arch.Z06", (20, 70)),
    "Z07": ("coach.arch.Z07", (15, 50)),
    "Z08": ("coach.arch.Z08", (30, 100)),
    "Z09": ("coach.arch.Z09", (5, 20)),
    "Z10": ("coach.arch.Z10", (20, 70)),
    "Z11": ("coach.arch.Z11", (8, 30)),
    "Z12": ("coach.arch.Z12", (3, 15)),
    "Z13": ("coach.arch.Z13", (2, 10)),
    "Z14": ("coach.arch.Z14", (25, 80)),
}
# id: translation key – reading, typing, attention, hearing, sensitivity to errors, analyst
MODIFIERS = {m: f"coach.mod.{m}" for m in ("M15", "M16", "M17", "M18", "M19", "M20")}
MODIFIER_ORDER = ["M18", "M16", "M15", "M17", "M19", "M20"]  # priority, max. 2
MAX_MODIFIERS = 2


def archetype_name(arch):
    return t(ARCHETYPES[arch][0]) if arch in ARCHETYPES else None


def modifier_name(mod):
    return t(MODIFIERS[mod]) if mod in MODIFIERS else None


def clean_answers(raw):
    """Only known questions and values; conditional questions only when the condition holds."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for q in QUESTIONS:
        v = raw.get(q["id"])
        if v in q["options"]:
            out[q["id"]] = v
    for q in QUESTIONS:
        w = q.get("when")
        if w and out.get(w[0]) not in w[1]:
            out.pop(q["id"], None)
    return out


def archetype_of(a):
    """Basic archetype Z01–Z14 from the answers (order of the rules = priority)."""
    exp = a.get("exp", "none")
    if exp == "active":
        return "Z13" if a.get("speed") == "fast" else "Z12"
    if exp == "table":
        return "Z10"
    if exp == "ear":
        return "Z11" if a.get("gaps") == "numpunct" else "Z09"
    age = a.get("age")
    if age == "child":
        return "Z06"
    if age == "teen":
        return "Z07"
    if age == "senior":
        return "Z08"
    if a.get("rhythm") in ("weekend", "irregular"):
        return "Z14"
    if a.get("time") == "lt10":
        return "Z04"
    if a.get("pace") == "fast" and a.get("time") in ("20to40", "gt40"):
        return "Z05"
    if a.get("music") == "yes":
        return "Z02"
    if a.get("pace") == "slow":
        return "Z03"
    return "Z01"


def modifiers_of(a):
    hit = {
        "M18": a.get("hearing") in ("some", "hard"),
        "M16": a.get("typing") == "hard",
        "M15": a.get("reading") == "hard",
        "M17": a.get("focus") == "short",
        "M19": a.get("errors") == "upset",
        "M20": a.get("numbers") == "yes",
    }
    return [m for m in MODIFIER_ORDER if hit[m]][:MAX_MODIFIERS]


DAY_MIN = {"lt10": 10, "10to20": 15, "20to40": 30, "gt40": 40}  # goal of minutes a day (cap 60 = warning)


def prefs_of(arch, mods, a):
    """Preferences following from the archetype and modifiers. settings = suggested settings (the client applies them)."""
    # block length 5–10 min (R1); attention (M17) shorter
    lesson = 5
    if arch in ("Z09", "Z11"):
        lesson = 7
    if arch in ("Z05", "Z12", "Z13") or (a.get("focus") == "long" and a.get("time") in ("20to40", "gt40")
                                         and arch not in ("Z06", "Z08")):
        lesson = 10
    if "M17" in mods:
        lesson = 4
    wpm, fwpm = 20, 15
    if arch in ("Z03", "Z06", "Z08", "Z14"):
        fwpm = 10
    if arch == "Z12":
        fwpm = 18
    if arch == "Z13":
        wpm, fwpm = 25, 22
    if arch == "Z10":
        fwpm = 12  # character at full speed so that dots cannot be counted; longer gaps
    day = DAY_MIN.get(a.get("time"), 20)
    return {
        "settings": {"lessonMin": lesson, "wpm": wpm, "fwpm": min(fwpm, wpm)},
        "dayMin": day,
        "perDay": 2 if day >= 20 and arch != "Z14" else 1,
        "keyboard": "tiles" if "M16" in mods else "std",
        "slowAnswer": "M16" in mods,
        "bigText": "M15" in mods,
        "toneCheck": "M18" in mods,
        "feedback": "gentle" if "M19" in mods else "std",
        "stats": "detail" if "M20" in mods else "basic",
        "entryTest": arch in ("Z09", "Z11", "Z12", "Z13"),
    }


def profile_from_answers(raw):
    """Answers → {archetype, modifiers, prefs}. The answers themselves are neither returned nor stored."""
    a = clean_answers(raw)
    arch = archetype_of(a)
    mods = modifiers_of(a)
    return {"archetype": arch, "modifiers": mods, "prefs": prefs_of(arch, mods, a)}


def questions_json():
    """Questions for the client, translated into the request language."""
    return [{"id": q["id"], "text": t(f"quiz.q.{q['id']}"),
             "options": [{"value": v, "label": t(f"quiz.q.{q['id']}.{v}")} for v in q["options"]],
             **({"when": {"q": q["when"][0], "in": sorted(q["when"][1])}} if q.get("when") else {})}
            for q in QUESTIONS]


# ================= calibration and plan estimate (R1 ch. 4) =================
SET_SIZE = 51
CORE_SIZE = 44        # 0.9.6: the main programme; the last 7 (rare punctuation) are an optional extension – levels use the core only
CALIB_CHARS = 2       # calibration done after 2 added characters (or after 3 lessons)
CALIB_LESSONS = 3
DEFAULT_DAY_MIN = 20


def additions(lessons, level):
    """Added characters from lessons [{at, level, dur_s}] (oldest first): [(level, minutes spent on it)].

    Addition = a lesson on level L is followed by a lesson (or the current progress) on L + 1. Manual jumps do not count.
    """
    mins = {}
    adds = []
    seq = [(r["level"], (r["dur_s"] or 0) / 60) for r in lessons] + [(level, 0)]
    for i, (lv, m) in enumerate(seq[:-1]):
        mins[lv] = mins.get(lv, 0) + m
        if seq[i + 1][0] == lv + 1 and lv not in [a for a, _ in adds]:
            adds.append((lv, mins[lv]))
    return adds, mins


def spread(n):
    """Range around the measured speed – it narrows with the number of added characters (spread up to 6×, R1)."""
    if n <= 0:
        return None
    return max(0.6, 1 - 0.4 / n ** 0.5), 1 + 1.2 / n ** 0.5


def plan_estimate(lessons, level, archetype, prefs):
    arch = archetype if archetype in ARCHETYPES else "Z01"
    day = (prefs or {}).get("dayMin") or DEFAULT_DAY_MIN
    adds, mins = additions(lessons, level)
    n = len(adds)
    total = sum(m for _, m in adds)
    calibrated = n >= CALIB_CHARS or len(lessons) >= CALIB_LESSONS
    if calibrated and total + mins.get(level, 0) > 0:
        # data win over the archetype; without an added character we assume the current one is almost done
        rate = (total + (0 if n else mins.get(level, 0))) / max(n, 1)
        lo_m, hi_m = spread(max(n, 1))
        per = (rate * lo_m, rate * hi_m)
        source = "data"
    else:
        per = ARCHETYPES[arch][1]
        rate = None
        source = "prior"
    left = max(0, CORE_SIZE - level)
    cur = mins.get(level, 0)
    # remaining characters + the newest one in progress (minus the minutes already spent on it)
    rem = [p * left + max(0, p - cur) if left else 0.0 for p in per]
    return {
        "source": source, "calibrated": source == "data", "added": n, "lessons": len(lessons),
        "rate": round(rate, 1) if rate is not None else None,
        "minPerChar": [round(per[0]), round(per[1])],
        "remainingChars": left, "remainingMin": [round(rem[0]), round(rem[1])],
        "dayMin": day, "days": [round(rem[0] / day, 1), round(rem[1] / day, 1)],
    }


# ================= sessions, levels U1–U6, plateau (R1 ch. 8, 4) =================
SESSION_BREAK_MIN = 20     # the same as web/js/coach.js (a test checks they match)
LEVEL_WINDOW = 20          # character statistics for U1 from the last 20 lessons
CHAR_MIN_N = 5             # a character must sound at least 5×
CHAR_ACC = 0.9
U2_WPM = 20                # U2 → U3: full speed 20/20 WPM
U2_ACC = 0.9
U2_TTR = {"pc": 600, "mobil": 800}  # median TTR (ms) by device ("mobil" = phone) – estimate C, refine from data; phones have more latency
PLATEAU_SESSIONS = 3       # ≥ 3 sessions without progress = plateau (explain)
PLATEAU_CHANGE = 5         # ≥ 5 sessions → suggest a change of plan

# Levels U1–U6; name/content/mode/goal are translated (server/i18n "coach.level.<id>.<field>"):
# beginner, novice, intermediate, advanced, expert, master.
ULEVELS = [{"id": i} for i in range(1, 7)]
ULEVEL_FIELDS = ("name", "content", "mode", "goal")
MAX_COMPUTED_ULEVEL = 6    # M7: U3 → U4 from copy behind; M8: U4 → U5; 0.10.14: U5 → U6 from head copy
COPY_MIN_CHARS = 60        # M7: a copy-behind session is evaluated from 60 sent characters (same as web/js/copy.js)


def ulevels():
    """Levels U1–U6 with texts in the request language."""
    return [{"id": u["id"], **{f: t(f"coach.level.{u['id']}.{f}") for f in ULEVEL_FIELDS}} for u in ULEVELS]


def mode_of(r):
    return r.get("mode") or MODE_CHAR


def char_lessons(lessons):
    """Character lessons (waiting for an answer) – character statistics, U1/U2, pace and plateau are computed from them."""
    # Z-14: the entry test is not a lesson (no drill, unknown characters on purpose) – only the statistics see it
    return [r for r in lessons if mode_of(r) == MODE_CHAR and not _detail(r).get("entry")]


def _ms(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def sessions_of(lessons):
    """Lessons (oldest first) → list of sessions (lists of lessons). A break ≥ 20 min between an end and a start = new one."""
    out = []
    prev_end = None
    for r in lessons:
        end = _ms(r["at"])
        if end is None:
            continue
        start = end - (r.get("dur_s") or 0) * 1000
        if prev_end is None or start - prev_end >= SESSION_BREAK_MIN * 60000:
            out.append([])
        out[-1].append(r)
        prev_end = end
    return out


def _detail(r):
    """Parsed detail of a lesson row. Parsed once per row (cached in the row dict under "_det"): the coach asks for it
    many times per request and json.loads was half of /api/coach (capacity analysis 2026-11-07)."""
    d = r.get("detail")
    if isinstance(d, dict):
        return d
    c = r.get("_det")
    if c is not None and c[0] is d:  # bound to this very detail string (a copied row with a new detail re-parses)
        return c[1]
    try:
        p = json.loads(d) if d else {}
    except ValueError:
        p = {}
    if not isinstance(p, dict):
        p = {}
    try:
        r["_det"] = (d, p)
    except TypeError:  # an immutable row (sqlite3.Row) – no cache
        pass
    return p


def char_table(lessons):
    """{char: (n, correct)} from the lesson details."""
    tab = {}
    for r in lessons:
        for x in _detail(r).get("perChar") or []:
            n = x.get("n") or 0
            if n and x.get("acc") is not None:
                a, b = tab.get(x["ch"], (0, 0))
                tab[x["ch"]] = (a + n, b + x["acc"] * n)
    return tab


def u1_status(lessons, level):
    """How many of the 44 characters of the main programme hold ≥ 90 % (of ≥ 5 trials) in recent lessons, and whether
    it is done. The optional extension (0.9.6) never blocks a level."""
    tab = char_table(char_lessons(lessons)[-LEVEL_WINDOW:])
    core = set(KOCH[:CORE_SIZE])
    good = sum(1 for ch, (n, c) in tab.items() if ch in core and n >= CHAR_MIN_N and c / n >= CHAR_ACC - 1e-9)
    return {"good": good, "of": CORE_SIZE, "done": level >= CORE_SIZE and good >= CORE_SIZE}


def session_summary(ses):
    """Session → {n, acc, ttr (weighted median), device (prevailing), full (all at 20/20 WPM)}."""
    n = sum(r.get("trials") or 0 for r in ses)
    if not n:
        return None
    acc = sum((r.get("acc") or 0) * (r.get("trials") or 0) for r in ses) / n
    pairs = sorted((r["ttr"], r.get("trials") or 0) for r in ses if r.get("ttr") is not None)
    ttr, half, run = None, sum(w for _, w in pairs) / 2, 0
    for v, w in pairs:
        run += w
        if run >= half:
            ttr = v
            break
    devs = {}
    for r in ses:
        devs[r.get("device") or "pc"] = devs.get(r.get("device") or "pc", 0) + (r.get("trials") or 0)
    device = max(devs, key=devs.get)
    full = all((r.get("wpm") or 0) >= U2_WPM and (r.get("fwpm") or 0) >= U2_WPM for r in ses)
    return {"n": n, "acc": acc, "ttr": ttr, "device": device, "full": full}


def u2_session_ok(ses):
    s = session_summary(ses)
    if not s or not s["full"] or s["acc"] < U2_ACC - 1e-9 or s["ttr"] is None:
        return False
    return s["ttr"] <= U2_TTR.get(s["device"], U2_TTR["pc"])


def computed_ulevel(lessons, level, stored=1):
    """Level from the data. A criterion must hold in 2 consecutive sessions (R1 ch. 8).
    U1/U2 from character lessons, U3 → U4 from copy-behind lessons (only when U3 is reached or computed)."""
    zn = char_lessons(lessons)
    ses = sessions_of(zn)
    comp = 1
    if len(ses) >= 2:
        before = [r for s in ses[:-1] for r in s]
        if u1_status(before, level)["done"] and u1_status(zn, level)["done"]:
            comp = 3 if u2_session_ok(ses[-1]) and u2_session_ok(ses[-2]) else 2
    if max(comp, stored or 1) >= 3:
        cs = copy_sessions(lessons)

        def two(ok):
            return len(cs) >= 2 and ok(cs[0]) and ok(cs[1])
        u4 = two(copy_u4_ok)
        u5 = (u4 or (stored or 1) >= 4) and two(copy_u5_ok)
        if u5 or (stored or 1) >= 5:  # 0.10.14: U5 → U6 – head copy at 40 WPM clean in 2 sessions
            hs = head_sessions(lessons)
            if len(hs) >= 2 and head_u6_ok(hs[0]) and head_u6_ok(hs[1]):
                return 6
        if u5:
            return 5
        if u4:
            return 4
    return comp


def next_criteria(ulevel, lessons, level):
    """What is missing for the next level – feedback about the task (not about the person)."""
    if ulevel == 1:
        st = u1_status(lessons, level)
        items = [t("coach.next.u1Chars", level=min(level, CORE_SIZE), of=CORE_SIZE),
                 t("coach.next.u1Good", good=st["good"], of=CORE_SIZE),
                 t("coach.next.twoSessions")]
        return {"target": 2, "items": items, "ratio": round(min(level, st["good"], CORE_SIZE) / CORE_SIZE, 3)}
    if ulevel == 2:
        ses = sessions_of(char_lessons(lessons))
        s = session_summary(ses[-1]) if ses else None
        items = [t("coach.next.u2Speed"), t("coach.next.u2Acc"), t("coach.next.twoSessions")]
        if s:
            items.append(t("coach.next.u2Last", acc=round(s["acc"] * 100), ttr=s["ttr"] or "–")
                         + ("" if s["full"] else t("coach.next.u2GapsSlow")))
        return {"target": 3, "items": items, "ratio": None}
    if ulevel == 3:
        last = COPY_STEPS[COPY_U3_LAST - 1]
        items = [t("coach.next.u3Step", step=last["step"], name=step_name(last)),
                 t("coach.next.u3Tempo", wpm=U2_WPM, acc=round(COPY_U4_ACC * 100), n=COPY_MIN_CHARS),
                 t("coach.next.u3Drift", n=COPY_DRIFT_MAX),
                 t("coach.next.twoSessions")]
        cs = copy_sessions(lessons)
        if cs:
            s = cs[0]
            items.append(t("coach.next.copyLast", step=s["step"], acc=round(s["acc"] * 100))
                         + (t("coach.next.copyLastLag", lag=fmt_num(s["lagCh"])) if s["lagCh"] is not None else ""))
        return {"target": 4, "items": items, "ratio": None}
    if ulevel == 4:
        last = COPY_STEPS[COPY_U4_LAST - 1]
        items = [t("coach.next.u4Step", step=last["step"], name=step_name(last), wpm=last["wpm"]),
                 t("coach.next.u4Acc", acc=round(COPY_U5_ACC * 100), words=round(COPY_U5_WORDS * 100), n=COPY_MIN_CHARS),
                 t("coach.next.u4Drift", n=COPY_DRIFT_MAX_U4),
                 t("coach.next.twoSessions")]
        cs = copy_sessions(lessons)
        if cs:
            s = cs[0]
            items.append(t("coach.next.copyLastWpm", step=s["step"], wpm=s["wpm"], acc=round(s["acc"] * 100))
                         + (t("coach.next.copyLastWords", words=round(s["words"] * 100)) if s["words"] is not None else ""))
        return {"target": 5, "items": items, "ratio": None}
    if ulevel == 5:
        st = HEAD_STEPS[HEAD_U6_STEP - 1]
        items = [t("coach.next.u5", a=COPY_U4_LAST + 1, n=len(COPY_STEPS)),
                 t("coach.next.u5Head", step=st["step"], wpm=st["wpm"], acc=round(HEAD_U6_ACC * 100), n=HEAD_MIN_Q),
                 t("coach.next.twoSessions")]
        hs = head_sessions(lessons)
        if hs:
            items.append(t("coach.next.headLast", step=hs[0]["step"], wpm=hs[0]["wpm"], acc=round(hs[0]["acc"] * 100)))
        return {"target": 6, "items": items, "ratio": None}
    return {"target": 6, "items": [t("coach.next.u6")], "ratio": None}


def _key(r):
    return (r.get("level") or 0, r.get("wpm") or 0, r.get("fwpm") or 0)


def plateau(lessons, level):
    """≥ 3 sessions without progress (new character, faster character or shorter gaps) → explanation and a process indicator."""
    ses = sessions_of(char_lessons(lessons))
    if not ses:
        return None
    flat = [r for s in ses for r in s]
    idx = {id(r): i for i, s in enumerate(ses) for r in s}
    last_prog = -1
    for a, b in zip(flat, flat[1:]):
        ka, kb = _key(a), _key(b)
        if any(y > x for x, y in zip(ka, kb)):
            last_prog = idx[id(a)]  # progress was earned by the session with the lesson before the change
    if level > (flat[-1].get("level") or 0):
        last_prog = len(ses) - 1
    n = len(ses) - 1 - last_prog
    if n < PLATEAU_SESSIONS:
        return None
    first = session_summary(ses[last_prog + 1])
    last = session_summary(ses[-1])
    proc = None
    if first and last:
        if first["ttr"] and last["ttr"] and last["ttr"] <= first["ttr"] * 0.95:
            proc = t("coach.plateau.ttr", a=first["ttr"], b=last["ttr"])
        elif last["acc"] >= first["acc"] + 0.02:
            proc = t("coach.plateau.acc", a=round(first["acc"] * 100), b=round(last["acc"] * 100))
    return {
        "sessions": n, "change": n >= PLATEAU_CHANGE, "process": proc,
        "text": t("coach.plateau.text", n=n),
        "advice": t("coach.plateau.adviceChange") if n >= PLATEAU_CHANGE else t("coach.plateau.advice"),
    }


def level_info(lessons, level, stored):
    """Level for the API: max(stored, from data) – it does not go back automatically (only by a training reset)."""
    comp = min(MAX_COMPUTED_ULEVEL, computed_ulevel(lessons, level, stored))
    cur = max(stored or 1, comp)
    return {"ulevel": cur, "computed": comp, "levels": ulevels(), "next": next_criteria(cur, lessons, level)}


# ================= pace: character speed and Farnsworth gaps (M6) =================
# Loop b for the pace. Decided between sessions (confirmation in the next session, R1) and always about one element only:
# in U1 the new element is the character (the pace only gets easier), in U2 the gaps shorten and then the character speeds up to 20/20 WPM.
# Stateless: computed only from sessions at the CURRENT pace, so after a change (by the coach or manual) new data are awaited.
SPEED_SESSIONS = 2         # decision from the last 2 sessions at the same pace
SPEED_MIN_TRIALS = 40      # a session counts from 40 trials at the given pace (shorter ones are skipped)
SPEED_UP_ACC = 0.9         # speed up: both sessions ≥ 90 % …
SPEED_TTR_RATIO = 1.25     # … and the reaction in the last one at most 1.25× the previous one (stable)
SPEED_EASE_ACC = 0.75      # both sessions < 75 % → gaps longer by 1 WPM (easier)
FW_FAR = 6                 # gaps ≥ 6 WPM slower than the character → step of 2 WPM, otherwise 1
FW_MIN = 5                 # longest gaps (effective speed)
FW_PLATEAU_MIN = 10        # a plateau in U1 (≥ 5 sessions) lengthens the gaps by 2 WPM, at most down to here
FW_PLATEAU_STEP = 2
FLUENCY_S = 60             # fluency block from U2 (end of the lesson, not counted) …
FLUENCY_PLATEAU_S = 120    # … longer with a plateau in U2


def speed_sessions(lessons, key):
    """Summaries of the last sessions at pace key = (wpm, fwpm), newest first.
    The series ends with a session without a lesson at this pace; sessions with < 40 trials at the pace are skipped."""
    out = []
    for s in reversed(sessions_of(char_lessons(lessons))):
        part = [r for r in s if (r.get("wpm"), r.get("fwpm")) == key]
        if not part:
            break
        sm = session_summary(part)
        if sm and sm["n"] >= SPEED_MIN_TRIALS:
            out.append(sm)
    return out


def tempo_text(wpm, fwpm):
    return t("coach.tempo.gaps", wpm=wpm, fwpm=fwpm) if fwpm < wpm else t("coach.tempo.full", wpm=wpm)


def speed_advice(lessons, level, ulevel, cur, plat=None):
    """Recommended pace. cur = {wpm, fwpm} (current settings). Returns {wpm, fwpm, change, next, fluencyS}.
    change = {kind, from, to, why} when the pace should change (ease | gaps | chars | plateau)."""
    wpm, fwpm = int(cur.get("wpm") or 20), int(cur.get("fwpm") or 15)
    fwpm = min(fwpm, wpm)
    ses = speed_sessions(lessons, (wpm, fwpm))
    u2 = ulevel >= 2 and level >= CORE_SIZE
    out = {"wpm": wpm, "fwpm": fwpm, "change": None, "sessions": len(ses),
           "fluencyS": (FLUENCY_PLATEAU_S if plat and plat.get("change") else FLUENCY_S) if u2 else 0}
    to, kind, why = None, None, None
    if len(ses) >= SPEED_SESSIONS:
        a, b = ses[0], ses[1]
        pct = t("coach.pctPair", a=round(b["acc"] * 100), b=round(a["acc"] * 100))
        stable = not (a["ttr"] and b["ttr"]) or a["ttr"] <= SPEED_TTR_RATIO * b["ttr"]
        if a["acc"] < SPEED_EASE_ACC and b["acc"] < SPEED_EASE_ACC and fwpm > FW_MIN:
            to, kind = (wpm, fwpm - 1), "ease"
            why = t("coach.speed.ease", acc=round(SPEED_EASE_ACC * 100), pct=pct)
        elif u2 and a["acc"] >= SPEED_UP_ACC - 1e-9 and b["acc"] >= SPEED_UP_ACC - 1e-9 and stable:
            if fwpm < wpm:
                to, kind = (wpm, min(wpm, fwpm + (2 if wpm - fwpm >= FW_FAR else 1))), "gaps"
                why = t("coach.speed.gaps", acc=round(SPEED_UP_ACC * 100), pct=pct)
            elif wpm < U2_WPM:
                to, kind = (wpm + 1, fwpm), "chars"
                why = t("coach.speed.chars", acc=round(SPEED_UP_ACC * 100), pct=pct)
        elif not u2 and plat and plat.get("change") and len(ses) >= PLATEAU_CHANGE and fwpm > FW_PLATEAU_MIN:
            to, kind = (wpm, max(FW_PLATEAU_MIN, fwpm - FW_PLATEAU_STEP)), "plateau"
            why = t("coach.speed.plateau", n=plat["sessions"])
    if to:
        out["change"] = {"kind": kind, "from": {"wpm": wpm, "fwpm": fwpm}, "to": {"wpm": to[0], "fwpm": to[1]},
                         "why": why, "text": t("coach.speed.changed", old=tempo_text(wpm, fwpm), new=tempo_text(*to))}
        out["wpm"], out["fwpm"] = to
    # what next (feedback about the task)
    if u2 and (fwpm < wpm or wpm < U2_WPM):
        nxt = (t("coach.speed.nextGaps", n=SPEED_SESSIONS, acc=round(SPEED_UP_ACC * 100), done=min(len(ses), SPEED_SESSIONS))
               if fwpm < wpm else
               t("coach.speed.nextChars", n=SPEED_SESSIONS, acc=round(SPEED_UP_ACC * 100), done=min(len(ses), SPEED_SESSIONS)))
    elif u2:
        nxt = t("coach.speed.fullCopy") if ulevel >= 3 else t("coach.speed.fullU3")
    else:
        nxt = t("coach.speed.koch")
    out["next"] = nxt
    out["tempo"] = tempo_text(out["wpm"], out["fwpm"])
    return out


# ================= copy behind: ladder of steps U3 (M7) =================
# One new element at a time: content (groups → pseudo-words → words) and shortening of the word gap alternate.
# Stateless like the pace: step = the step of the last copy-behind lesson, the last 2 sessions on this step decide.
# M8 (U4, steps 7–13): abbreviations and Q codes → call signs → long words (whole-word lag) → mix → 21/23/25 WPM.
# wpm = speed of the character and gaps in a copy-behind lesson (None = settings from M6); markLag = the mark of word k
# only after word k+markLag (just the timing of feedback). U5 will append more steps (QSO, interference, 27–35 WPM).
# The name of a step is translated by its content ("coach.content.<content>").
def _st(step, ul, content, gapX, wpm=None, markLag=1, band=None):
    return {"step": step, "ulevel": ul, "content": content, "gapX": gapX, "wpm": wpm, "markLag": markLag, "band": band}


COPY_STEPS = [
    _st(1, 3, "groups", 3.0),
    _st(2, 3, "groups", 2.0),
    _st(3, 3, "pseudo", 2.0),
    _st(4, 3, "pseudo", 1.5),
    _st(5, 3, "words", 1.5),
    _st(6, 3, "words", 1.0),
    _st(7, 4, "abbr", 1.0, 20),
    _st(8, 4, "calls", 1.0, 20),
    _st(9, 4, "long", 1.0, 20, 2),
    _st(10, 4, "mix", 1.0, 20, 2),
    _st(11, 4, "mix", 1.0, 21, 2),
    _st(12, 4, "mix", 1.0, 23, 2),
    _st(13, 4, "mix", 1.0, 25, 2),
    # M9 (U5): QSO lines, then the band (web/js/band.js BAND_LADDER) one element at a time, then speed 27–35 WPM
    _st(14, 5, "qso", 1.0, 25, 2),
    _st(15, 5, "qso", 1.0, 25, 2, "u5noise"),
    _st(16, 5, "qso", 1.0, 25, 2, "u5qsb"),
    _st(17, 5, "qso", 1.0, 25, 2, "u5qrm"),
    _st(18, 5, "qso", 1.0, 25, 2, "u5mix"),
    _st(19, 5, "qso", 1.0, 25, 2, "u5band"),
    _st(20, 5, "qso", 1.0, 27, 2, "u5band"),
    _st(21, 5, "qso", 1.0, 30, 2, "u5band"),
    _st(22, 5, "qso", 1.0, 33, 2, "u5band"),
    _st(23, 5, "qso", 1.0, 35, 2, "u5band"),
]
COPY_EARLY_MIN = 10        # Z-16 (0.9.9): trial copy behind before U3 from this many mastered characters …
COPY_EARLY_LAST = 2        # … only on steps 1–2 (groups); the coach still recommends character lessons
COPY_U4_LAST = 13          # M9: the last step of U4 (U4 → U5 criterion); steps 14+ belong to U5
COPY_BANDS = {s["band"] for s in COPY_STEPS if s["band"]}
COPY_U3_LAST = 6           # the last step of U3 (normal gaps, short words)
COPY_SESSIONS = 2          # decision from the last 2 sessions on a step
COPY_UP_ACC = 0.9          # both ≥ 90 % after alignment → next step
COPY_EASE_ACC = 0.75       # both < 75 % → a step back
COPY_U4_ACC = 0.9          # U3 → U4 on the last step
COPY_DRIFT_MAX = 1         # lag "stable" = does not run away by more than 1 character during a lesson
COPY_U5_ACC = 0.9          # M8: U4 → U5 on the last step (25 WPM) …
COPY_U5_WORDS = 0.9        # … and whole words ≥ 90 % (R1 ch. 8)
COPY_U5_WPM = 25
COPY_DRIFT_MAX_U4 = 3      # in U4 a lag of a word is desirable, it just must not keep growing
KOCH = "KMURESNAPTLWI.JZ=FOYVG5/Q92H38B?47C1D60X-(+&,':)\"@!"  # order as in web/js/charset.js


def step_name(st):
    """Translated name of a copy-behind step (by its content; M9: + the band situation)."""
    name = t(f"coach.content.{st['content']}")
    return f"{name} – {t('coach.band.' + st['band'])}" if st.get("band") else name


def _copy(r):
    return _detail(r).get("copy") or {}


def step_of(r):
    st = _copy(r).get("step")
    return st if isinstance(st, int) and 1 <= st <= len(COPY_STEPS) else 1


def copy_summary(part):
    """Copy-behind lessons of one session → {n, acc, lagCh, lagMs, drift, step, full}."""
    n = sum(r.get("trials") or 0 for r in part)
    if not n:
        return None
    ok = sum(_copy(r).get("ok") or round((r.get("acc") or 0) * (r.get("trials") or 0)) for r in part)
    ins = sum(_copy(r).get("ins") or 0 for r in part)
    lag = [(_copy(r).get("lagCh"), r.get("trials") or 0) for r in part if _copy(r).get("lagCh") is not None]
    lagms = [(_copy(r).get("lagMs"), r.get("trials") or 0) for r in part if _copy(r).get("lagMs") is not None]
    drifts = [_copy(r)["drift"] for r in part if _copy(r).get("drift") is not None]
    lagw = [(_copy(r).get("lagW"), r.get("trials") or 0) for r in part if _copy(r).get("lagW") is not None]
    wn = sum(((_copy(r).get("words") or {}).get("n") or 0) for r in part)
    wok = sum(((_copy(r).get("words") or {}).get("ok") or 0) for r in part)

    def wmed(pairs):
        pairs = sorted(pairs)
        half, run = sum(w for _, w in pairs) / 2, 0
        for v, w in pairs:
            run += w
            if run >= half:
                return v
        return None
    return {"n": n, "acc": ok / (n + ins), "lagCh": wmed(lag), "lagMs": wmed(lagms),
            "drift": max(drifts) if drifts else None, "step": step_of(part[-1]),
            "full": all((r.get("wpm") or 0) >= U2_WPM and (r.get("fwpm") or 0) >= U2_WPM for r in part),
            "wpm": min(min(r.get("wpm") or 0, r.get("fwpm") or 0) for r in part),
            "lagW": wmed(lagw), "words": wok / wn if wn else None}


def copy_sessions(lessons, step=None):
    """Summaries of copy-behind sessions, newest first. Sessions with character lessons only are skipped.
    With a step: the series ends with a session where copy behind was only on another step; sessions with < 60 characters are skipped."""
    out = []
    for s in reversed(sessions_of(lessons)):
        cp = [r for r in s if mode_of(r) == MODE_COPY]
        if not cp:
            continue
        part = [r for r in cp if step is None or step_of(r) == step]
        if not part:
            break
        sm = copy_summary(part)
        if sm and sm["n"] >= COPY_MIN_CHARS:
            out.append(sm)
    return out


def copy_u4_ok(sm):
    return (sm["step"] >= COPY_U3_LAST and sm["full"] and sm["acc"] >= COPY_U4_ACC - 1e-9
            and (sm["drift"] is None or sm["drift"] <= COPY_DRIFT_MAX))


def copy_u5_ok(sm):
    """U4 → U5 (M8): last step, ≥ 25 WPM, ≥ 90 % after alignment, whole words ≥ 90 %, the lag does not run away."""
    return (sm["step"] >= COPY_U4_LAST and sm["wpm"] >= COPY_U5_WPM and sm["acc"] >= COPY_U5_ACC - 1e-9
            and sm["words"] is not None and sm["words"] >= COPY_U5_WORDS - 1e-9
            and (sm["drift"] is None or sm["drift"] <= COPY_DRIFT_MAX_U4))


# ================= head copy (U6, 0.10.14) =================
# A QSO is played once, nothing is typed while listening; then HEAD_Q questions about its content (call, RST, name, QTH…)
# answered by writing the value (owner 2026-11-07). Own ladder; from U4 only step 1 as a trial, the full ladder from U5,
# U5 → U6 = 2 sessions ≥ 90 % on step HEAD_U6_STEP (40 WPM clean). Up/down like copy behind (2 sessions ≥ 90 % / < 75 %).
def _hs(step, ul, wpm, band=None):
    return {"step": step, "ulevel": ul, "wpm": wpm, "band": band}


HEAD_STEPS = [
    _hs(1, 4, 25), _hs(2, 5, 30), _hs(3, 5, 30, "u5noise"), _hs(4, 5, 35), _hs(5, 5, 35, "u5band"),
    _hs(6, 5, 40), _hs(7, 6, 40, "u5band"), _hs(8, 6, 45),
]
HEAD_EARLY_LAST = 1        # U4: trial on step 1 only
HEAD_U6_STEP = 6           # 40 WPM clean
HEAD_U6_ACC = 0.9
HEAD_MIN_Q = 12            # a session counts from 12 answered questions (= 4 QSOs)


def head_step_name(st):
    name = t("coach.head.name", wpm=st["wpm"])
    return f"{name} – {t('coach.band.' + st['band'])}" if st.get("band") else name


def head_step_of(r):
    st = (_detail(r).get("head") or {}).get("step")
    return st if isinstance(st, int) and 1 <= st <= len(HEAD_STEPS) else 1


def head_summary(part):
    q = sum(r.get("trials") or 0 for r in part)
    if not q:
        return None
    ok = sum(r.get("correct") or 0 for r in part)
    return {"n": q, "acc": ok / q, "step": head_step_of(part[-1]), "wpm": min(r.get("wpm") or 0 for r in part)}


def head_sessions(lessons, step=None):
    """Summaries of head-copy sessions, newest first (as copy_sessions: a series on one step, < HEAD_MIN_Q skipped)."""
    out = []
    for s in reversed(sessions_of(lessons)):
        hd = [r for r in s if mode_of(r) == MODE_HEAD]
        if not hd:
            continue
        part = [r for r in hd if step is None or head_step_of(r) == step]
        if not part:
            break
        sm = head_summary(part)
        if sm and sm["n"] >= HEAD_MIN_Q:
            out.append(sm)
    return out


def head_u6_ok(sm):
    return sm["step"] >= HEAD_U6_STEP and sm["wpm"] >= HEAD_STEPS[HEAD_U6_STEP - 1]["wpm"] and sm["acc"] >= HEAD_U6_ACC - 1e-9


def head_advice(lessons, ulevel):
    """Step of head copy for the next lesson: {available, early, step, of, wpm, band, name, change, next}."""
    hd = [r for r in lessons if mode_of(r) == MODE_HEAD]
    step = head_step_of(hd[-1]) if hd else 1
    early = ulevel < 5
    top = HEAD_EARLY_LAST if early else len(HEAD_STEPS)
    step = min(step, top)
    ses = head_sessions(lessons, step)
    change = None
    done = sum(1 for x in ses[:COPY_SESSIONS] if x["acc"] >= COPY_UP_ACC - 1e-9)
    if len(ses) >= COPY_SESSIONS:
        a, b = ses[0], ses[1]
        pct = t("coach.pctPair", a=round(b["acc"] * 100), b=round(a["acc"] * 100))
        if (a["acc"] >= COPY_UP_ACC - 1e-9 and b["acc"] >= COPY_UP_ACC - 1e-9 and step < top
                and HEAD_STEPS[step]["ulevel"] <= ulevel):
            change = {"kind": "up", "from": step, "to": step + 1, "why": t("coach.copy.up", acc=round(COPY_UP_ACC * 100), pct=pct)}
        elif a["acc"] < COPY_EASE_ACC and b["acc"] < COPY_EASE_ACC and step > 1:
            change = {"kind": "ease", "from": step, "to": step - 1,
                      "why": t("coach.copy.ease", acc=round(COPY_EASE_ACC * 100), pct=pct)}
    if change:
        step = change["to"]
        done = 0
    st = HEAD_STEPS[step - 1]
    if change:
        change["text"] = t("coach.head.changed", a=change["from"], b=step, name=head_step_name(st))
    if early:
        nxt = t("coach.head.nextEarly")
    elif step == HEAD_U6_STEP and ulevel < 6:
        nxt = t("coach.head.nextU6", n=COPY_SESSIONS, acc=round(HEAD_U6_ACC * 100))
    elif step == len(HEAD_STEPS):
        nxt = t("coach.head.nextLast")
    elif step == top or HEAD_STEPS[step]["ulevel"] > ulevel:
        nxt = t("coach.head.nextLocked")
    else:
        nxt = t("coach.copy.next", n=COPY_SESSIONS, acc=round(COPY_UP_ACC * 100), done=done)
    return {"available": ulevel >= 4, "early": early, "step": step, "of": len(HEAD_STEPS), "wpm": st["wpm"],
            "band": st["band"], "name": head_step_name(st), "change": change, "next": nxt, "minQ": HEAD_MIN_Q}


def mastered_chars(lessons):
    """Mastered characters (≥ 90 % of ≥ 5 trials in the last 20 character lessons) in Koch order."""
    tab = char_table(char_lessons(lessons)[-LEVEL_WINDOW:])
    return [c for c in KOCH if c in tab and tab[c][0] >= CHAR_MIN_N and tab[c][1] / tab[c][0] >= CHAR_ACC - 1e-9]


def copy_advice(lessons, ulevel):
    """Ladder step of copy behind for the next lesson. Returns {available, step, of, content, gapX, name, chars, change, next}."""
    cps = [r for r in lessons if mode_of(r) == MODE_COPY]
    step = step_of(cps[-1]) if cps else 1
    chars = mastered_chars(lessons)
    # Z-16 (0.9.9): before U3 an optional trial from mastered characters, steps 1–2 only (cannot lead to U4: needs step 6)
    early = ulevel < 3
    top = COPY_EARLY_LAST if early else len(COPY_STEPS)
    step = min(step, top)
    ses = copy_sessions(lessons, step)
    change = None
    if len(ses) >= COPY_SESSIONS:
        a, b = ses[0], ses[1]
        pct = t("coach.pctPair", a=round(b["acc"] * 100), b=round(a["acc"] * 100))
        if (a["acc"] >= COPY_UP_ACC - 1e-9 and b["acc"] >= COPY_UP_ACC - 1e-9 and step < top
                and (early or COPY_STEPS[step]["ulevel"] <= ulevel)):  # into U4 (step 7) only after reaching U4
            change = {"kind": "up", "from": step, "to": step + 1,
                      "why": t("coach.copy.up", acc=round(COPY_UP_ACC * 100), pct=pct)}
        elif a["acc"] < COPY_EASE_ACC and b["acc"] < COPY_EASE_ACC and step > 1:
            change = {"kind": "ease", "from": step, "to": step - 1,
                      "why": t("coach.copy.ease", acc=round(COPY_EASE_ACC * 100), pct=pct)}
    if change:
        step = change["to"]
    st = COPY_STEPS[step - 1]
    name = step_name(st)
    gap = t("coach.copy.gapNormal") if st["gapX"] <= 1 else t("coach.copy.gapX", x=fmt_num(st["gapX"]))
    if change:
        change["text"] = (t("coach.copy.changed", a=change["from"], b=step, name=name, gap=gap)
                          + (t("coach.copy.changedWpm", wpm=st["wpm"]) if st["wpm"] else "") + ").")
    if early:
        nxt = t("coach.copy.nextEarly", n=len(chars), last=COPY_EARLY_LAST)
    elif step == COPY_U3_LAST and ulevel < 4:
        nxt = t("coach.copy.nextU3Last", n=COPY_SESSIONS, acc=round(COPY_U4_ACC * 100))
    elif step == len(COPY_STEPS):
        nxt = t("coach.copy.nextU5Last")
    elif step == COPY_U4_LAST and ulevel < 5:
        nxt = t("coach.copy.nextU4Last", n=COPY_SESSIONS, acc=round(COPY_U5_ACC * 100), words=round(COPY_U5_WORDS * 100),
                wpm=COPY_U5_WPM)
    elif step < len(COPY_STEPS):
        nxt = t("coach.copy.next", n=COPY_SESSIONS, acc=round(COPY_UP_ACC * 100),
                done=min(len(ses) if not change else 0, COPY_SESSIONS))
    return {"available": ulevel >= 3 or len(chars) >= COPY_EARLY_MIN, "early": early, "step": step, "of": len(COPY_STEPS),
            "content": st["content"], "gapX": st["gapX"], "name": name, "gap": gap, "chars": chars,
            "wpm": st["wpm"], "markLag": st["markLag"], "ulevel": st["ulevel"], "band": st["band"],
            "change": change, "next": nxt, "last": ses[0] if ses and not change else None}


# ================= progress dashboard (M5) =================
# Regularity vs. progress. Days are counted in local time (users in Czechia); the client does not send its time.
TZ_NAME = "Europe/Prague"
DASH_DAYS = 28             # regularity calendar
DASH_WEEKS = 8             # weeks: minutes, days, added characters
DASH_SESSIONS = 30         # course by sessions
REGULAR_DAYS = 4           # a "regular" week = training on at least 4 days
TARGET_SHARE = 0.8         # a day met the goal at ≥ 80 % of the daily goal of minutes


def _tz():
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(TZ_NAME)
    except Exception:  # without tzdata: UTC (only shifts the day boundary)
        from datetime import timezone
        return timezone.utc


def _local_date(ms, tz):
    return datetime.fromtimestamp(ms / 1000, tz).date()


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def dashboard(lessons, level, prefs, now_ms):
    """Lessons (oldest first, fields at/level/dur_s/trials/acc/ttr/detail) → data for the Progress card."""
    from datetime import timedelta
    tz = _tz()
    today = _local_date(now_ms, tz)
    target = (prefs or {}).get("dayMin") or DEFAULT_DAY_MIN

    # minutes by days
    per_day = {}
    for r in lessons:
        ms = _ms(r["at"])
        if ms is None:
            continue
        d = _local_date(ms, tz)
        x = per_day.setdefault(d, [0.0, 0])
        x[0] += (r.get("dur_s") or 0) / 60
        x[1] += 1
    days = []
    for i in range(DASH_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        m, n = per_day.get(d, (0.0, 0))
        days.append({"d": d.isoformat(), "min": round(m, 1), "n": n,
                     "goal": m >= target * TARGET_SHARE - 1e-9 and m > 0})
    last14 = days[-14:]
    streak = 0
    for x in reversed(days if days[-1]["n"] else days[:-1]):  # today may still come
        if not x["n"]:
            break
        streak += 1
    first = min(per_day) if per_day else today
    regularity = {
        "span14": min(14, (today - first).days + 1),  # how many of the last 14 days the user has been training
        "days14": sum(1 for x in last14 if x["n"]), "goal14": sum(1 for x in last14 if x["goal"]),
        "min7": round(sum(x["min"] for x in days[-7:]) / 7, 1), "target": target, "streak": streak,
    }

    # weeks (Monday): minutes, active days, added characters
    def week_of(d):
        return d - timedelta(days=d.weekday())
    seq = [(r, _ms(r["at"])) for r in lessons]
    seq = [(r, ms) for r, ms in seq if ms is not None]
    added_at = []  # date of a lesson after which a character was added
    for i, (r, ms) in enumerate(seq):
        nxt = seq[i + 1][0]["level"] if i + 1 < len(seq) else level
        if nxt == (r.get("level") or 0) + 1:
            added_at.append(_local_date(ms, tz))
    w0 = week_of(today)
    weeks = []
    for i in range(DASH_WEEKS - 1, -1, -1):
        ws = w0 - timedelta(weeks=i)
        we = ws + timedelta(days=7)
        ds = [d for d in per_day if ws <= d < we]
        weeks.append({"w": ws.isoformat(), "min": round(sum(per_day[d][0] for d in ds), 1), "days": len(ds),
                      "added": sum(1 for d in added_at if ws <= d < we), "current": i == 0})

    # course by sessions
    ses_out = []
    prev = None  # the last character lesson from earlier sessions (the warm-up is compared with it)
    for s in sessions_of(lessons):
        zn = char_lessons(s)
        cp = [r for r in s if mode_of(r) == MODE_COPY]
        sm = session_summary(zn) if zn else None
        cs = copy_summary(cp) if cp else None  # M7: copy behind separately (a different meaning than TTR)
        if not sm and not cs:
            continue
        w = (_detail(zn[0]).get("warmup") or {}) if zn else {}
        fat = sum(1 for r in s if (_detail(r).get("fatigue") or {}).get("events"))  # M8: in copy behind too
        ses_out.append({
            "at": s[-1]["at"], "chars": max(r.get("level") or 0 for r in s),
            "acc": _r(sm["acc"]) if sm else None, "ttr": sm["ttr"] if sm else None,
            "min": round(sum((r.get("dur_s") or 0) for r in s) / 60, 1), "lessons": len(s),
            "warm": _r(w.get("acc")) if w.get("acc") is not None and prev else None,
            "prevEnd": _r(prev.get("acc")) if prev and w.get("acc") is not None else None,
            "gapH": w.get("gapH"), "fatigue": fat,
            "copy": {"acc": _r(cs["acc"]), "lagCh": cs["lagCh"], "lagMs": cs["lagMs"], "step": cs["step"],
                     "n": cs["n"], "wpm": cs["wpm"], "lagW": cs["lagW"],
                     "words": _r(cs["words"]) if cs["words"] is not None else None} if cs else None,
        })
        if zn:
            prev = zn[-1]
    ses_out = ses_out[-DASH_SESSIONS:]

    # retention: warm-up vs. end of the previous session (the last 5 sessions with a warm-up)
    wr = [s for s in ses_out if s["warm"] is not None][-5:]
    retention = None
    if wr:
        wa = sum(s["warm"] for s in wr) / len(wr)
        pe = sum(s["prevEnd"] for s in wr) / len(wr)
        retention = {"n": len(wr), "warm": _r(wa), "prevEnd": _r(pe), "keep": _r(wa / pe) if pe else None}

    return {"tz": TZ_NAME, "days": days, "regularity": regularity, "weeks": weeks, "sessions": ses_out,
            "retention": retention, "insight": insight(weeks, regularity, retention),
            "fatigue14": sum(s["fatigue"] for s in ses_out
                             if _ms(s["at"]) and _local_date(_ms(s["at"]), tz) > today - timedelta(days=14))}


def insight(weeks, reg, retention):
    """A short explanation of how regularity relates to progress – about the task, not the person (R1 ch. 5)."""
    done = [w for w in weeks if not w["current"] and w["min"] > 0]
    reg_w = [w for w in done if w["days"] >= REGULAR_DAYS]
    irr_w = [w for w in done if w["days"] < REGULAR_DAYS]
    out = []
    if reg_w and irr_w and sum(w["added"] for w in done) > 0:
        a = sum(w["added"] for w in reg_w) / len(reg_w)
        b = sum(w["added"] for w in irr_w) / len(irr_w)
        def one_decimal(x):
            return f"{x:.1f}".replace(".", t("fmt.decimal"))
        out.append(t("coach.insight.weeks", days=REGULAR_DAYS, a=one_decimal(a), b=one_decimal(b)))
    if retention and retention["keep"] is not None:
        k = round(retention["keep"] * 100)
        out.append(t("coach.insight.retention", warm=round(retention["warm"] * 100), prev=round(retention["prevEnd"] * 100))
                   + (t("coach.insight.retentionGood") if k >= 95 else t("coach.insight.retentionDrop")))
    if reg["span14"] >= 4 and reg["days14"] < reg["span14"] * 0.5:
        out.append(t("coach.insight.oftener"))
    elif reg["goal14"] >= 10:
        out.append(t("coach.insight.regular"))
    return out
