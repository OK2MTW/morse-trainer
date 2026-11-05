# SPDX-License-Identifier: EUPL-1.2
"""Trenér nad lekcemi (M4): dotazník → archetyp + modifikátory, kalibrace, odhad plánu, úrovně U1–U6, plato.

Vše jsou čisté funkce (bez DB a Flasku), testy v tests/test_coach_server.py.
Soukromí: odpovědi dotazníku se NEUKLÁDAJÍ (mohou prozrazovat zdravotní stav). Uloží se jen výsledek:
archetyp, modifikátory a preference. Modifikátory jsou pojmenované podle potřeby (čtení, psaní…), ne podle diagnózy.
"""
import json
from datetime import datetime

# ================= dotazník =================
# Každá otázka: id, text, možnosti [(hodnota, text)], volitelně "when" = (id otázky, {povolené hodnoty}).
QUESTIONS = [
    {"id": "age", "text": "Kolik ti je let?", "options": [
        ("child", "8–12"), ("teen", "13–17"), ("adult", "18–59"), ("senior", "60 a víc")]},
    {"id": "exp", "text": "Jakou máš zkušenost s Morseovou abecedou?", "options": [
        ("none", "Žádnou, začínám"),
        ("ear", "Kdysi jsem ji uměl(a) sluchem"),
        ("table", "Kdysi jsem ji uměl(a) z tabulky – počítal(a) jsem tečky a čárky"),
        ("active", "Používám ji, chci se zlepšit")]},
    {"id": "speed", "text": "Jakou rychlost přijímáš (nebo jsi přijímal(a))?", "when": ("exp", {"ear", "table", "active"}),
     "options": [("unknown", "Nevím"), ("slow", "Do 10 WPM"), ("mid", "10–18 WPM"), ("fast", "20 WPM a víc")]},
    {"id": "gaps", "text": "Co ti chybí nejvíc?", "when": ("exp", {"ear", "table", "active"}), "options": [
        ("most", "Skoro všechno"), ("numpunct", "Hlavně čísla a interpunkce"), ("few", "Jen pár znaků"),
        ("unknown", "Nevím")]},
    {"id": "time", "text": "Kolik času denně můžeš cvičit?", "options": [
        ("lt10", "Méně než 10 minut"), ("10to20", "10–20 minut"), ("20to40", "20–40 minut"), ("gt40", "Víc než 40 minut")]},
    {"id": "rhythm", "text": "Jak pravidelně budeš cvičit?", "options": [
        ("daily", "Skoro každý den"), ("often", "Několikrát týdně"), ("weekend", "Hlavně o víkendu"),
        ("irregular", "Nepravidelně, jak to vyjde")]},
    {"id": "pace", "text": "Jaké tempo učení ti vyhovuje?", "options": [
        ("slow", "Pomalu a jistě"), ("normal", "Normální"), ("fast", "Rychle, rád(a) se zapotím")]},
    {"id": "music", "text": "Hraješ na hudební nástroj nebo zpíváš?", "options": [
        ("yes", "Ano, pravidelně"), ("some", "Trochu nebo dřív"), ("no", "Ne")]},
    {"id": "reading", "text": "Jak ti jde čtení textu a písmen na obrazovce?", "options": [
        ("easy", "Bez potíží"), ("slow", "Čtu raději větší písmo"), ("hard", "Čtení mi dělá potíže")]},
    {"id": "typing", "text": "Jak ti jde psaní na klávesnici nebo ťukání na malé klávesy v mobilu?", "options": [
        ("easy", "Bez potíží"), ("slow", "Jde to, ale pomaleji"), ("hard", "Je to pro mě obtížné")]},
    {"id": "focus", "text": "Jak dlouho se vydržíš soustředit na jednu věc?", "options": [
        ("long", "Půl hodiny i déle"), ("mid", "10–20 minut"), ("short", "Spíš jen pár minut")]},
    {"id": "hearing", "text": "Jak slyšíš tóny (pípání)?", "options": [
        ("ok", "Bez potíží"), ("some", "Některé tóny slyším hůř"), ("hard", "Slyším hůř nebo používám sluchadlo")]},
    {"id": "errors", "text": "Jak na tebe působí chyby při učení?", "options": [
        ("fine", "Nevadí mi, učím se z nich"), ("some", "Trochu mě štvou"), ("upset", "Hodně mě rozhodí")]},
    {"id": "numbers", "text": "Zajímají tě podrobná čísla a grafy o pokroku?", "options": [
        ("yes", "Ano, podrobně"), ("basic", "Stačí přehled"), ("no", "Ne")]},
]
QMAP = {q["id"]: q for q in QUESTIONS}

ARCHETYPES = {
    # id: (název, priorita minut čistého drillu na 1 znak (od, do) – jen počáteční odhad před kalibrací)
    "Z01": ("Nováček – standard", (20, 60)),
    "Z02": ("Nováček – hudebně nadaný", (12, 40)),
    "Z03": ("Nováček – pozvolný", (30, 90)),
    "Z04": ("Nováček – málo času", (20, 60)),
    "Z05": ("Nováček – intenzivní", (15, 45)),
    "Z06": ("Dítě 8–12", (20, 70)),
    "Z07": ("Teenager", (15, 50)),
    "Z08": ("Senior 60+", (30, 100)),
    "Z09": ("Návrat – kdysi sluchem", (5, 20)),
    "Z10": ("Návrat – „počítač teček“", (20, 70)),
    "Z11": ("Návrat – chybí čísla a interpunkce", (8, 30)),
    "Z12": ("Aktivní 10–18 WPM", (3, 15)),
    "Z13": ("Aktivní 20+ WPM", (2, 10)),
    "Z14": ("Nepravidelný / víkendový", (25, 80)),
}
MODIFIERS = {
    "M15": "Čtení – větší písmo, méně textu",
    "M16": "Psaní – víc času na odpověď, větší klávesy",
    "M17": "Pozornost – kratší bloky, víc střídání",
    "M18": "Sluch – kontrola tónu a hlasitosti, sluchátka",
    "M19": "Citlivost na chyby – jemnější zpětná vazba",
    "M20": "Analytik – podrobné statistiky",
}
MODIFIER_ORDER = ["M18", "M16", "M15", "M17", "M19", "M20"]  # priorita, max. 2
MAX_MODIFIERS = 2


def clean_answers(raw):
    """Jen známé otázky a hodnoty; podmíněné otázky jen pokud platí podmínka."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for q in QUESTIONS:
        v = raw.get(q["id"])
        if v in {o[0] for o in q["options"]}:
            out[q["id"]] = v
    for q in QUESTIONS:
        w = q.get("when")
        if w and out.get(w[0]) not in w[1]:
            out.pop(q["id"], None)
    return out


def archetype_of(a):
    """Základní archetyp Z01–Z14 podle odpovědí (pořadí pravidel = priorita)."""
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


DAY_MIN = {"lt10": 10, "10to20": 15, "20to40": 30, "gt40": 40}  # cíl minut denně (strop 60 = upozornění)


def prefs_of(arch, mods, a):
    """Preference plynoucí z archetypu a modifikátorů. settings = návrh nastavení (klient ho použije)."""
    # délka bloku 5–10 min (R1); pozornost (M17) kratší
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
        fwpm = 12  # znak plnou rychlostí, aby nešlo počítat tečky; mezery delší
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
    """Odpovědi → {archetype, modifiers, prefs}. Odpovědi samotné se nevracejí ani neukládají."""
    a = clean_answers(raw)
    arch = archetype_of(a)
    mods = modifiers_of(a)
    return {"archetype": arch, "modifiers": mods, "prefs": prefs_of(arch, mods, a)}


def questions_json():
    return [{"id": q["id"], "text": q["text"], "options": [{"value": v, "label": t} for v, t in q["options"]],
             **({"when": {"q": q["when"][0], "in": sorted(q["when"][1])}} if q.get("when") else {})}
            for q in QUESTIONS]


# ================= kalibrace a odhad plánu (R1 kap. 4) =================
SET_SIZE = 51
CALIB_CHARS = 2       # kalibrace hotová po 2 přidaných znacích (nebo po 3 lekcích)
CALIB_LESSONS = 3
DEFAULT_DAY_MIN = 20


def additions(lessons, level):
    """Přidané znaky z lekcí [{at, level, dur_s}] (nejstarší první): [(úroveň, minuty na ní)].

    Přidání = po lekci na úrovni L následuje lekce (nebo aktuální pokrok) na L + 1. Ruční skoky se nepočítají.
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
    """Rozmezí kolem naměřené rychlosti – zužuje se s počtem přidaných znaků (rozptyl až 6×, R1)."""
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
        # data mají přednost před archetypem; bez přidaného znaku počítáme, že ten současný je skoro hotový
        rate = (total + (0 if n else mins.get(level, 0))) / max(n, 1)
        lo_m, hi_m = spread(max(n, 1))
        per = (rate * lo_m, rate * hi_m)
        source = "data"
    else:
        per = ARCHETYPES[arch][1]
        rate = None
        source = "prior"
    left = max(0, SET_SIZE - level)
    cur = mins.get(level, 0)
    # zbývající znaky + rozpracovaný nejnovější (minus minuty, které už na něm jsou)
    rem = [p * left + max(0, p - cur) if left else 0.0 for p in per]
    return {
        "source": source, "calibrated": source == "data", "added": n, "lessons": len(lessons),
        "rate": round(rate, 1) if rate is not None else None,
        "minPerChar": [round(per[0]), round(per[1])],
        "remainingChars": left, "remainingMin": [round(rem[0]), round(rem[1])],
        "dayMin": day, "days": [round(rem[0] / day, 1), round(rem[1] / day, 1)],
    }


# ================= sezení, úrovně U1–U6, plato (R1 kap. 8, 4) =================
SESSION_BREAK_MIN = 20     # stejné jako web/js/coach.js (test hlídá shodu)
LEVEL_WINDOW = 20          # statistika znaků pro U1 z posledních 20 lekcí
CHAR_MIN_N = 5             # znak musí zaznít aspoň 5×
CHAR_ACC = 0.9
U2_WPM = 20                # U2 → U3: plná rychlost 20/20 WPM
U2_ACC = 0.9
U2_TTR = {"pc": 600, "mobil": 800}  # medián TTR (ms) – odhad C, zpřesnit z dat; mobil má větší latenci
PLATEAU_SESSIONS = 3       # ≥ 3 sezení bez postupu = plato (vysvětlit)
PLATEAU_CHANGE = 5         # ≥ 5 sezení → navrhnout změnu plánu

ULEVELS = [
    {"id": 1, "name": "Nováček", "content": "Kochova sada, znaky po jednom", "mode": "znak, čeká na odpověď",
     "goal": "všech 51 znaků v sadě, každý ≥ 90 %"},
    {"id": 2, "name": "Začátečník", "content": "celá sada, zkracování mezer (Farnsworth), okamžité rozpoznání",
     "mode": "znak, čeká na odpověď", "goal": "plná rychlost 20/20 WPM, ≥ 90 %, medián reakce ≤ 600 ms (PC) / 800 ms (mobil)"},
    {"id": 3, "name": "Mírně pokročilý", "content": "skupiny, pseudoslova a krátká slova", "mode": "příjem ve skluzu (proud bez čekání)",
     "goal": "stabilní skluz ≥ 1 znak, ≥ 90 % po zarovnání, normální mezery"},
    {"id": 4, "name": "Pokročilý", "content": "slova, zkratky, Q-kódy, volací znaky", "mode": "skluz celého slova",
     "goal": "25 WPM, ≥ 90 % po zarovnání a slova ≥ 90 %"},
    {"id": 5, "name": "Expert", "content": "věty, QSO, rušení, různé tóny", "mode": "dlouhý skluz",
     "goal": "30–35 WPM"},
    {"id": 6, "name": "Mistr", "content": "provoz, závody, příjem v hlavě", "mode": "otázky k obsahu",
     "goal": "otevřené"},
]
MAX_COMPUTED_ULEVEL = 5    # M7: U3 → U4 ze skluzu; M8: U4 → U5; obsah U5+ zatím jen stav a kritéria
COPY_MIN_CHARS = 60        # M7: sezení ve skluzu se hodnotí od 60 vyslaných znaků (shodně s web/js/copy.js)


def mode_of(r):
    return r.get("mode") or "znak"


def znak_only(lessons):
    """Lekce po znacích (čeká na odpověď) – z nich se počítá statistika znaků, U1/U2, tempo a plato."""
    return [r for r in lessons if mode_of(r) == "znak"]


def _ms(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def sessions_of(lessons):
    """Lekce (nejstarší první) → seznam sezení (seznamy lekcí). Pauza ≥ 20 min mezi koncem a začátkem = nové."""
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
    d = r.get("detail")
    if isinstance(d, dict):
        return d
    try:
        return json.loads(d) if d else {}
    except ValueError:
        return {}


def char_table(lessons):
    """{znak: (n, správně)} z detailu lekcí."""
    t = {}
    for r in lessons:
        for x in _detail(r).get("perChar") or []:
            n = x.get("n") or 0
            if n and x.get("acc") is not None:
                a, b = t.get(x["ch"], (0, 0))
                t[x["ch"]] = (a + n, b + x["acc"] * n)
    return t


def u1_status(lessons, level):
    """Kolik znaků z 51 drží ≥ 90 % (z ≥ 5 pokusů) v posledních lekcích, a zda je hotovo."""
    t = char_table(znak_only(lessons)[-LEVEL_WINDOW:])
    good = sum(1 for n, c in t.values() if n >= CHAR_MIN_N and c / n >= CHAR_ACC - 1e-9)
    return {"good": good, "of": SET_SIZE, "done": level >= SET_SIZE and good >= SET_SIZE}


def session_summary(ses):
    """Sezení → {n, acc, ttr (vážený medián), device (převažující), full (vše 20/20 WPM)}."""
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
    """Úroveň z dat. Kritérium musí platit ve 2 po sobě jdoucích sezeních (R1 kap. 8).
    U1/U2 z lekcí po znacích, U3 → U4 z lekcí ve skluzu (jen když je U3 dosažená nebo spočítaná)."""
    zn = znak_only(lessons)
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
        if (u4 or (stored or 1) >= 4) and two(copy_u5_ok):
            return 5
        if u4:
            return 4
    return comp


def next_criteria(ulevel, lessons, level):
    """Co chybí do další úrovně – zpětná vazba o úkolu (ne o osobě)."""
    if ulevel == 1:
        st = u1_status(lessons, level)
        items = [f"znaky v sadě: {level} z {SET_SIZE}",
                 f"znaky s ≥ 90 % v posledních lekcích: {st['good']} z {SET_SIZE}",
                 "splnit ve 2 sezeních po sobě"]
        return {"target": 2, "items": items, "ratio": round(min(level, st["good"]) / SET_SIZE, 3)}
    if ulevel == 2:
        ses = sessions_of(znak_only(lessons))
        s = session_summary(ses[-1]) if ses else None
        items = ["rychlost znaku i mezer 20 WPM (zkracuj mezery postupně)",
                 "úspěšnost ≥ 90 %, medián reakce ≤ 600 ms na PC / 800 ms na mobilu",
                 "splnit ve 2 sezeních po sobě"]
        if s:
            items.append(f"poslední sezení: {round(s['acc'] * 100)} %, reakce {s['ttr'] or '–'} ms"
                         f"{'' if s['full'] else ', mezery ještě pod 20 WPM'}")
        return {"target": 3, "items": items, "ratio": None}
    if ulevel == 3:
        last = COPY_STEPS[COPY_U3_LAST - 1]
        items = [f"krok {last['step']} žebříku skluzu: {last['name']}, normální mezery mezi slovy",
                 f"tempo aspoň {U2_WPM}/{U2_WPM} WPM, ≥ {round(COPY_U4_ACC * 100)} % po zarovnání, "
                 f"≥ {COPY_MIN_CHARS} znaků v sezení",
                 f"skluz stabilní – během lekce neujíždí o víc než {COPY_DRIFT_MAX} znak",
                 "splnit ve 2 sezeních po sobě"]
        cs = copy_sessions(lessons)
        if cs:
            s = cs[0]
            items.append(f"poslední sezení ve skluzu: krok {s['step']}, {round(s['acc'] * 100)} %"
                         + (f", skluz {fmt_num(s['lagCh'])} zn." if s["lagCh"] is not None else ""))
        return {"target": 4, "items": items, "ratio": None}
    if ulevel == 4:
        last = COPY_STEPS[-1]
        items = [f"krok {last['step']} žebříku skluzu: {last['name']}, {last['wpm']} WPM",
                 f"≥ {round(COPY_U5_ACC * 100)} % po zarovnání a celá slova ≥ {round(COPY_U5_WORDS * 100)} %, "
                 f"≥ {COPY_MIN_CHARS} znaků v sezení",
                 f"skluz stabilní – během lekce neujíždí o víc než {COPY_DRIFT_MAX_U4} znaky (skluz o slovo je v pořádku)",
                 "splnit ve 2 sezeních po sobě"]
        cs = copy_sessions(lessons)
        if cs:
            s = cs[0]
            items.append(f"poslední sezení ve skluzu: krok {s['step']}, {s['wpm']} WPM, {round(s['acc'] * 100)} %"
                         + (f", slova {round(s['words'] * 100)} %" if s["words"] is not None else ""))
        return {"target": 5, "items": items, "ratio": None}
    return {"target": min(6, ulevel + 1), "items": ["věty, QSO a rušení (U5) připravujeme – zatím udržuj krok "
                                                     f"{len(COPY_STEPS)} žebříku skluzu"], "ratio": None}


def _key(r):
    return (r.get("level") or 0, r.get("wpm") or 0, r.get("fwpm") or 0)


def plateau(lessons, level):
    """≥ 3 sezení bez postupu (nový znak, rychlejší znak nebo kratší mezery) → vysvětlení a procesní ukazatel."""
    ses = sessions_of(znak_only(lessons))
    if not ses:
        return None
    flat = [r for s in ses for r in s]
    idx = {id(r): i for i, s in enumerate(ses) for r in s}
    last_prog = -1
    for a, b in zip(flat, flat[1:]):
        ka, kb = _key(a), _key(b)
        if any(y > x for x, y in zip(ka, kb)):
            last_prog = idx[id(a)]  # postup si vysloužilo sezení s lekcí před změnou
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
            proc = f"Reakce se zrychlila z {first['ttr']} na {last['ttr']} ms."
        elif last["acc"] >= first["acc"] + 0.02:
            proc = f"Úspěšnost vzrostla z {round(first['acc'] * 100)} na {round(last['acc'] * 100)} %."
    return {
        "sessions": n, "change": n >= PLATEAU_CHANGE, "process": proc,
        "text": ("Plato: už {n} sezení bez nového kroku. To je normální – dovednost se upevňuje a pokrok přichází "
                 "ve skocích, ne rovnoměrně.").format(n=n),
        "advice": ("Zkus na pár dní změnu: kratší lekce 2× denně s pauzou mezi nimi a zaměř se na znaky, "
                   "které se pletou (Pokrok → Kochova cesta, záměny). Pomáhá i rozcvička po spánku." if n >= PLATEAU_CHANGE else
                   "Pokračuj v pravidelných krátkých lekcích, na výsledku sezení nezáleží tolik jako na pravidelnosti."),
    }


def level_info(lessons, level, stored):
    """Úroveň pro API: max(uložená, z dat) – zpět se automaticky nevrací (jen resetem výcviku)."""
    comp = min(MAX_COMPUTED_ULEVEL, computed_ulevel(lessons, level, stored))
    cur = max(stored or 1, comp)
    return {"ulevel": cur, "computed": comp, "levels": ULEVELS, "next": next_criteria(cur, lessons, level)}


# ================= tempo: rychlost znaku a Farnsworthovy mezery (M6) =================
# Smyčka b pro tempo. Rozhoduje se mezi sezeními (potvrzení v dalším sezení, R1) a vždy jen o jeden prvek:
# v U1 je novým prvkem znak (tempo se jen ulehčuje), v U2 se zkracují mezery a pak zrychluje znak k 20/20 WPM.
# Bezstavové: počítá se jen ze sezení na AKTUÁLNÍM tempu, takže po změně (trenérem i ručně) se čeká na nová data.
SPEED_SESSIONS = 2         # rozhodnutí z posledních 2 sezení na stejném tempu
SPEED_MIN_TRIALS = 40      # sezení se počítá od 40 pokusů na daném tempu (kratší se přeskočí)
SPEED_UP_ACC = 0.9         # zrychlit: obě sezení ≥ 90 % …
SPEED_TTR_RATIO = 1.25     # … a reakce v posledním nejvýš 1,25× předchozího (stabilní)
SPEED_EASE_ACC = 0.75      # obě sezení < 75 % → delší mezery o 1 WPM (ulehčit)
FW_FAR = 6                 # mezery o ≥ 6 WPM pomalejší než znak → krok 2 WPM, jinak 1
FW_MIN = 5                 # nejdelší mezery (efektivní rychlost)
FW_PLATEAU_MIN = 10        # plato v U1 (≥ 5 sezení) prodlouží mezery o 2 WPM, nejvýš sem
FW_PLATEAU_STEP = 2
FLUENCY_S = 60             # blok plynulosti od U2 (konec lekce, nezapočítává se) …
FLUENCY_PLATEAU_S = 120    # … při platu v U2 delší


def speed_sessions(lessons, key):
    """Souhrny posledních sezení na tempu key = (wpm, fwpm), nejnovější první.
    Řada končí sezením bez lekce na tomto tempu; sezení s < 40 pokusy na tempu se přeskočí."""
    out = []
    for s in reversed(sessions_of(znak_only(lessons))):
        part = [r for r in s if (r.get("wpm"), r.get("fwpm")) == key]
        if not part:
            break
        sm = session_summary(part)
        if sm and sm["n"] >= SPEED_MIN_TRIALS:
            out.append(sm)
    return out


def _tempo(wpm, fwpm):
    return f"znak {wpm} WPM, mezery {fwpm} WPM" if fwpm < wpm else f"{wpm} WPM bez prodloužených mezer"


def speed_advice(lessons, level, ulevel, cur, plat=None):
    """Doporučené tempo. cur = {wpm, fwpm} (aktuální nastavení). Vrací {wpm, fwpm, change, next, fluencyS}.
    change = {kind, from, to, why} když se má tempo změnit (ease | gaps | chars | plateau)."""
    wpm, fwpm = int(cur.get("wpm") or 20), int(cur.get("fwpm") or 15)
    fwpm = min(fwpm, wpm)
    ses = speed_sessions(lessons, (wpm, fwpm))
    u2 = ulevel >= 2 and level >= SET_SIZE
    out = {"wpm": wpm, "fwpm": fwpm, "change": None, "sessions": len(ses),
           "fluencyS": (FLUENCY_PLATEAU_S if plat and plat.get("change") else FLUENCY_S) if u2 else 0}
    to, kind, why = None, None, None
    if len(ses) >= SPEED_SESSIONS:
        a, b = ses[0], ses[1]
        pct = f"{round(b['acc'] * 100)} % a {round(a['acc'] * 100)} %"
        stable = not (a["ttr"] and b["ttr"]) or a["ttr"] <= SPEED_TTR_RATIO * b["ttr"]
        if a["acc"] < SPEED_EASE_ACC and b["acc"] < SPEED_EASE_ACC and fwpm > FW_MIN:
            to, kind = (wpm, fwpm - 1), "ease"
            why = f"Dvě sezení pod {round(SPEED_EASE_ACC * 100)} % ({pct}) – delší mezery dají víc času na rozpoznání."
        elif u2 and a["acc"] >= SPEED_UP_ACC - 1e-9 and b["acc"] >= SPEED_UP_ACC - 1e-9 and stable:
            if fwpm < wpm:
                to, kind = (wpm, min(wpm, fwpm + (2 if wpm - fwpm >= FW_FAR else 1))), "gaps"
                why = f"Dvě sezení ≥ {round(SPEED_UP_ACC * 100)} % ({pct}) se stabilní reakcí – mezery se zkracují."
            elif wpm < U2_WPM:
                to, kind = (wpm + 1, fwpm), "chars"
                why = f"Dvě sezení ≥ {round(SPEED_UP_ACC * 100)} % ({pct}) bez prodloužených mezer – zrychluje se znak (mezery chvíli delší)."
        elif not u2 and plat and plat.get("change") and len(ses) >= PLATEAU_CHANGE and fwpm > FW_PLATEAU_MIN:
            to, kind = (wpm, max(FW_PLATEAU_MIN, fwpm - FW_PLATEAU_STEP)), "plateau"
            why = (f"Už {plat['sessions']} sezení bez nového znaku – změna plánu: delší mezery dají víc času "
                   "na rozpoznání, nový znak pak přijde snáz. Mezery se zase zkrátí po celé sadě.")
    if to:
        out["change"] = {"kind": kind, "from": {"wpm": wpm, "fwpm": fwpm}, "to": {"wpm": to[0], "fwpm": to[1]},
                         "why": why, "text": f"Trenér změnil tempo: {_tempo(wpm, fwpm)} → {_tempo(*to)}."}
        out["wpm"], out["fwpm"] = to
    # co dál (zpětná vazba o úkolu)
    if u2 and (fwpm < wpm or wpm < U2_WPM):
        nxt = (f"Další zkrácení mezer po {SPEED_SESSIONS} sezeních ≥ {round(SPEED_UP_ACC * 100)} % na stejném tempu "
               f"(zatím {min(len(ses), SPEED_SESSIONS)} z {SPEED_SESSIONS})." if fwpm < wpm else
               f"Zrychlení znaku po {SPEED_SESSIONS} sezeních ≥ {round(SPEED_UP_ACC * 100)} % (zatím {min(len(ses), SPEED_SESSIONS)}).")
    elif u2:
        nxt = ("Plné tempo 20/20 WPM – další krok je příjem ve skluzu (karta na Domů)." if ulevel >= 3 else
               "Plné tempo 20/20 WPM – po 2 sezeních s rychlou reakcí se otevře příjem ve skluzu (U3).")
    else:
        nxt = "Během Kochovy sady se tempo nezrychluje (nový prvek je znak); mezery se zkracují po zvládnutí celé sady."
    out["next"] = nxt
    out["tempo"] = _tempo(out["wpm"], out["fwpm"])
    return out


# ================= příjem ve skluzu: žebřík kroků U3 (M7) =================
# Jeden nový prvek najednou: obsah (skupiny → pseudoslova → slova) a zkracování mezery mezi slovy se střídají.
# Bezstavové jako tempo: krok = krok poslední lekce ve skluzu, rozhodují 2 poslední sezení na tomto kroku.
# M8 (U4, kroky 7–13): zkratky a Q-kódy → volací znaky → dlouhá slova (skluz celého slova) → směs → 21/23/25 WPM.
# wpm = rychlost znaku i mezer v lekci ve skluzu (None = nastavení z M6); markLag = značka slova k až po slově
# k+markLag (jen načasování zpětné vazby). U5 připojí další kroky (QSO, rušení, 27–35 WPM).
def _st(step, ul, content, gapX, name, wpm=None, markLag=1):
    return {"step": step, "ulevel": ul, "content": content, "gapX": gapX, "name": name, "wpm": wpm, "markLag": markLag}


COPY_STEPS = [
    _st(1, 3, "groups", 3.0, "skupiny 2–3 znaky"),
    _st(2, 3, "groups", 2.0, "skupiny 2–3 znaky"),
    _st(3, 3, "pseudo", 2.0, "pseudoslova 2–5 znaků"),
    _st(4, 3, "pseudo", 1.5, "pseudoslova 2–5 znaků"),
    _st(5, 3, "words", 1.5, "krátká slova"),
    _st(6, 3, "words", 1.0, "krátká slova"),
    _st(7, 4, "abbr", 1.0, "zkratky a Q-kódy", 20),
    _st(8, 4, "calls", 1.0, "volací znaky", 20),
    _st(9, 4, "long", 1.0, "delší slova 6–7 písmen (skluz celého slova)", 20, 2),
    _st(10, 4, "mix", 1.0, "směs: slova, zkratky, volací znaky", 20, 2),
    _st(11, 4, "mix", 1.0, "směs: slova, zkratky, volací znaky", 21, 2),
    _st(12, 4, "mix", 1.0, "směs: slova, zkratky, volací znaky", 23, 2),
    _st(13, 4, "mix", 1.0, "směs: slova, zkratky, volací znaky", 25, 2),
]
COPY_U3_LAST = 6           # poslední krok U3 (normální mezery, krátká slova)
COPY_SESSIONS = 2          # rozhodnutí z posledních 2 sezení na kroku
COPY_UP_ACC = 0.9          # obě ≥ 90 % po zarovnání → další krok
COPY_EASE_ACC = 0.75       # obě < 75 % → krok zpět
COPY_U4_ACC = 0.9          # U3 → U4 na posledním kroku
COPY_DRIFT_MAX = 1         # skluz „stabilní“ = během lekce neujíždí o víc než 1 znak
COPY_U5_ACC = 0.9          # M8: U4 → U5 na posledním kroku (25 WPM) …
COPY_U5_WORDS = 0.9        # … a celá slova ≥ 90 % (R1 kap. 8)
COPY_U5_WPM = 25
COPY_DRIFT_MAX_U4 = 3      # v U4 je skluz o slovo žádoucí, jen nesmí dál růst
KOCH = "KMURESNAPTLWI.JZ=FOY,VG5/Q92H38B?47C1D60X'-:()\"@+&!"  # pořadí jako web/js/charset.js


def fmt_num(x):
    return str(round(x, 1)).replace(".", ",").removesuffix(",0")


def _copy(r):
    return _detail(r).get("copy") or {}


def step_of(r):
    st = _copy(r).get("step")
    return st if isinstance(st, int) and 1 <= st <= len(COPY_STEPS) else 1


def copy_summary(part):
    """Lekce ve skluzu jednoho sezení → {n, acc, lagCh, lagMs, drift, step, full}."""
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
    """Souhrny sezení ve skluzu, nejnovější první. Sezení jen s lekcemi po znacích se přeskočí.
    S krokem: řada končí sezením, kde byl skluz jen na jiném kroku; sezení s < 60 znaky se přeskočí."""
    out = []
    for s in reversed(sessions_of(lessons)):
        cp = [r for r in s if mode_of(r) == "skluz"]
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
    """U4 → U5 (M8): poslední krok, ≥ 25 WPM, ≥ 90 % po zarovnání, celá slova ≥ 90 %, skluz neujíždí."""
    return (sm["step"] == len(COPY_STEPS) and sm["wpm"] >= COPY_U5_WPM and sm["acc"] >= COPY_U5_ACC - 1e-9
            and sm["words"] is not None and sm["words"] >= COPY_U5_WORDS - 1e-9
            and (sm["drift"] is None or sm["drift"] <= COPY_DRIFT_MAX_U4))


def mastered_chars(lessons):
    """Zvládnuté znaky (≥ 90 % z ≥ 5 pokusů v posledních 20 lekcích po znacích) v Kochově pořadí."""
    t = char_table(znak_only(lessons)[-LEVEL_WINDOW:])
    return [c for c in KOCH if c in t and t[c][0] >= CHAR_MIN_N and t[c][1] / t[c][0] >= CHAR_ACC - 1e-9]


def copy_advice(lessons, ulevel):
    """Krok žebříku skluzu pro další lekci. Vrací {available, step, of, content, gapX, name, chars, change, next}."""
    cps = [r for r in lessons if mode_of(r) == "skluz"]
    step = step_of(cps[-1]) if cps else 1
    ses = copy_sessions(lessons, step)
    change = None
    if len(ses) >= COPY_SESSIONS:
        a, b = ses[0], ses[1]
        pct = f"{round(b['acc'] * 100)} % a {round(a['acc'] * 100)} %"
        if (a["acc"] >= COPY_UP_ACC - 1e-9 and b["acc"] >= COPY_UP_ACC - 1e-9 and step < len(COPY_STEPS)
                and COPY_STEPS[step]["ulevel"] <= ulevel):  # do U4 (krok 7) až po dosažení U4
            change = {"kind": "up", "from": step, "to": step + 1,
                      "why": f"Dvě sezení ≥ {round(COPY_UP_ACC * 100)} % ({pct}) – další krok."}
        elif a["acc"] < COPY_EASE_ACC and b["acc"] < COPY_EASE_ACC and step > 1:
            change = {"kind": "ease", "from": step, "to": step - 1,
                      "why": f"Dvě sezení pod {round(COPY_EASE_ACC * 100)} % ({pct}) – krok zpět, ať je čas na upevnění."}
    if change:
        step = change["to"]
    st = COPY_STEPS[step - 1]
    gap = "normální mezera mezi slovy" if st["gapX"] <= 1 else f"mezera mezi slovy {fmt_num(st['gapX'])}×"
    if change:
        change["text"] = (f"Příjem ve skluzu: krok {change['from']} → {step} ({st['name']}, {gap}"
                          + (f", {st['wpm']} WPM" if st["wpm"] else "") + ").")
    if step == COPY_U3_LAST and ulevel < 4:
        nxt = (f"Poslední krok U3 – po {COPY_SESSIONS} sezeních ≥ {round(COPY_U4_ACC * 100)} % se stabilním skluzem "
               "je hotová úroveň U3 a otevře se U4 (zkratky, Q-kódy, volací znaky, 21–25 WPM).")
    elif step == len(COPY_STEPS) and ulevel >= 5:
        nxt = "Úroveň U4 je hotová. Věty, QSO a rušení (U5) připravujeme – tento krok slouží k udržování."
    elif step == len(COPY_STEPS):
        nxt = (f"Poslední krok U4 – po {COPY_SESSIONS} sezeních ≥ {round(COPY_U5_ACC * 100)} % a celých slovech "
               f"≥ {round(COPY_U5_WORDS * 100)} % na {COPY_U5_WPM} WPM je hotová úroveň U4.")
    elif step < len(COPY_STEPS):
        nxt = (f"Další krok po {COPY_SESSIONS} sezeních ≥ {round(COPY_UP_ACC * 100)} % na tomto kroku "
               f"(zatím {min(len(ses) if not change else 0, COPY_SESSIONS)} z {COPY_SESSIONS}).")
    return {"available": ulevel >= 3, "step": step, "of": len(COPY_STEPS), "content": st["content"],
            "gapX": st["gapX"], "name": st["name"], "gap": gap, "chars": mastered_chars(lessons),
            "wpm": st["wpm"], "markLag": st["markLag"], "ulevel": st["ulevel"],
            "change": change, "next": nxt, "last": ses[0] if ses and not change else None}


# ================= dashboard pokroku (M5) =================
# Pravidelnost vs. pokrok. Dny se počítají v místním čase (uživatelé v ČR); klient čas nepředává.
TZ_NAME = "Europe/Prague"
DASH_DAYS = 28             # kalendář pravidelnosti
DASH_WEEKS = 8             # týdny: minuty, dny, přidané znaky
DASH_SESSIONS = 30         # průběh po sezeních
REGULAR_DAYS = 4           # „pravidelný“ týden = trénink aspoň 4 dny
TARGET_SHARE = 0.8         # den splnil cíl při ≥ 80 % denního cíle minut


def _tz():
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(TZ_NAME)
    except Exception:  # bez tzdata: UTC (jen posun hranice dne)
        from datetime import timezone
        return timezone.utc


def _local_date(ms, tz):
    return datetime.fromtimestamp(ms / 1000, tz).date()


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def dashboard(lessons, level, prefs, now_ms):
    """Lekce (nejstarší první, pole at/level/dur_s/trials/acc/ttr/detail) → data pro kartu Pokrok."""
    from datetime import timedelta
    tz = _tz()
    today = _local_date(now_ms, tz)
    target = (prefs or {}).get("dayMin") or DEFAULT_DAY_MIN

    # minuty po dnech
    per_day = {}
    for r in lessons:
        t = _ms(r["at"])
        if t is None:
            continue
        d = _local_date(t, tz)
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
    for x in reversed(days if days[-1]["n"] else days[:-1]):  # dnešek ještě může přijít
        if not x["n"]:
            break
        streak += 1
    first = min(per_day) if per_day else today
    regularity = {
        "span14": min(14, (today - first).days + 1),  # kolik z posledních 14 dní už uživatel trénuje
        "days14": sum(1 for x in last14 if x["n"]), "goal14": sum(1 for x in last14 if x["goal"]),
        "min7": round(sum(x["min"] for x in days[-7:]) / 7, 1), "target": target, "streak": streak,
    }

    # týdny (pondělí): minuty, aktivní dny, přidané znaky
    def week_of(d):
        return d - timedelta(days=d.weekday())
    seq = [(r, _ms(r["at"])) for r in lessons]
    seq = [(r, t) for r, t in seq if t is not None]
    added_at = []  # datum lekce, po které přibyl znak
    for i, (r, t) in enumerate(seq):
        nxt = seq[i + 1][0]["level"] if i + 1 < len(seq) else level
        if nxt == (r.get("level") or 0) + 1:
            added_at.append(_local_date(t, tz))
    w0 = week_of(today)
    weeks = []
    for i in range(DASH_WEEKS - 1, -1, -1):
        ws = w0 - timedelta(weeks=i)
        we = ws + timedelta(days=7)
        ds = [d for d in per_day if ws <= d < we]
        weeks.append({"w": ws.isoformat(), "min": round(sum(per_day[d][0] for d in ds), 1), "days": len(ds),
                      "added": sum(1 for d in added_at if ws <= d < we), "current": i == 0})

    # průběh po sezeních
    ses_out = []
    prev = None  # poslední lekce po znacích z dřívějších sezení (rozcvička se srovnává s ní)
    for s in sessions_of(lessons):
        zn = znak_only(s)
        cp = [r for r in s if mode_of(r) == "skluz"]
        sm = session_summary(zn) if zn else None
        cs = copy_summary(cp) if cp else None  # M7: skluz zvlášť (jiný význam než TTR)
        if not sm and not cs:
            continue
        w = (_detail(zn[0]).get("warmup") or {}) if zn else {}
        fat = sum(1 for r in s if (_detail(r).get("fatigue") or {}).get("events"))  # M8: i ve skluzu
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

    # zapamatování: rozcvička vs. konec předchozího sezení (posledních 5 sezení s rozcvičkou)
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
    """Krátké vysvětlení vztahu pravidelnosti a pokroku – o úkolu, ne o osobě (R1 kap. 5)."""
    done = [w for w in weeks if not w["current"] and w["min"] > 0]
    reg_w = [w for w in done if w["days"] >= REGULAR_DAYS]
    irr_w = [w for w in done if w["days"] < REGULAR_DAYS]
    out = []
    if reg_w and irr_w and sum(w["added"] for w in done) > 0:
        a = sum(w["added"] for w in reg_w) / len(reg_w)
        b = sum(w["added"] for w in irr_w) / len(irr_w)
        def cz(x):
            return f"{x:.1f}".replace(".", ",")
        out.append(f"V týdnech s tréninkem aspoň {REGULAR_DAYS} dny přibylo v průměru "
                   f"{cz(a)} znaku za týden, v ostatních týdnech {cz(b)}.")
    if retention and retention["keep"] is not None:
        k = round(retention["keep"] * 100)
        out.append(f"Po pauze držíš {round(retention['warm'] * 100)} % (konec předchozího sezení "
                   f"{round(retention['prevEnd'] * 100)} %)" + (" – znaky si dobře pamatuješ." if k >= 95 else
                   " – mírný pokles po pauze je normální a není to regres; rozcvička ho srovná."))
    if reg["span14"] >= 4 and reg["days14"] < reg["span14"] * 0.5:
        out.append("Pro rychlejší pokrok pomáhá trénovat častěji a kratčeji – ideálně denně, klidně 2× 10–15 min.")
    elif reg["goal14"] >= 10:
        out.append("Pravidelnost je výborná – právě ta dělá většinu pokroku.")
    return out
