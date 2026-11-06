// SPDX-License-Identifier: EUPL-1.2
// Statistics card: the Koch "path" of characters (learned / current / next) and character detail.
// No dots and dashes – the method is purely aural, a character can only be played.
import { t, fmtDate } from './i18n.js';
import { KOCH_ORDER } from './charset.js';
import { trendArrow } from './drill.js';

const ARROW = { up: '↑', down: '↓', flat: '→' };
const arrowTitle = (a) => t(`stats.trend.${a}`);
const MIN_N = 5; // from how many trials we colour by accuracy

const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)} %`);
const ms = (x) => (x == null ? '–' : `${x} ms`);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/** Colour class by accuracy (q4 = excellent … q1 = weak). */
export function accClass(s) {
  if (!s || s.n < MIN_N || s.acc == null) return 'q0';
  if (s.acc >= 0.95) return 'q4';
  if (s.acc >= 0.85) return 'q3';
  if (s.acc >= 0.7) return 'q2';
  return 'q1';
}

/** Confusions of the new character with others in both directions: {char: count} – for choosing discrimination contrasts. */
export function confusionsWith(chars, target) {
  const out = {};
  for (const x of chars[target]?.conf || []) out[x.ans] = (out[x.ans] || 0) + x.n;
  for (const [ch, s] of Object.entries(chars)) {
    for (const x of s.conf || []) if (x.ans === target && ch !== target) out[ch] = (out[ch] || 0) + x.n;
  }
  return out;
}

/**
 * Renders the Statistics card.
 * @param {HTMLElement} root
 * @param {{stats: object, level: number, onPlay: (ch: string) => void}} o
 */
export function renderStats(root, { stats, level, onPlay }) {
  root.textContent = '';
  const chars = stats.chars || {};

  const card = el('div', 'card');
  card.append(el('h2', null, t('stats.title')));
  card.append(el('p', 'hint', stats.lessons
    ? t('stats.intro', { n: stats.lessons, level, of: KOCH_ORDER.length })
    : t('stats.empty')));
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
    const sub = state === 'next' ? t('stats.next') : state === 'future' ? '' : (s && s.ttr != null ? String(s.ttr) : '–');
    b.append(el('small', null, sub));
    if (arrow) {
      const a = el('i', `arrow ${arrow}`, ARROW[arrow]);
      a.title = arrowTitle(arrow);
      b.append(a);
    }
    if (state === 'future') b.disabled = true;
    b.setAttribute('aria-label', `${c}: ${state === 'next' ? t('stats.nextChar') : s ? `${pct(s.acc)}, ${ms(s.ttr)}` : t('stats.noData')}`);
    b.addEventListener('click', () => {
      for (const x of grid.querySelectorAll('.tile.sel')) x.classList.remove('sel');
      b.classList.add('sel');
      renderDetail(detail, c, chars, state, onPlay);
      detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    grid.append(b);
  });
  card.append(grid);

  const legend = el('p', 'legend hint');
  for (const [q, label] of [['q4', '≥ 95 %'], ['q3', '≥ 85 %'], ['q2', '≥ 70 %'], ['q1', '< 70 %'], ['q0', t('stats.fewData')]]) {
    const sp = el('span', `lg ${q}`, label);
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
  const play = el('button', null, t('stats.play'));
  play.type = 'button';
  play.addEventListener('click', () => onPlay(c));
  head.append(play);
  box.append(head);

  if (!s) {
    box.append(el('p', 'hint', state === 'next' ? t('stats.nextHint') : t('stats.noDataYet')));
    return;
  }
  const table = el('table', 'diag');
  const tb = el('tbody');
  const arrow = trendArrow(s.recent, s.before);
  const rows = [
    [t('stats.trials'), String(s.n)],
    [t('stats.acc'), pct(s.acc)],
    [t('result.ttrTitle'), ms(s.ttr)],
    [t('stats.recent'), s.recent ? `${pct(s.recent.acc)} · ${ms(s.recent.ttr)}` : '–'],
    [t('stats.before'), s.before ? `${pct(s.before.acc)} · ${ms(s.before.ttr)}` : '–'],
    [t('result.colTrend'), arrow ? `${ARROW[arrow]} ${arrowTitle(arrow)}` : t('stats.fewData')],
  ];
  for (const [k, v] of rows) {
    const tr = el('tr');
    tr.append(el('th', null, k), el('td', null, v));
    tb.append(tr);
  }
  table.append(tb);
  box.append(table);

  // development by lessons: bar = accuracy
  if (s.hist?.length) {
    box.append(el('h3', 'sub', t('stats.history')));
    const bars = el('div', 'bars');
    for (const h of s.hist) {
      const bar = el('div', `bar ${accClass({ n: MIN_N, acc: h.acc })}`);
      bar.style.height = `${Math.max(4, Math.round((h.acc ?? 0) * 100))}%`;
      const d = fmtDate(h.at, { day: 'numeric', month: 'numeric' });
      bar.title = `${d}: ${pct(h.acc)}, ${ms(h.ttr)}, ${h.n}×`;
      bars.append(bar);
    }
    box.append(bars);
  }

  const heardAs = (s.conf || []).map((x) => t('stats.quoted', { ch: x.ans, n: x.n }));
  const mistaken = [];
  for (const [ch, o] of Object.entries(chars)) {
    for (const x of o.conf || []) if (x.ans === c && ch !== c) mistaken.push([ch, x.n]);
  }
  mistaken.sort((a, b) => b[1] - a[1]);
  box.append(el('h3', 'sub', t('stats.confTitle')));
  box.append(el('p', 'hint', heardAs.length ? t('stats.heardAs', { ch: c, list: heardAs.join(', ') }) : t('stats.noConf', { ch: c })));
  if (mistaken.length) {
    box.append(el('p', 'hint', t('stats.mistaken', { ch: c, list: mistaken.slice(0, 5).map(([ch, n]) => t('stats.quoted', { ch, n })).join(', ') })));
  }
}
