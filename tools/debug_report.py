# SPDX-License-Identifier: EUPL-1.2
"""V1: overview of the debug traces of training (read-only access to the database).

  .venv/bin/python -m tools.debug_report [NICK] [--lessons N] [--events]
      → per lesson: course of the reaction (fifths of the lesson), errors, timeouts, repeats, pauses, leaving the app,
        audio state, suspicious tone times; at the end application errors. --events also prints the raw events of the
        last lesson. The old name `python -m tools.ladeni [--lekci N] [--udalosti]` still works.
"""
import argparse
import json
import sqlite3
import statistics
from collections import Counter

from server.coach import MODE_CHAR
from server.db import DB_PATH


def med(xs):
    return round(statistics.median(xs)) if xs else None


def char_summary(ev):
    trials, cur, out = [], None, Counter()
    hidden_at, hidden_ms, tone_bad = None, 0, 0
    for e in ev:
        t, typ = e[0], e[1]
        d = e[2] if len(e) > 2 else None
        if typ == "p":
            cur = {"ch": d[0], "t": t, "phase": d[5] if len(d) > 5 else "", "wpm": d[1], "fwpm": d[2]}
            if d[3] is not None and not (0 < d[3] < 3000):
                tone_bad += 1
        elif typ == "a" and cur:
            trials.append({**cur, "ans": d[0], "ttr": d[1], "ok": bool(d[2])})
            cur = None
        elif typ == "to" and cur:
            trials.append({**cur, "ans": None, "ttr": None, "ok": False, "to": True})
            cur = None
        elif typ == "vis":
            if d == "hidden":
                hidden_at = t
            elif hidden_at is not None:
                hidden_ms += t - hidden_at
                hidden_at = None
        out[typ] += 1
    return trials, out, hidden_ms, tone_bad


def report_char(row, data, show_events):
    ev = data.get("ev", [])
    meta = data.get("meta", {})
    trials, cnt, hidden_ms, tone_bad = char_summary(ev)
    n = len(trials)
    end = data.get("end", {})
    print(f"\n== {row['at'][:16].replace('T', ' ')}  {row['nick']}  char  level {meta.get('level')} "
          f"({meta.get('chars', '')})  new: {meta.get('fresh') or '-'}  {meta.get('device')}"
          f"{' PWA' if meta.get('standalone') else ''}{' outside' if meta.get('public') else ''}"
          f"{'  ABORTED ' + str(end.get('aborted')) if end.get('aborted') else ''}")
    s = meta.get("set", {})
    a = meta.get("audio") or {}
    print(f"   settings {s.get('wpm')}/{s.get('fwpm')} WPM, {s.get('freq')} Hz, {s.get('min')} min · audio {a.get('state')} "
          f"latency {a.get('base')}/{a.get('output')} ms · duration {round(data.get('durMs', 0) / 60000, 1)} min")
    if not n:
        print("   no trials")
        return
    ok = [x for x in trials if x["ok"]]
    print(f"   trials {n}, accuracy {round(100 * len(ok) / n)} %, median reaction {med([x['ttr'] for x in ok])} ms, "
          f"timeouts {cnt['to']}, repeats {cnt['rep']}, corrections {cnt['fix']}")
    k = 5
    parts = []
    for i in range(k):
        seg = trials[i * n // k:(i + 1) * n // k]
        sok = [x for x in seg if x["ok"]]
        if seg:
            parts.append(f"{round(100 * len(sok) / len(seg))}%/{med([x['ttr'] for x in sok])}ms")
    print(f"   course by fifths (acc./reaction): {'  '.join(parts)}")
    errs = Counter(f"{x['ch']}→{x['ans'] or '∅'}" for x in trials if not x["ok"])
    if errs:
        print(f"   errors: {', '.join(f'{k} {v}×' for k, v in errs.most_common(8))}")
    after_err = [trials[i]["ok"] for i in range(1, n) if not trials[i - 1]["ok"]]
    if after_err:
        print(f"   correct after an error: {round(100 * sum(after_err) / len(after_err))} % ({len(after_err)})")
    fresh = meta.get("fresh") or ""
    if fresh:
        nf = [x for x in trials if x["ch"] in fresh]
        print(f"   new character: {len(nf)} trials ({round(100 * len(nf) / n)} %), accuracy "
              f"{round(100 * sum(x['ok'] for x in nf) / len(nf)) if nf else '-'} %")
    other = {k: v for k, v in cnt.items() if k in ("pause", "resume", "vis", "audio", "net", "error", "fat", "fatChoice",
                                                    "pw", "flu", "warmEnd", "rewarmEnd", "pagehide")}
    if other or hidden_ms:
        print(f"   events: {', '.join(f'{k} {v}×' for k, v in other.items())}"
              f"{f', outside the app {round(hidden_ms / 1000)} s' if hidden_ms else ''}")
    for e in ev:
        if e[1] in ("audio", "error", "fat", "fatChoice", "resume", "pw", "pwEnd"):
            print(f"     {e[0] / 1000:7.1f} s  {e[1]} {json.dumps(e[2], ensure_ascii=False) if len(e) > 2 else ''}")
    if tone_bad:
        print(f"   ! suspicious tone end for {tone_bad} characters (outside 0–3000 ms)")
    if show_events:
        for e in ev:
            print(f"     {e[0] / 1000:7.1f} s  {e[1]} {json.dumps(e[2], ensure_ascii=False) if len(e) > 2 else ''}")


def report_copy(row, data, show_events):
    meta = data.get("meta", {})
    ev = data.get("ev", [])
    cnt = Counter(e[1] for e in ev)
    rounds = [e[2] for e in ev if e[1] == "roundEnd"]
    accs = [r["acc"] for r in rounds if r.get("acc") is not None]
    print(f"\n== {row['at'][:16].replace('T', ' ')}  {row['nick']}  copy  step {meta.get('plan', {}).get('step')} "
          f"{meta.get('wpm')}/{meta.get('fwpm')} WPM  lines {len(rounds)}  accuracy per line "
          f"{' '.join(str(round(a * 100)) for a in accs)}  backspaces {cnt['bs']}  pauses {cnt['pause']}")
    if show_events:
        for e in ev:
            print(f"     {e[0] / 1000:7.1f} s  {e[1]} {json.dumps(e[2], ensure_ascii=False) if len(e) > 2 else ''}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Overview of debug traces of training (read-only).")
    ap.add_argument("nick", nargs="?", help="only this user")
    ap.add_argument("--lessons", "--lekci", dest="lessons", type=int, default=10, help="number of recent lessons")
    ap.add_argument("--events", "--udalosti", dest="events", action="store_true", help="raw events of the last lesson")
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    where, args = ("WHERE u.nick = ?", (a.nick,)) if a.nick else ("", ())
    rows = con.execute(f"SELECT t.*, u.nick FROM traces t JOIN users u ON u.id = t.user_id {where} "
                       f"ORDER BY t.at DESC LIMIT ?", (*args, a.lessons)).fetchall()
    for i, r in enumerate(reversed(rows)):
        data = json.loads(r["data"])
        last = i == len(rows) - 1
        if r["kind"] == "klic":   # 0.12.3: key page recording (tones for the decoder), analysed separately
            k = data.get("end") or {}
            print(f"\n== {r['at'][:16]} {r['nick']} key recording: {len(k.get('tones', []))} tones, "
                  f"{len(k.get('ex', []))} tasks, meant {k.get('meant')!r}, decoded {k.get('text')!r}")
            continue
        (report_char if r["kind"] == MODE_CHAR else report_copy)(r, data, a.events and last)
    errs = con.execute(f"SELECT e.at, e.data, u.nick FROM client_errors e JOIN users u ON u.id = e.user_id {where} "
                       f"ORDER BY e.at DESC LIMIT 20", args).fetchall()
    if errs:
        print("\n== Application errors (newest):")
        for e in errs:
            d = json.loads(e["data"])
            print(f"   {e['at'][:16]} {e['nick']}: {d.get('msg')} @ {d.get('src', '').rsplit('/', 1)[-1]}:{d.get('line')} "
                  f"[{d.get('view')}]")
    if not rows and not errs:
        print("No debug traces yet.")


if __name__ == "__main__":
    main()
