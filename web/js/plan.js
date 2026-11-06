// SPDX-License-Identifier: EUPL-1.2
// "Personal plan" card on the home screen (M4): plan type from the questionnaire, estimate from calibration,
// level U1–U6, plateau. The server computes the data (GET /api/coach); here they are only displayed.
import { t, fmtNum } from './i18n.js';

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

// preference value → translation key (values are stored by the server)
const PREF_KEYS = {
  keyboard: { tiles: 'plan.pref.tiles' },
  feedback: { gentle: 'plan.pref.gentle' },
  stats: { detail: 'plan.pref.detail' },
};

/** Text with the settings the questionnaire suggested. */
export function prefsSummary(prefs) {
  if (!prefs || !prefs.settings) return '';
  const s = prefs.settings;
  const out = [t('plan.prefLesson', { min: s.lessonMin }), t('plan.prefStart', { wpm: s.wpm }),
    t('plan.prefGaps', { fwpm: s.fwpm }), t('plan.prefDay', { min: prefs.dayMin })];
  for (const [k, map] of Object.entries(PREF_KEYS)) if (map[prefs[k]]) out.push(t(map[prefs[k]]));
  if (prefs.toneCheck) out.push(t('plan.pref.toneCheck'));
  if (prefs.slowAnswer) out.push(t('plan.pref.slowAnswer'));
  return out.join(' · ');
}

/** Range of days → readable text ("5–9 days", "3–6 weeks", "2–4 months"). */
export function daysText(lo, hi) {
  if (hi < 1.5) return t('plan.fewDays');
  const range = (a, b, key) => {
    const x = Math.max(1, Math.round(a)), y = Math.max(x, Math.round(b));
    return t(key, { range: x === y ? String(x) : `${x}–${y}`, n: y });
  };
  if (hi < 14) return range(lo, hi, 'plan.rangeDays');
  if (hi < 70) return range(lo / 7, hi / 7, 'plan.rangeWeeks');
  return range(lo / 30, hi / 30, 'plan.rangeMonths');
}

/** Plan estimate (calibration): minutes per character and time to the full set, always as a range. */
function planBlock(p) {
  const box = el('div', 'plan-est');
  if (p.remainingChars === 0) {
    box.append(el('p', 'plan-line', t('plan.fullSet')));
    return box;
  }
  const [lo, hi] = p.minPerChar;
  box.append(el('p', 'plan-line plan-range', t('plan.wholeSet', { time: daysText(p.days[0], p.days[1]) })));
  box.append(el('p', 'plan-line hint', t('plan.estimateLine', { day: p.dayMin, n: p.remainingChars, lo, hi })));
  box.append(el('p', 'plan-line hint', p.source === 'data'
    ? t('plan.fromData', { n: p.added }) + (p.rate != null ? t('plan.fromDataRate', { rate: fmtNum(p.rate) }) : '') + t('plan.fromDataEnd')
    : t('plan.fromPrior')));
  return box;
}

/** Level U1–U6: level strip, description of the current one and what is missing for the next (feedback about the task). */
function levelBlock(lv, isNew) {
  const box = el('div', 'plan-level');
  const strip = el('div', 'ulevels');
  for (const u of lv.levels) {
    const s = el('span', u.id < lv.ulevel ? 'done' : u.id === lv.ulevel ? 'cur' : '', `U${u.id}`);
    s.title = `${u.name}: ${u.content}`;
    strip.append(s);
  }
  box.append(strip);
  const cur = lv.levels.find((u) => u.id === lv.ulevel);
  if (cur) {
    box.append(el('p', 'plan-line', `${isNew ? `${t('plan.newLevel')} ` : ''}U${cur.id} ${cur.name} – ${cur.content}.`));
  }
  const nx = lv.next;
  const target = lv.levels.find((u) => u.id === nx?.target);
  if (nx && target && target.id > lv.ulevel) {
    box.append(el('p', 'plan-line hint', t('plan.toLevel', { id: target.id, name: target.name })));
    const ul = el('ul', 'hint');
    for (const item of nx.items) ul.append(el('li', null, item));
    box.append(ul);
  }
  return box;
}

/** Plateau: explanation, the process indicator that improves, and advice (≥ 5 sessions = a change is suggested). */
function plateauBlock(p) {
  const box = el('div', 'plateau');
  box.append(el('p', 'plan-line', p.text));
  if (p.process) box.append(el('p', 'plan-line hint', t('plan.improving', { what: p.process })));
  box.append(el('p', 'plan-line hint', p.advice));
  return box;
}

/**
 * Renders the plan card. info = response of GET /api/coach (or null), onQuiz = open the questionnaire.
 */
export function renderPlan(root, info, { onQuiz } = {}) {
  root.textContent = '';
  if (info?.levelInfo) root.append(levelBlock(info.levelInfo, info.ulevelNew));
  if (info?.plan) root.append(planBlock(info.plan));
  if (info?.plateau) root.append(plateauBlock(info.plateau));
  if (info?.speed) {
    // M6: pace and what is needed for the next step (about the task, not the person)
    const sp = info.speed;
    root.append(el('p', 'plan-line', t(sp.auto ? 'plan.tempoAuto' : 'plan.tempoManual', { tempo: sp.tempo })));
    root.append(el('p', 'plan-line hint', sp.next + (sp.fluencyS ? ` ${t('plan.fluency', { s: sp.fluencyS })}` : '')));
  }
  if (info?.copy?.available) {
    // M7: copy-behind ladder
    const cp = info.copy;
    root.append(el('p', 'plan-line', t('plan.copy', { step: cp.step, of: cp.of, name: cp.name, gap: cp.gap })));
    root.append(el('p', 'plan-line hint', `${cp.next} ${t('plan.copyKeep')}`));
  }
  if (!info || !info.archetype) {
    root.append(el('p', 'hint', t('plan.quizIntro')));
    const b = el('button', null, t('plan.quizButton'));
    b.type = 'button';
    b.addEventListener('click', () => onQuiz?.());
    root.append(b);
    return;
  }
  root.append(el('p', 'plan-line', t('plan.type', { name: info.archetypeName || info.archetype })));
  if (info.modifierNames?.length) root.append(el('p', 'plan-line hint', t('plan.modifiers', { list: info.modifierNames.join(' · ') })));
  const ps = prefsSummary(info.prefs);
  if (ps) root.append(el('p', 'plan-line hint', ps));
  if (info.prefs?.entryTest) {
    root.append(el('p', 'plan-line hint', t('plan.entryTest')));
  }
  const b = el('button', null, t('plan.editAnswers'));
  b.type = 'button';
  b.addEventListener('click', () => onQuiz?.());
  root.append(b);
}
