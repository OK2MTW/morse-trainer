// SPDX-License-Identifier: EUPL-1.2
// Karta Statistika: Kochova „cesta“ znaků (naučené / aktuální / další) a detail znaku.
// Žádné tečky a čárky – metoda je čistě sluchová, znak se dá jen přehrát.
import { KOCH_ORDER } from './charset.js';
import { trendArrow } from './drill.js';

const ARROW = { up: '↑', down: '↓', flat: '→' };
const ARROW_TITLE = { up: 'zlepšení', down: 'zhoršení', flat: 'beze změny' };
const MIN_N = 5; // od kolika pokusů barvíme podle úspěšnosti

const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)} %`);
const ms = (x) => (x == null ? '–' : `${x} ms`);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Třída barvy podle úspěšnosti (q4 = výborně … q1 = slabé). */
export function accClass(s) {
  if (!s || s.n < MIN_N || s.acc == null) return 'q0';
  if (s.acc >= 0.95) return 'q4';
  if (s.acc >= 0.85) return 'q3';
  if (s.acc >= 0.7) return 'q2';
  return 'q1';
}

/** Záměny nového znaku s ostatními oběma směry: {znak: počet} – pro výběr kontrastů v rozlišování. */
export function confusionsWith(chars, target) {
  const out = {};
  for (const x of chars[target]?.conf || []) out[x.ans] = (out[x.ans] || 0) + x.n;
  for (const [ch, s] of Object.entries(chars)) {
    for (const x of s.conf || []) if (x.ans === target && ch !== target) out[ch] = (out[ch] || 0) + x.n;
  }
  return out;
}

/**
 * Vykreslí kartu Statistika.
 * @param {HTMLElement} root
 * @param {{stats: object, level: number, onPlay: (ch: string) => void}} o
 */
export function renderStats(root, { stats, level, onPlay }) {
  root.textContent = '';
  const chars = stats.chars || {};

  const card = el('div', 'card');
  card.append(el('h2', null, 'Kochova cesta'));
  card.append(el('p', 'hint', stats.lessons
    ? `Z posledních ${stats.lessons} lekcí. Naučeno ${level} z ${KOCH_ORDER.length} znaků. Barva = úspěšnost, číslo = medián reakce. Klepni na znak pro detail.`
    : 'Zatím žádná data – statistika se ukáže po první odeslané lekci.'));
  const grid = el('div', 'path');
  const detail = el('div', 'card');
  detail.hidden = true;

  KOCH_ORDER.forEach((c, i) => {
    const s = chars[c];
    const state = i < level - 1 ? 'learned' : i === level - 1 ? 'current' : i === level ? 'next' : 'future';
    const b = el('button', `tile ${state} ${state === 'future' || state === 'next' ? 'q0' : accClass(s)}`);
    b.type = 'button';
    b.append(el('b', null, c));
    const arrow = s ? trendArrow(s.recent, s.before) : null;
    const sub = state === 'next' ? 'další' : state === 'future' ? '' : (s && s.ttr != null ? String(s.ttr) : '–');
    b.append(el('small', null, sub));
    if (arrow) {
      const a = el('i', `arrow ${arrow}`, ARROW[arrow]);
      a.title = ARROW_TITLE[arrow];
      b.append(a);
    }
    if (state === 'future') b.disabled = true;
    b.setAttribute('aria-label', `${c}: ${state === 'next' ? 'další znak' : s ? `${pct(s.acc)}, ${ms(s.ttr)}` : 'bez dat'}`);
    b.addEventListener('click', () => {
      for (const t of grid.querySelectorAll('.tile.sel')) t.classList.remove('sel');
      b.classList.add('sel');
      renderDetail(detail, c, chars, state, onPlay);
      detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    grid.append(b);
  });
  card.append(grid);

  const legend = el('p', 'legend hint');
  for (const [q, t] of [['q4', '≥ 95 %'], ['q3', '≥ 85 %'], ['q2', '≥ 70 %'], ['q1', '< 70 %'], ['q0', 'málo dat']]) {
    const sp = el('span', `lg ${q}`, t);
    legend.append(sp);
  }
  card.append(legend);
  root.append(card, detail);
}

function renderDetail(box, c, chars, state, onPlay) {
  box.textContent = '';
  box.hidden = false;
  const s = chars[c];
  const head = el('div', 'detail-head');
  head.append(el('span', 'detail-char', c));
  const play = el('button', null, '▶ Přehrát');
  play.type = 'button';
  play.addEventListener('click', () => onPlay(c));
  head.append(play);
  box.append(head);

  if (!s) {
    box.append(el('p', 'hint', state === 'next' ? 'Tento znak přibude, až splníš podmínky postupu.' : 'Zatím bez dat.'));
    return;
  }
  const t = el('table', 'diag');
  const tb = el('tbody');
  const arrow = trendArrow(s.recent, s.before);
  const rows = [
    ['Pokusů', String(s.n)],
    ['Úspěšnost', pct(s.acc)],
    ['Medián reakce', ms(s.ttr)],
    ['Posledních 5 lekcí', s.recent ? `${pct(s.recent.acc)} · ${ms(s.recent.ttr)}` : '–'],
    ['Předtím', s.before ? `${pct(s.before.acc)} · ${ms(s.before.ttr)}` : '–'],
    ['Trend', arrow ? `${ARROW[arrow]} ${ARROW_TITLE[arrow]}` : 'málo dat'],
  ];
  for (const [k, v] of rows) {
    const tr = el('tr');
    tr.append(el('th', null, k), el('td', null, v));
    tb.append(tr);
  }
  t.append(tb);
  box.append(t);

  // vývoj po lekcích: sloupec = úspěšnost
  if (s.hist?.length) {
    box.append(el('h3', 'sub', 'Vývoj po lekcích'));
    const bars = el('div', 'bars');
    for (const h of s.hist) {
      const bar = el('div', `bar ${accClass({ n: MIN_N, acc: h.acc })}`);
      bar.style.height = `${Math.max(4, Math.round((h.acc ?? 0) * 100))}%`;
      const d = new Date(h.at).toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric' });
      bar.title = `${d}: ${pct(h.acc)}, ${ms(h.ttr)}, ${h.n}×`;
      bars.append(bar);
    }
    box.append(bars);
  }

  const heardAs = (s.conf || []).map((x) => `„${x.ans}“ ${x.n}×`);
  const mistaken = [];
  for (const [ch, o] of Object.entries(chars)) {
    for (const x of o.conf || []) if (x.ans === c && ch !== c) mistaken.push([ch, x.n]);
  }
  mistaken.sort((a, b) => b[1] - a[1]);
  box.append(el('h3', 'sub', 'Nejčastější záměny'));
  box.append(el('p', 'hint', heardAs.length ? `Místo „${c}“ jsi zadal(a): ${heardAs.join(', ')}.` : `„${c}“ sis s ničím nespletl(a).`));
  if (mistaken.length) {
    box.append(el('p', 'hint', `„${c}“ jsi zadal(a) místo: ${mistaken.slice(0, 5).map(([ch, n]) => `„${ch}“ ${n}×`).join(', ')}.`));
  }
}
