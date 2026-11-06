// SPDX-License-Identifier: EUPL-1.2
// Progress card (M5): training regularity vs. progress. The server computes the data (GET /api/coach → dashboard).
// Charts are simple SVG (one series = one colour, no dual axes), values also in a table / title.
import { t, fmtNum, fmtDate } from './i18n.js';

const SVG = 'http://www.w3.org/2000/svg';
const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)} %`);
const num = (x) => fmtNum(x);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function sv(tag, attrs = {}, cls = null) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (cls) e.setAttribute('class', cls);
  return e;
}
const dateShort = (iso) => fmtDate(iso, { day: 'numeric', month: 'numeric' });

function tile(value, label) {
  const box = el('div', 'tile');
  box.append(el('div', 'tile-val', value), el('div', 'tile-lbl', label));
  return box;
}

/** Short weekday names Monday…Sunday in the current language. */
function weekdays() {
  const monday = new Date(2024, 0, 1, 12); // 1 Jan 2024 was a Monday
  return Array.from({ length: 7 }, (_, i) => fmtDate(monday.getTime() + i * 86400000, { weekday: 'short' }));
}

/** Calendar of the last 28 days (Mon–Sun), saturation = minutes relative to the daily goal. */
function calendar(days, target) {
  const wrap = el('div', 'cal');
  for (const w of weekdays()) wrap.append(el('div', 'cal-h', w));
  const first = new Date(`${days[0].d}T12:00:00`);
  const offset = (first.getDay() + 6) % 7;
  for (let i = 0; i < offset; i++) wrap.append(el('div', 'cal-pad'));
  days.forEach((x, i) => {
    const q = !x.n ? 0 : x.goal ? 3 : x.min >= target * 0.4 ? 2 : 1;
    const c = el('div', `cal-d d${q}${i === days.length - 1 ? ' today' : ''}`);
    c.title = `${dateShort(`${x.d}T12:00:00`)}: ${x.n ? t('dash.dayLessons', { min: num(x.min), n: x.n }) : t('dash.noTraining')}`;
    c.textContent = String(new Date(`${x.d}T12:00:00`).getDate());
    wrap.append(c);
  });
  return wrap;
}

/** Line chart of one series: points [{x: label, y, tip}], y axis limits. */
function lineChart(points, { min, max, fmt, step = false }) {
  const W = 320, H = 120, L = 34, R = 8, T = 8, B = 18;
  const s = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', class: 'chart' });
  const xs = (i) => L + (points.length < 2 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const ys = (v) => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  for (const v of [min, (min + max) / 2, max]) {
    s.append(sv('line', { x1: L, x2: W - R, y1: ys(v), y2: ys(v) }, 'grid'));
    const tx = sv('text', { x: L - 4, y: ys(v) + 3, 'text-anchor': 'end' }, 'axis');
    tx.textContent = fmt(v);
    s.append(tx);
  }
  const pts = points.map((p, i) => (p.y == null ? null : [xs(i), ys(Math.min(max, Math.max(min, p.y)))]));
  let d = '';
  let prev = null;
  for (const p of pts) {
    if (!p) { prev = null; continue; }
    if (!prev) d += `M${p[0]},${p[1]}`;
    else d += step ? `H${p[0]}V${p[1]}` : `L${p[0]},${p[1]}`;
    prev = p;
  }
  s.append(sv('path', { d }, 'series'));
  if (points.length) {
    for (const [i, lbl] of [[0, points[0].x], [points.length - 1, points.at(-1).x]]) {
      const tx = sv('text', { x: xs(i), y: H - 4, 'text-anchor': i ? 'end' : 'start' }, 'axis');
      tx.textContent = lbl;
      s.append(tx);
      if (points.length === 1) break;
    }
  }
  pts.forEach((p, i) => {
    if (!p) return;
    if (i === pts.length - 1 || points.length <= 12) s.append(sv('circle', { cx: p[0], cy: p[1], r: 3 }, 'dot'));
    const hit = sv('circle', { cx: p[0], cy: p[1], r: 9 }, 'hit');
    const tt = sv('title');
    tt.textContent = points[i].tip;
    hit.append(tt);
    s.append(hit);
  });
  return s;
}

function chartBlock(title, svg, note) {
  const b = el('div', 'chart-block');
  b.append(el('h3', null, title), svg);
  if (note) b.append(el('p', 'hint', note));
  return b;
}

/**
 * @param {HTMLElement} root
 * @param {object|null} dash  coachInfo.data.dashboard
 */
export function renderDashboard(root, dash) {
  root.textContent = '';
  const card = el('div', 'card');
  card.append(el('h2', null, t('dash.title')));
  root.append(card);
  if (!dash) {
    card.append(el('p', 'hint', t('dash.empty')));
    return;
  }
  const r = dash.regularity;
  const tiles = el('div', 'tiles');
  tiles.append(
    tile(String(r.streak), t('dash.streak', { n: r.streak })),
    tile(`${r.days14}/14`, t('dash.days14')),
    tile(`${num(r.min7)}`, t('dash.min7', { target: r.target })),
  );
  card.append(tiles);
  card.append(el('h3', null, t('dash.last28')), calendar(dash.days, r.target));
  const leg = el('p', 'hint cal-legend');
  leg.textContent = t('dash.legend', { target: r.target });
  card.append(leg);

  for (const line of dash.insight || []) card.append(el('p', 'insight', line));
  if (dash.fatigue14) {
    card.append(el('p', 'hint', t('dash.fatigue14', { n: dash.fatigue14 })));
  }

  const ses = dash.sessions || [];
  if (ses.length) {
    const c2 = el('div', 'card');
    c2.append(el('h2', null, t('dash.sessions', { n: ses.length })));
    const lbl = (s) => dateShort(s.at);
    const maxC = Math.max(...ses.map((s) => s.chars));
    c2.append(chartBlock(t('dash.chars'), lineChart(
      ses.map((s) => ({ x: lbl(s), y: s.chars, tip: `${lbl(s)}: ${t('dash.charsTip', { n: s.chars })}` })),
      { min: Math.max(0, Math.min(...ses.map((s) => s.chars)) - 1), max: Math.max(maxC + 1, 4), fmt: (v) => String(Math.round(v)), step: true },
    )));
    c2.append(chartBlock(t('dash.acc'), lineChart(
      ses.map((s) => ({ x: lbl(s), y: s.acc, tip: `${lbl(s)}: ${pct(s.acc)}, ${num(s.min)} min` })),
      { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
    ), t('dash.accNote')));
    const tt = ses.filter((s) => s.ttr != null).map((s) => s.ttr);
    if (tt.length) {
      const hi = Math.ceil(Math.max(...tt) / 200) * 200;
      c2.append(chartBlock(t('dash.ttr'), lineChart(
        ses.map((s) => ({ x: lbl(s), y: s.ttr, tip: `${lbl(s)}: ${s.ttr ?? '–'} ms` })),
        { min: 0, max: Math.max(hi, 400), fmt: (v) => `${Math.round(v)}` },
      ), t('dash.ttrNote')));
    }
    const wr = ses.filter((s) => s.warm != null);
    if (wr.length) {
      c2.append(chartBlock(t('dash.warm'), lineChart(
        wr.map((s) => ({ x: lbl(s), y: s.warm, tip: `${lbl(s)}: ${t('dash.warmTip', { warm: pct(s.warm), prev: pct(s.prevEnd) })}` })),
        { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
      ), t('dash.warmNote')));
    }
    // M7: copy behind – accuracy after alignment and lag (a different meaning than reaction, hence separate)
    const cs = ses.filter((s) => s.copy);
    if (cs.length) {
      c2.append(chartBlock(t('dash.copyAcc'), lineChart(
        cs.map((s) => ({ x: lbl(s), y: s.copy.acc, tip: `${lbl(s)}: ${t('dash.copyStep', { step: s.copy.step })}${s.copy.wpm ? `, ${s.copy.wpm} WPM` : ''}, ${pct(s.copy.acc)}`
          + `${s.copy.words != null ? `, ${t('dash.copyWords', { pct: pct(s.copy.words) })}` : ''}, ${t('dash.charsTip', { n: s.copy.n })}` })),
        { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
      ), t('dash.copyAccNote')));
      const lag = cs.filter((s) => s.copy.lagCh != null);
      if (lag.length) {
        const hi = Math.max(2, Math.ceil(Math.max(...lag.map((s) => s.copy.lagCh))));
        c2.append(chartBlock(t('dash.lag'), lineChart(
          cs.map((s) => ({ x: lbl(s), y: s.copy.lagCh, tip: `${lbl(s)}: ${t('dash.lagChars', { n: num(s.copy.lagCh) })}${s.copy.lagW != null ? ` (${t('dash.lagWords', { n: num(s.copy.lagW) })})` : ''}, ${s.copy.lagMs ?? '–'} ms` })),
          { min: 0, max: hi, fmt: (v) => num(Math.round(v * 10) / 10) },
        ), t('dash.lagNote')));
      }
    }
    root.append(c2);
  }

  const c3 = el('div', 'card');
  c3.append(el('h2', null, t('dash.weeks')));
  const tb = el('table', 'weeks');
  const hr = el('tr');
  for (const h of ['dash.colWeek', 'dash.colDays', 'dash.colMin', 'dash.colNew']) hr.append(el('th', null, t(h)));
  tb.append(hr);
  const maxMin = Math.max(1, ...dash.weeks.map((w) => w.min));
  for (const w of [...dash.weeks].reverse()) {
    const tr = el('tr', w.current ? 'current' : null);
    tr.append(el('td', null, `${dateShort(`${w.w}T12:00:00`)}${w.current ? ` ${t('dash.now')}` : ''}`), el('td', null, String(w.days)));
    const td = el('td', 'bar-cell');
    const bar = el('span', 'wbar');
    bar.style.width = `${Math.round((w.min / maxMin) * 100)}%`;
    td.append(bar, el('span', null, String(Math.round(w.min))));
    tr.append(td, el('td', null, w.added ? `+${w.added}` : '–'));
    tb.append(tr);
  }
  c3.append(tb);
  root.append(c3);
}
