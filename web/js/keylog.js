// SPDX-License-Identifier: EUPL-1.2
// 0.14.3: summary of the key event log for the acceptance test of the HW key (spec H-42 (1)) – pure logic, ported to
// tests/keylog.py. Events {at (ms), code, down} in time order → per key: presses (keydown–keyup pairs), lengths
// split into dots and dashes (two groups when their medians differ ≥ LOG_SPLIT, as a machine keyer makes them),
// median / min / max, WPM from the dot; errors: keydown again without keyup (lost keyup / doubled keydown), keyup
// without keydown, held at the end.

export const KEYLOG_MAX = 2000;   // events kept for the summary (100 elements = 200 events)
export const LOG_SPLIT = 1.8;     // dots / dashes: the largest jump between sorted lengths ≥ 1.8×

const median = (a) => {
  const s = [...a].sort((x, y) => x - y);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
};
const stats = (a) => (a.length ? { n: a.length, med: median(a), min: Math.min(...a), max: Math.max(...a) } : null);

/** Lengths → {dot, dash, all} stats; dot/dash null without two clear groups. */
export function lengthGroups(lens) {
  const s = [...lens].sort((x, y) => x - y);
  let at = -1;
  let best = 0;
  for (let i = 1; i < s.length; i++) {
    const r = s[i] / Math.max(1, s[i - 1]);
    if (r > best) { best = r; at = i; }
  }
  if (at < 0 || best < LOG_SPLIT) return { dot: null, dash: null, all: stats(s) };
  return { dot: stats(s.slice(0, at)), dash: stats(s.slice(at)), all: stats(s) };
}

/** Summary of events [{at, code, down}] → {events, ms, keys: [{code, n, dot, dash, all, wpm}], dup, orphan, open}. */
export function logSummary(events) {
  const open = new Map();
  const lens = new Map();
  let dup = 0;
  let orphan = 0;
  for (const e of events) {
    if (!lens.has(e.code)) lens.set(e.code, []);
    if (e.down) {
      if (open.has(e.code)) dup += 1;
      open.set(e.code, e.at);
    } else if (!open.has(e.code)) {
      orphan += 1;
    } else {
      lens.get(e.code).push(e.at - open.get(e.code));
      open.delete(e.code);
    }
  }
  const keys = [...lens.entries()].map(([code, l]) => {
    const g = lengthGroups(l);
    return { code, n: l.length, ...g, wpm: g.dot ? 1200 / g.dot.med : null };
  });
  return {
    events: events.length, ms: events.length ? events.at(-1).at - events[0].at : 0, keys, dup, orphan, open: open.size,
  };
}
