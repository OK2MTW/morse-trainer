// SPDX-License-Identifier: EUPL-1.2
// Karta Pokrok (M5): pravidelnost tréninku vs. pokrok. Data počítá server (GET /api/coach → dashboard).
// Grafy jsou jednoduché SVG (jedna řada = jedna barva, žádné dvě osy), hodnoty i v tabulce / title.

const SVG = 'http://www.w3.org/2000/svg';
const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)} %`);
const cz = (x) => String(x).replace('.', ',');

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
const dateCz = (iso) => new Date(iso).toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric' });

function tile(value, label) {
  const t = el('div', 'tile');
  t.append(el('div', 'tile-val', value), el('div', 'tile-lbl', label));
  return t;
}

/** Kalendář posledních 28 dní (po–ne), sytost = minuty vůči dennímu cíli. */
function calendar(days, target) {
  const wrap = el('div', 'cal');
  for (const w of ['po', 'út', 'st', 'čt', 'pá', 'so', 'ne']) wrap.append(el('div', 'cal-h', w));
  const first = new Date(`${days[0].d}T12:00:00`);
  const offset = (first.getDay() + 6) % 7;
  for (let i = 0; i < offset; i++) wrap.append(el('div', 'cal-pad'));
  days.forEach((x, i) => {
    const q = !x.n ? 0 : x.goal ? 3 : x.min >= target * 0.4 ? 2 : 1;
    const c = el('div', `cal-d d${q}${i === days.length - 1 ? ' today' : ''}`);
    c.title = `${dateCz(`${x.d}T12:00:00`)}: ${x.n ? `${cz(x.min)} min, ${x.n} lekcí` : 'bez tréninku'}`;
    c.textContent = String(new Date(`${x.d}T12:00:00`).getDate());
    wrap.append(c);
  });
  return wrap;
}

/** Spojnicový graf jedné řady: points [{x: label, y, tip}], meze osy y. */
function lineChart(points, { min, max, fmt, step = false }) {
  const W = 320, H = 120, L = 34, R = 8, T = 8, B = 18;
  const s = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', class: 'chart' });
  const xs = (i) => L + (points.length < 2 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const ys = (v) => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  for (const v of [min, (min + max) / 2, max]) {
    s.append(sv('line', { x1: L, x2: W - R, y1: ys(v), y2: ys(v) }, 'grid'));
    const t = sv('text', { x: L - 4, y: ys(v) + 3, 'text-anchor': 'end' }, 'axis');
    t.textContent = fmt(v);
    s.append(t);
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
      const t = sv('text', { x: xs(i), y: H - 4, 'text-anchor': i ? 'end' : 'start' }, 'axis');
      t.textContent = lbl;
      s.append(t);
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
  card.append(el('h2', null, 'Pokrok a pravidelnost'));
  root.append(card);
  if (!dash) {
    card.append(el('p', 'hint', 'Přehled se ukáže po první synchronizaci se serverem.'));
    return;
  }
  const r = dash.regularity;
  const tiles = el('div', 'tiles');
  tiles.append(
    tile(String(r.streak), r.streak === 1 ? 'den v řadě' : r.streak >= 2 && r.streak <= 4 ? 'dny v řadě' : 'dní v řadě'),
    tile(`${r.days14}/14`, 'dní s tréninkem'),
    tile(`${cz(r.min7)}`, `min denně (7 d), cíl ${r.target}`),
  );
  card.append(tiles);
  card.append(el('h3', null, 'Posledních 28 dní'), calendar(dash.days, r.target));
  const leg = el('p', 'hint cal-legend');
  leg.textContent = `Sytější = víc minut; plná barva = splněný denní cíl (${r.target} min).`;
  card.append(leg);

  for (const t of dash.insight || []) card.append(el('p', 'insight', t));
  if (dash.fatigue14) {
    card.append(el('p', 'hint', `Za posledních 14 dní se v ${dash.fatigue14} lekcích ukázala únava. Pomáhají kratší bloky s pauzou a trénink v odpočinutém stavu.`));
  }

  const ses = dash.sessions || [];
  if (ses.length) {
    const c2 = el('div', 'card');
    c2.append(el('h2', null, `Průběh po sezeních (${ses.length})`));
    const lbl = (s) => dateCz(s.at);
    const maxC = Math.max(...ses.map((s) => s.chars));
    c2.append(chartBlock('Znaky v sadě', lineChart(
      ses.map((s) => ({ x: lbl(s), y: s.chars, tip: `${lbl(s)}: ${s.chars} znaků` })),
      { min: Math.max(0, Math.min(...ses.map((s) => s.chars)) - 1), max: Math.max(maxC + 1, 4), fmt: (v) => String(Math.round(v)), step: true },
    )));
    c2.append(chartBlock('Úspěšnost sezení', lineChart(
      ses.map((s) => ({ x: lbl(s), y: s.acc, tip: `${lbl(s)}: ${pct(s.acc)}, ${cz(s.min)} min` })),
      { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
    ), 'Trenér drží úspěšnost v lekci kolem 85 %, takže tady nečekej stálý růst – pokrok ukazují znaky a reakce.'));
    const tt = ses.filter((s) => s.ttr != null).map((s) => s.ttr);
    if (tt.length) {
      const hi = Math.ceil(Math.max(...tt) / 200) * 200;
      c2.append(chartBlock('Medián reakce', lineChart(
        ses.map((s) => ({ x: lbl(s), y: s.ttr, tip: `${lbl(s)}: ${s.ttr ?? '–'} ms` })),
        { min: 0, max: Math.max(hi, 400), fmt: (v) => `${Math.round(v)}` },
      ), 'ms od konce znaku po stisk – níž je lépe. Po přidání znaku se obvykle na chvíli zvedne.'));
    }
    const wr = ses.filter((s) => s.warm != null);
    if (wr.length) {
      c2.append(chartBlock('Rozcvička po pauze (zapamatování)', lineChart(
        wr.map((s) => ({ x: lbl(s), y: s.warm, tip: `${lbl(s)}: rozcvička ${pct(s.warm)}, konec předchozího sezení ${pct(s.prevEnd)}` })),
        { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
      ), 'Úspěšnost v prvních 90 s sezení – nejlepší měřítko toho, co si pamatuješ přes pauzu a spánek.'));
    }
    // M7: příjem ve skluzu – úspěšnost po zarovnání a skluz (jiný význam než reakce, proto zvlášť)
    const cs = ses.filter((s) => s.copy);
    if (cs.length) {
      c2.append(chartBlock('Skluz: úspěšnost po zarovnání', lineChart(
        cs.map((s) => ({ x: lbl(s), y: s.copy.acc, tip: `${lbl(s)}: krok ${s.copy.step}${s.copy.wpm ? `, ${s.copy.wpm} WPM` : ''}, ${pct(s.copy.acc)}`
          + `${s.copy.words != null ? `, slova ${pct(s.copy.words)}` : ''}, ${s.copy.n} znaků` })),
        { min: 0.5, max: 1, fmt: (v) => `${Math.round(v * 100)}` },
      ), 'Lekce ve skluzu. Krok žebříku se zvyšuje po 2 sezeních ≥ 90 %, po 2 sezeních pod 75 % se ulehčí.'));
      const lag = cs.filter((s) => s.copy.lagCh != null);
      if (lag.length) {
        const hi = Math.max(2, Math.ceil(Math.max(...lag.map((s) => s.copy.lagCh))));
        c2.append(chartBlock('Skluz (medián, znaky)', lineChart(
          cs.map((s) => ({ x: lbl(s), y: s.copy.lagCh, tip: `${lbl(s)}: ${cz(s.copy.lagCh)} zn.${s.copy.lagW != null ? ` (${cz(s.copy.lagW)} sl.)` : ''}, ${s.copy.lagMs ?? '–'} ms` })),
          { min: 0, max: hi, fmt: (v) => cz(Math.round(v * 10) / 10) },
        ), 'O kolik znaků za vysílačem píšeš. Delší a stabilní skluz je cíl – hlava drží víc znaků, v U4 celá slova.'));
      }
    }
    root.append(c2);
  }

  const c3 = el('div', 'card');
  c3.append(el('h2', null, 'Týdny'));
  const tb = el('table', 'weeks');
  const hr = el('tr');
  for (const h of ['týden od', 'dní', 'minut', 'nové znaky']) hr.append(el('th', null, h));
  tb.append(hr);
  const maxMin = Math.max(1, ...dash.weeks.map((w) => w.min));
  for (const w of [...dash.weeks].reverse()) {
    const tr = el('tr', w.current ? 'current' : null);
    tr.append(el('td', null, `${dateCz(`${w.w}T12:00:00`)}${w.current ? ' (teď)' : ''}`), el('td', null, String(w.days)));
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
