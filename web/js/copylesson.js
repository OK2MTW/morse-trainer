// SPDX-License-Identifier: EUPL-1.2
// Lekce ve skluzu (M7 U3, M8 U4): proud položek po řádcích, zápis bez čekání, značky slov se zpožděním
// 1 slova (od kroku 9 o 2 slova – skluz celého slova), oprava na konci řádku, únava po řádcích, výsledek lekce.
// Rychlost: krok s wpm (U4) hraje znak i mezery touto rychlostí, jinak nastavení z M6.
// Logika hodnocení je v copy.js (testovaná v Pythonu).
import { evaluate, lessonSummary, CopyFatigue, ROUND_ITEMS, ROUND_TAIL_MS } from './copy.js';
import { makeItems } from './content.js';
import { normalizeKey } from './charset.js';
import { DAY_WARN_MIN, SESSION_END_MIN } from './coach.js';

const $ = (s) => document.querySelector(s);
const fmtTime = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const pct = (x) => `${Math.round(x * 100)} %`;
const num = (x) => String(x).replace('.', ',');
const TAIL_MAX_MS = 3 * ROUND_TAIL_MS; // psaní po konci proudu prodlužuje řádek, nejvýš sem
const MARK_AFTER_MS = 600;            // značka slova k nejdřív 600 ms po doznění slova k+1

/**
 * deps: {player, kbd, show, settings, progress, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind,
 *        currentLoad, fallbackChars()}
 */
export function initCopy(deps) {
  const { player, kbd, settings } = deps;
  const C = { running: false };
  let R = null; // aktuální řádek

  function plan() {
    const cp = deps.coachInfo.data?.copy;
    const chars = cp?.chars?.length ? cp.chars : deps.fallbackChars();
    return {
      step: cp?.step || 1, content: cp?.content || 'groups', gapX: cp?.gapX || 3, name: cp?.name || 'skupiny', chars,
      wpm: cp?.wpm || null, markLag: cp?.markLag || 1,
    };
  }

  async function start() {
    if (!(await deps.ensureAudio())) { alert('Zvuk se nepodařilo zapnout.'); return; }
    await deps.keepAwake(true);
    Object.assign(C, {
      running: true, paused: false, plan: plan(), rounds: [], activeMs: 0, pauses: [], pauseAt: 0,
      lessonMs: settings.lessonMin * 60000, tick: null, fat: new CopyFatigue(), fatEvents: [],
    });
    // M8: krok s rychlostí (U4) – znak i mezery rychlostí kroku; nastavení pro lekce po znacích se nemění
    C.wpm = C.plan.wpm || settings.wpm;
    C.fwpm = C.plan.wpm || settings.fwpm;
    player.settings = { ...settings, wpm: C.wpm, fwpm: C.fwpm };
    kbd.setMode('skluz');
    kbd.setActive(deps.fallbackChars()); // psát jde každý známý znak (i záměnu), obsah je jen ze zvládnutých
    $('#cp-phase').textContent = `Krok ${C.plan.step}: ${C.plan.name} · ${C.wpm}/${C.fwpm} WPM`
      + (C.plan.gapX > 1 ? ` · mezera mezi slovy ${num(C.plan.gapX)}×` : '')
      + (C.plan.markLag > 1 ? ' · klidně piš o celé slovo později' : '');
    $('#cp-acc').textContent = '–';
    $('#cp-pause-overlay').hidden = true;
    $('#cp-fatigue-overlay').hidden = true;
    deps.show('copy');
    C.tick = setInterval(updateBar, 250);
    await new Promise((r) => setTimeout(r, 800));
    if (C.running && !C.paused) startRound();
  }

  function updateBar() {
    const t = C.activeMs + (R && R.t0 && !R.done ? performance.now() - R.t0 : 0);
    $('#cp-time').textContent = fmtTime(t);
    $('#cp-progress').style.width = `${Math.min(100, (t / C.lessonMs) * 100)}%`;
    if (C.paused) $('#cp-pause-time').textContent = fmtTime(Date.now() - C.pauseAt);
  }

  // ---------- řádek ----------
  function startRound() {
    const items = makeItems(C.plan.content, C.plan.chars, ROUND_ITEMS);
    R = {
      items, typed: [], disp: [], marks: items.map(() => null), timers: [], done: false, review: false,
      startS: C.activeMs / 1000,
    };
    $('#cp-review').hidden = true;
    $('#cp-next').hidden = true;
    $('#cp-typed').hidden = false;
    $('#cp-status').textContent = 'Poslouchej a piš – nečekej na konec.';
    drawTyped();
    drawMarks();
    const st = player.playStream(items, { gapX: C.plan.gapX });
    Object.assign(R, { chars: st.chars, wordEnds: st.wordEnds, toneEnd: st.toneEnd, t0: st.start });
    const now = performance.now();
    const lag = C.plan.markLag;
    st.wordEnds.forEach((end, k) => {
      if (k < lag) return;
      R.timers.push(setTimeout(() => markWord(k - lag), Math.max(0, end - now) + MARK_AFTER_MS));
    });
    armTail();
  }

  function armTail() {
    clearTimeout(R.tail);
    const now = performance.now();
    const due = Math.max(R.toneEnd + ROUND_TAIL_MS, Math.min(now + ROUND_TAIL_MS / 2, R.toneEnd + TAIL_MAX_MS));
    R.tail = setTimeout(endRound, Math.max(0, due - now));
  }

  function markWord(k) {
    if (!R || R.done) return;
    // průběžně: zarovnání vyslaného textu do slova k+markLag se vším napsaným – značka jen pro slovo k
    const lag = C.plan.markLag;
    const upto = R.chars.filter((c) => c.w <= k + lag);
    const ev = evaluate(R.items.slice(0, k + lag + 1), upto, R.typed);
    R.marks[k] = ev.words[k];
    drawMarks();
  }

  function drawTyped() {
    const el = $('#cp-typed');
    el.textContent = R.disp.join('');
    const cur = document.createElement('span');
    cur.className = 'cur';
    cur.textContent = '​';
    el.append(cur);
  }

  function drawMarks() {
    const el = $('#cp-marks');
    el.textContent = '';
    R.marks.forEach((m) => {
      const s = document.createElement('span');
      s.textContent = m === null ? '·' : m ? '✓' : '✗';
      if (m !== null) s.className = m ? 'ok' : 'bad';
      el.append(s);
    });
  }

  function onChar(ch, ts) {
    if (!C.running || C.paused || !R || R.done) return;
    R.typed.push({ ch, t: ts });
    R.disp.push(ch);
    drawTyped();
    if (performance.now() > R.toneEnd) armTail();
  }

  function onSpace() {
    if (!R || R.done || C.paused) return;
    if (R.disp.length && R.disp.at(-1) !== ' ') { R.disp.push(' '); drawTyped(); }
  }

  function onBackspace() {
    if (!R || R.done || C.paused) return;
    if (R.disp.length && R.disp.at(-1) !== ' ') { R.disp.pop(); R.typed.pop(); drawTyped(); }
  }

  function endRound() {
    if (!R || R.done) return;
    R.done = true;
    R.timers.forEach(clearTimeout);
    clearTimeout(R.tail);
    C.activeMs += performance.now() - R.t0;
    const ev = evaluate(R.items, R.chars, R.typed);
    C.rounds.push({ items: R.items, ev });
    R.marks = ev.words;
    drawMarks();
    drawReview(ev);
    const sum = lessonSummary(C.rounds);
    $('#cp-acc').textContent = sum.acc === null ? '–' : pct(sum.acc);
    const last = C.activeMs >= C.lessonMs;
    $('#cp-status').textContent = `Řádek: ${ev.sc.acc === null ? '–' : pct(ev.sc.acc)}, slov ${ev.words.filter(Boolean).length} z ${ev.words.length}.`;
    const nb = $('#cp-next');
    nb.textContent = last ? '▶ Výsledek lekce' : '▶ Další řádek';
    nb.hidden = false;
    R.review = true;
    // M8: únava po řádku – návrh pauzy v opravě řádku (proud se nepřerušuje)
    const f = C.fat.add(ev.sc, R.startS, C.activeMs / 1000);
    if (f.propose) proposeFatigue(f);
  }

  function proposeFatigue(f) {
    C.fatEvents.push({ t: Math.round(C.activeMs / 1000), kind: f.kind, accDrop: f.accDrop, missUp: f.missUp, action: null });
    $('#cp-fat-text').textContent = (f.kind === 'acc'
      ? `Úspěšnost v posledních řádcích je o ${Math.round(f.accDrop * 100)} p. b. nižší než na začátku lekce.`
      : `V posledních řádcích chybí o ${Math.round(f.missUp * 100)} p. b. víc znaků než na začátku – proud ujíždí.`)
      + ' To bývá únava – krátká pauza (3–5 min: vstát, protáhnout se, napít) obvykle pomůže víc než další řádky.';
    $('#cp-fatigue-overlay').hidden = false;
  }

  function fatigueChoice(action) {
    const e = C.fatEvents.at(-1);
    if (e) e.action = action;
    $('#cp-fatigue-overlay').hidden = true;
    if (action === 'pause') pause();
    else if (action === 'end') finish();
    else C.fat.snooze(C.activeMs / 1000);
  }

  function drawReview(ev) {
    const box = $('#cp-review');
    box.textContent = '';
    const sent = R.chars.map((c) => c.ch);
    const tch = R.typed.map((x) => x.ch);
    const wordOf = R.chars.map((c) => c.w);
    // bloky po slovech: operace patří slovu vyslaného znaku, navíc slovu před sebou
    const blocks = R.items.map(() => ({ s: [], t: [] }));
    let w = 0;
    for (const o of ev.ops) {
      if (o.s !== null) w = wordOf[o.s];
      const b = blocks[w];
      if (o.op === 'ok') { b.s.push(['ok', sent[o.s]]); b.t.push(['ok', tch[o.t]]); }
      if (o.op === 'sub') { b.s.push(['', sent[o.s]]); b.t.push(['sub', tch[o.t]]); }
      if (o.op === 'del') { b.s.push(['del', sent[o.s]]); b.t.push(['del', '_']); }
      if (o.op === 'ins') { b.s.push(['', ' ']); b.t.push(['ins', tch[o.t]]); }
    }
    blocks.forEach((b, k) => {
      const wb = document.createElement('span');
      wb.className = ev.words[k] ? 'wb' : 'wb bad';
      for (const [row, cls] of [[b.s, 'row'], [b.t, 'row typed']]) {
        const r = document.createElement('span');
        r.className = cls;
        for (const [c, ch] of row) {
          const s = document.createElement('span');
          if (c) s.className = c;
          s.textContent = ch;
          r.append(s);
        }
        wb.append(r);
      }
      box.append(wb);
    });
    const lg = document.createElement('div');
    lg.className = 'legend';
    lg.textContent = 'Nahoře vysláno, dole napsáno. Zeleně správně, červeně podtržená záměna, oranžově „_“ chybí, přeškrtnuté navíc.';
    box.append(lg);
    box.hidden = false;
  }

  function next() {
    if (!R?.review) return;
    if (C.activeMs >= C.lessonMs) { finish(); return; }
    startRound();
  }

  // ---------- pauza ----------
  function pause() {
    if (!C.running || C.paused) return;
    player.stop();
    if (R && !R.done) { // rozehraný řádek se zahodí
      R.done = true;
      R.timers.forEach(clearTimeout);
      clearTimeout(R.tail);
      C.activeMs += Math.max(0, performance.now() - R.t0);
    }
    C.paused = true;
    C.pauseAt = Date.now();
    $('#cp-pause-overlay').hidden = false;
  }

  function resume() {
    if (!C.paused) return;
    C.pauses.push([Math.round(C.activeMs / 1000), Math.round((Date.now() - C.pauseAt) / 1000)]);
    C.paused = false;
    C.fat.reset(); // po pauze nové okno (základ zůstává)
    $('#cp-pause-overlay').hidden = true;
    if (R?.review) return; // pauza během opravy řádku – pokračuje se tlačítkem „Další řádek“
    deps.ensureAudio().then(() => { player.warmUp(); setTimeout(() => { if (C.running && !C.paused) startRound(); }, 1500); });
  }

  // ---------- konec lekce ----------
  function finish() {
    clearInterval(C.tick);
    if (R && !R.done) pause();
    C.running = false;
    C.paused = false;
    $('#cp-pause-overlay').hidden = true;
    $('#cp-fatigue-overlay').hidden = true;
    player.stop();
    player.settings = settings; // zpět sdílené nastavení (rychlost kroku platila jen pro tuto lekci)
    kbd.setMode('znak');
    deps.keepAwake(false);
    if (!C.rounds.length) { deps.show('home'); return; }
    const s = lessonSummary(C.rounds);
    const p = C.plan;
    deps.addLesson({
      at: new Date().toISOString(), device: deps.deviceKind(), mode: 'skluz', level: deps.progress.level,
      durS: Math.round(C.activeMs / 1000), trials: s.n, correct: s.ok, acc: s.acc ?? 0, ttr: null,
      wpm: C.wpm, fwpm: C.fwpm,
      detail: {
        copy: { step: p.step, content: p.content, gapX: p.gapX, ...(p.wpm ? { wpm: p.wpm } : {}), markLag: p.markLag, ...s },
        ...(C.pauses.length ? { pauses: C.pauses } : {}),
        ...(C.fat.base || C.fatEvents.length ? { fatigue: { base: C.fat.base, events: C.fatEvents } } : {}),
      },
    });
    showResult(s);
  }

  function showResult(s) {
    $('#cr-acc').textContent = s.acc === null ? '–' : pct(s.acc);
    $('#cr-words').textContent = `${s.words.ok} z ${s.words.n}`;
    $('#cr-lag').textContent = s.lagCh === null ? '–' : `${num(s.lagCh)} zn.`
      + (C.plan.markLag > 1 && s.lagW !== null ? ` / ${num(s.lagW)} sl.` : '');
    const cp = deps.coachInfo.data?.copy;
    let v;
    if (s.acc >= 0.9) v = `Výborně, ${pct(s.acc)} po zarovnání. ${cp?.next || ''}`;
    else if (s.acc >= 0.75) v = `${pct(s.acc)} po zarovnání – dobré pásmo pro učení. Další krok přijde od 90 % ve 2 sezeních.`;
    else v = `${pct(s.acc)} po zarovnání. Skluz je nová dovednost – nevadí, když napíšeš slovo až po jeho doznění. Při dvou sezeních pod 75 % trenér krok ulehčí.`;
    $('#cr-verdict').textContent = v;
    const d = [];
    if (s.lagMs !== null) d.push(`Skluz: medián ${num(s.lagCh)} zn. (${s.lagMs} ms za koncem znaku), 90 % znaků do ${s.lagChP90} zn., nejvíc ${s.lagChMax} zn.`
      + (s.lagW !== null ? ` Ve slovech: medián ${num(s.lagW)}, 90 % do ${s.lagWP90}.` : ''));
    if (C.fatEvents.length) d.push('Během lekce trenér navrhl pauzu kvůli možné únavě.');
    if (s.drift !== null && s.drift > 1) d.push(`Ke konci lekce skluz narostl o ${num(s.drift)} zn. – zkus psát průběžně, ať proud neujíždí.`);
    d.push(`Správně ${s.ok}, záměny ${s.sub}, chybí ${s.del}, navíc ${s.ins} (z ${s.n} vyslaných znaků, ${s.rounds} řádků).`);
    if (s.confusions.length) d.push(`Záměny: ${s.confusions.slice(0, 5).map((c) => `${c.pair} ${c.n}×`).join(', ')}.`);
    $('#cr-detail').textContent = d.join(' ');
    const ld = deps.currentLoad();
    const rl = $('#cr-load');
    rl.hidden = false;
    rl.className = ld.suggestEnd || ld.dayWarn ? 'hint warn' : 'hint';
    rl.textContent = ld.dayWarn
      ? `Dnes už ${Math.round(ld.dayMin)} min. Víc než ${DAY_WARN_MIN} min denně už moc nepřidá – pokračuj raději zítra.`
      : ld.suggestEnd
        ? `Sezení trvá ${Math.round(ld.sessionMin)} min – po ${SESSION_END_MIN} min klesá soustředění. Navrhuji skončit.`
        : `Sezení ${Math.round(ld.sessionMin)} min. Před dalším blokem si dej aspoň 30 s pauzu.`;
    deps.show('copyresult');
  }

  /** Klávesy v pohledu 'copy' (PC). Vrací true, když je obsloužil. */
  function onKey(e) {
    if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return false;
    if (!$('#cp-fatigue-overlay').hidden) { // návrh pauzy: Esc = pauza, jinak jen tlačítka
      if (e.key === 'Escape') { fatigueChoice('pause'); return true; }
      return false;
    }
    if (e.key === 'Escape') { if (C.paused) resume(); else pause(); return true; }
    if (C.paused) return false;
    if (R?.review) {
      if (e.key === 'Enter' || e.key === ' ') { next(); return true; }
      return false;
    }
    if (e.key === 'Enter') { if (R && performance.now() > R.toneEnd) endRound(); return true; }
    if (e.key === ' ') { onSpace(); return true; }
    if (e.key === 'Backspace') { onBackspace(); return true; }
    const ch = normalizeKey(e.key);
    if (ch) { kbd.flash(ch); onChar(ch, e.timeStamp); return true; }
    return false;
  }

  $('#cp-next').addEventListener('click', next);
  $('#cp-pause').addEventListener('click', () => (C.paused ? resume() : pause()));
  $('#cp-resume').addEventListener('click', resume);
  $('#cp-finish').addEventListener('click', finish);
  $('#cp-fat-pause').addEventListener('click', () => fatigueChoice('pause'));
  $('#cp-fat-end').addEventListener('click', () => fatigueChoice('end'));
  $('#cp-fat-continue').addEventListener('click', () => fatigueChoice('continue'));

  return {
    start, onKey, onChar, onSpace,
    pause: () => (!$('#cp-fatigue-overlay').hidden ? fatigueChoice('pause') : C.paused ? resume() : pause()),
    hold: pause,
    get running() { return C.running; },
  };
}
