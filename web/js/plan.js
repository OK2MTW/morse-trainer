// SPDX-License-Identifier: EUPL-1.2
// Karta „Osobní plán“ na domovské obrazovce (M4): typ plánu z dotazníku, odhad z kalibrace, úroveň U1–U6, plato.
// Data počítá server (GET /api/coach), tady se jen zobrazují.

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const PREF_TEXT = {
  keyboard: { tiles: 'velké klávesy (připravuje se)' },
  feedback: { gentle: 'jemnější zpětná vazba' },
  stats: { detail: 'podrobné statistiky' },
};

/** Text s nastavením, které dotazník navrhl. */
export function prefsSummary(prefs) {
  if (!prefs || !prefs.settings) return '';
  const s = prefs.settings;
  const out = [`lekce ${s.lessonMin} min`, `začátek: znak ${s.wpm} WPM`, `mezery ${s.fwpm} WPM`, `cíl ${prefs.dayMin} min denně`];
  for (const [k, map] of Object.entries(PREF_TEXT)) if (map[prefs[k]]) out.push(map[prefs[k]]);
  if (prefs.toneCheck) out.push('vyzkoušej si tón a hlasitost v Nastavení, ideálně se sluchátky');
  if (prefs.slowAnswer) out.push('na odpověď je dost času, nespěchej');
  return out.join(' · ');
}

const num = (x) => String(x).replace('.', ',');

/** Rozmezí dnů → čitelný text („5–9 dní“, „3–6 týdnů“, „2–4 měsíce“). */
export function daysText(lo, hi) {
  if (hi < 1.5) return 'pár dní';
  const range = (a, b, few, many) => {
    const x = Math.max(1, Math.round(a)), y = Math.max(x, Math.round(b));
    return `${x === y ? x : `${x}–${y}`} ${y >= 2 && y <= 4 ? few : many}`;
  };
  if (hi < 14) return range(lo, hi, 'dny', 'dní');
  if (hi < 70) return range(lo / 7, hi / 7, 'týdny', 'týdnů');
  return range(lo / 30, hi / 30, 'měsíce', 'měsíců');
}
const charsWord = (n) => (n === 1 ? 'znak' : n >= 2 && n <= 4 ? 'znaky' : 'znaků');

/** Odhad plánu (kalibrace): minuty na znak a doba do celé sady, vždy jako rozmezí. */
function planBlock(p) {
  const box = el('div', 'plan-est');
  if (p.remainingChars === 0) {
    box.append(el('p', 'plan-line', 'Máš celou sadu znaků. Teď jde o to, aby každý znak držel ≥ 90 % a reakce byla rychlá.'));
    return box;
  }
  const [lo, hi] = p.minPerChar;
  box.append(el('p', 'plan-line plan-range', `Celá sada: asi ${daysText(p.days[0], p.days[1])}`));
  box.append(el('p', 'plan-line hint', `při ${p.dayMin} min cvičení denně · zbývá ${p.remainingChars} ${charsWord(p.remainingChars)} · `
    + `${lo}–${hi} min na jeden znak`));
  box.append(el('p', 'plan-line hint', p.source === 'data'
    ? `Odhad z tvých lekcí (${p.added} ${p.added === 1 ? 'přidaný znak' : p.added < 5 ? 'přidané znaky' : 'přidaných znaků'}`
      + `${p.rate != null ? `, průměr ${num(p.rate)} min na znak` : ''}). Pozdější znaky bývají pomalejší, proto rozmezí.`
    : 'Zatím jen odhad podle typu plánu. Po prvních 2–3 lekcích ho trenér zpřesní podle toho, jak rychle se učíš '
      + '(lidé se v rychlosti liší až 6×, všichni ale cíle dosáhnou).'));
  return box;
}

/** Úroveň U1–U6: pruh úrovní, popis současné a co chybí do další (zpětná vazba o úkolu). */
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
    box.append(el('p', 'plan-line', `${isNew ? '🎉 Nová úroveň! ' : ''}U${cur.id} ${cur.name} – ${cur.content}.`));
  }
  const nx = lv.next;
  const target = lv.levels.find((u) => u.id === nx?.target);
  if (nx && target && target.id > lv.ulevel) {
    box.append(el('p', 'plan-line hint', `Do U${target.id} ${target.name}:`));
    const ul = el('ul', 'hint');
    for (const t of nx.items) ul.append(el('li', null, t));
    box.append(ul);
  }
  return box;
}

/** Plato: vysvětlení, procesní ukazatel, který se zlepšuje, a rada (≥ 5 sezení = návrh změny). */
function plateauBlock(p) {
  const box = el('div', 'plateau');
  box.append(el('p', 'plan-line', p.text));
  if (p.process) box.append(el('p', 'plan-line hint', `Co se zlepšuje: ${p.process}`));
  box.append(el('p', 'plan-line hint', p.advice));
  return box;
}

/**
 * Vykreslí kartu plánu. info = odpověď GET /api/coach (nebo null), onQuiz = otevřít dotazník.
 */
export function renderPlan(root, info, { onQuiz } = {}) {
  root.textContent = '';
  if (info?.levelInfo) root.append(levelBlock(info.levelInfo, info.ulevelNew));
  if (info?.plan) root.append(planBlock(info.plan));
  if (info?.plateau) root.append(plateauBlock(info.plateau));
  if (info?.speed) {
    // M6: tempo a co je potřeba k dalšímu kroku (o úkolu, ne o osobě)
    const sp = info.speed;
    root.append(el('p', 'plan-line', `Tempo: ${sp.tempo}${sp.auto ? ' · řídí trenér' : ' · ručně'}`));
    root.append(el('p', 'plan-line hint', sp.next + (sp.fluencyS ? ` Na konci lekce ${sp.fluencyS} s blok plynulosti.` : '')));
  }
  if (info?.copy?.available) {
    // M7: žebřík příjmu ve skluzu
    const cp = info.copy;
    root.append(el('p', 'plan-line', `Příjem ve skluzu: krok ${cp.step} z ${cp.of} – ${cp.name}, ${cp.gap}`));
    root.append(el('p', 'plan-line hint', `${cp.next} Lekce po znacích dál slouží k udržování a rozcvičce.`));
  }
  if (!info || !info.archetype) {
    root.append(el('p', 'hint', 'Krátký dotazník (asi 12 otázek, 2 minuty) nastaví délku lekcí a tempo podle tebe. '
      + 'Po prvních lekcích trenér plán zpřesní podle toho, jak rychle se učíš.'));
    const b = el('button', null, '📝 Vyplnit dotazník');
    b.type = 'button';
    b.addEventListener('click', () => onQuiz?.());
    root.append(b);
    return;
  }
  root.append(el('p', 'plan-line', `Typ plánu: ${info.archetypeName || info.archetype}`));
  if (info.modifierNames?.length) root.append(el('p', 'plan-line hint', `Přizpůsobení: ${info.modifierNames.join(' · ')}`));
  const ps = prefsSummary(info.prefs);
  if (ps) root.append(el('p', 'plan-line hint', ps));
  if (info.prefs?.entryTest) {
    root.append(el('p', 'plan-line hint', 'Navrátilec: vstupní test všech znaků přijde v další verzi. '
      + 'Zatím můžeš počet znaků nastavit ručně v Nastavení.'));
  }
  const b = el('button', null, 'Upravit odpovědi');
  b.type = 'button';
  b.addEventListener('click', () => onQuiz?.());
  root.append(b);
}
