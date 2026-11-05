// SPDX-License-Identifier: EUPL-1.2
// Lekce Kochovou metodou (M1) + účty a synchronizace (M2) + statistika a rozlišování (M3) + trenér: plán, zátěž, úrovně (M4)
// + únava v lekci, rozcvička po pauze, dashboard pokroku (M5).
import { isPublic, otherSite } from './site.js';
import { MorsePlayer } from './audio.js';
import { TouchKeyboard } from './keyboard.js';
import { normalizeKey, KOCH_ORDER } from './charset.js';
import {
  Drill, charsForLevel, median, trendArrow, pickContrasts, discrimSequence,
  ADVANCE_WINDOW, ADVANCE_ACCURACY, NEW_MIN_N, NEW_ACCURACY,
} from './drill.js';
import {
  settings, progress, sync, stats, coachInfo, setCoachInfo, saveSettings, saveProgress, addLesson, onDataChange,
} from './storage.js';
import { renderQuiz } from './quiz.js';
import { renderPlan } from './plan.js';
import { renderDashboard } from './dashboard.js';
import { renderStats, confusionsWith } from './stats.js';
import {
  confirmGate, sessionLoad, warmupStats, fatigueSignal, WARMUP_S, SESSION_END_MIN, DAY_WARN_MIN, FATIGUE_TTR,
  FatigueMonitor, fatigueRef, REWARM_PAUSE_MIN, REWARM_S, SESSION_BREAK_MIN,
} from './coach.js';
import { startAuth, renderAccount, backgroundSync, session } from './account.js';
import { deviceKind } from './api.js';
import { initCopy } from './copylesson.js';
import * as WPM from '../vendor/morse-pro/morse-pro-wpm.js';

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ANSWER_TIMEOUT = 6000; // ms po konci znaku → „nevím“
// 0.5.1: opravné přehrání nejdřív FIX_AFTER_PRESS po odpovědi A ZÁROVEŇ FIX_AFTER_TONE po doznění
// původního znaku (odpověď lze zadat ještě během znaku – dřív se oprava „srazila“ s originálem).
const FIX_AFTER_PRESS = 600;
const FIX_AFTER_TONE = 700;
const untilTone = (toneEnd) => Math.max(0, toneEnd - performance.now());
const fixDelay = (toneEnd) => Math.max(FIX_AFTER_PRESS, untilTone(toneEnd) + FIX_AFTER_TONE);
// Odstup prvního znaku po pauze v lekci (s ≥ 5 s pauzy se navíc zahřívá zvuk)
const RESUME_SHORT_MS = 600;   // pauza < 5 s
const RESUME_MS = 1500;        // pauza < REWARM_PAUSE_MIN
const RESUME_LONG_MS = 2500;   // dlouhá pauza – Android mezitím uspí zvukový výstup

const player = new MorsePlayer();
player.settings = settings; // sdílený objekt (wpm, fwpm, freq, volume)

// ================= navigace =================
let view = 'home';
const PUBLIC_VIEWS = ['login', 'register', 'reset'];
const TRAINING_VIEWS = ['home', 'intro', 'discrim', 'lesson', 'result', 'stats', 'quiz', 'copy', 'copyresult'];
// 0.8.6: menu uživatele (ikona vpravo nahoře)
function closeUserMenu() {
  $('#user-menu').hidden = true;
  $('#user-btn').setAttribute('aria-expanded', 'false');
}
$('#user-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  const open = $('#user-menu').hidden;
  $('#user-menu').hidden = !open;
  $('#user-btn').setAttribute('aria-expanded', String(open));
});
document.addEventListener('click', (e) => { if (!e.target.closest('#user-menu')) closeUserMenu(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeUserMenu(); });
$('#menu-logout').addEventListener('click', () => { closeUserMenu(); $('#acc-logout').click(); });

function show(name) {
  if (!session.user && !PUBLIC_VIEWS.includes(name)) name = 'login';
  if (session.user?.pw_change) name = 'pwchange'; // E3: nejdřív nové heslo
  const admin = session.user?.role === 'admin'; // správce jen spravuje, netrénuje
  if (admin && TRAINING_VIEWS.includes(name)) name = 'account';
  $('.tabs [data-go="home"]').hidden = admin;
  for (const el of document.querySelectorAll('.training-only')) el.hidden = admin;
  view = name;
  for (const v of document.querySelectorAll('.view')) v.hidden = v.id !== `view-${name}`;
  const training = name === 'lesson' || name === 'intro' || name === 'discrim' || name === 'copy';
  $('#keyboard').hidden = name !== 'lesson' && name !== 'discrim' && name !== 'copy';
  player.keepAlive(training && document.visibilityState === 'visible'); // 0.8.5: BT výstup nesmí usnout
  $('.tabs').hidden = training || !session.user || name === 'pwchange';
  $('#user-btn').hidden = name === 'pwchange';
  for (const b of document.querySelectorAll('.tabs button')) b.classList.toggle('active', b.dataset.go === name);
  $('#user-btn').classList.toggle('active', name === 'settings' || name === 'account');
  closeUserMenu();
  if (name === 'home') renderHome();
  if (name === 'settings') { renderSteppers(); refreshDiag(); }
  if (name === 'account') renderAccount();
  if (name === 'stats') { drawStats(); backgroundSync(); }
  if (name === 'quiz') openQuiz();
  window.scrollTo(0, 0);
}
document.addEventListener('click', (e) => {
  const go = e.target.closest('[data-go]');
  if (go) show(go.dataset.go);
});

async function ensureAudio() {
  if (player.ready) return true;
  try { return await player.unlock(); } catch (e) { return false; }
}

let wakeLock = null;
async function keepAwake(on) {
  try {
    if (on && !wakeLock) wakeLock = await navigator.wakeLock?.request('screen');
    if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
  } catch (e) { wakeLock = null; }
}

// ================= klávesnice a vstup =================
let inputHandler = null; // (ch, ts) => void – kdo právě čeká na odpověď
const kbd = new TouchKeyboard($('#keyboard'), (ch, ts) => (view === 'copy' ? copyCtl.onChar(ch, ts) : inputHandler?.(ch, ts)), {
  onRepeat: () => repeatHandler?.(),
  onPause: () => (view === 'copy' ? copyCtl.pause() : pauseHandler?.()),
  onSpace: (ts) => copyCtl.onSpace(ts),
});
let repeatHandler = null;
let pauseHandler = null;

document.addEventListener('keydown', (e) => {
  if (view === 'copy') { if (copyCtl.onKey(e)) e.preventDefault(); return; }
  if (view !== 'lesson' && view !== 'intro' && view !== 'discrim') return;
  if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
  if (e.key === ' ') { e.preventDefault(); repeatHandler?.(); return; }
  if (view === 'intro') { if (e.key === 'Enter') { e.preventDefault(); intro.next?.(); } return; }
  if (e.key === 'Escape') { e.preventDefault(); pauseHandler?.(); return; }
  const ch = normalizeKey(e.key);
  if (ch) { e.preventDefault(); kbd.flash(ch); inputHandler?.(ch, e.timeStamp); }
});

// ================= DOMŮ =================
function localMidnight() { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); }
function currentLoad() { return sessionLoad(progress.history, Date.now(), localMidnight()); }
const fmtMin = (m) => String(Math.round(m)).replace('.', ',');

function newestChar() { return charsForLevel(progress.level).at(-1); }

function renderHome() {
  const chars = charsForLevel(progress.level);
  $('#level-count').textContent = `(${chars.length} z ${KOCH_ORDER.length})`;
  const box = $('#level-chars');
  box.textContent = '';
  for (const c of chars) {
    const s = document.createElement('span');
    s.textContent = c;
    if (c === newestChar()) s.className = 'newest';
    box.append(s);
  }
  const next = KOCH_ORDER[chars.length];
  $('#level-next').textContent = next
    ? `Další znak: „${next}“ – přidá se, až budeš mít ${Math.round(ADVANCE_ACCURACY * 100)} % v posledních ${ADVANCE_WINDOW} znacích lekce a nejnovější znak poznáš spolehlivě a rychle. Od 5. znaku se postup potvrzuje v dalším sezení (aspoň 3 h).`
    : 'Máš všechny znaky sady!';
  $('#lesson-info').textContent = `${settings.lessonMin} min · znak ${settings.wpm} WPM · mezery ${settings.fwpm} WPM · tón ${settings.freq} Hz`;
  // M6: změna tempa trenérem (zůstane vidět do další lekce)
  const sn = coachInfo.data?.speedNotice;
  const sp = coachInfo.data?.speed;
  const snEl = $('#speed-note');
  snEl.hidden = !sn && !(sp?.change && !sp.change.applied);
  if (sn) snEl.textContent = `${sn.text} ${sn.why}`;
  else if (sp?.change && !sp.change.applied) snEl.textContent = `Trenér navrhuje tempo ${sp.change.to.wpm}/${sp.change.to.fwpm} WPM. ${sp.change.why} (Změníš v Nastavení.)`;
  const ld = currentLoad();
  const li = $('#load-info');
  li.hidden = ld.dayMin === 0;
  li.className = ld.suggestEnd || ld.dayWarn ? 'hint center warn' : 'hint center';
  li.textContent = ld.dayWarn
    ? `Dnes už ${fmtMin(ld.dayMin)} min. Nad ${DAY_WARN_MIN} min denně se už moc nepřidá – lepší je pokračovat zítra.`
    : ld.suggestEnd
      ? `Toto sezení trvá ${fmtMin(ld.sessionMin)} min. Doporučuji skončit a pokračovat po delší pauze.`
      : `Dnes ${fmtMin(ld.dayMin)} min${ld.newSession ? '' : ` · toto sezení ${fmtMin(ld.sessionMin)} min`}.`;
  if (!ld.newSession && lastFatigueAt && Date.now() - lastFatigueAt < SESSION_BREAK_MIN * 60000) {
    li.hidden = false;
    li.className = 'hint center warn';
    li.textContent += ` Minulá lekce ukázala únavu – dej si pauzu aspoň ${SESSION_BREAK_MIN} min, další sezení pak začne rozcvičkou.`;
  }

  renderPlan($('#plan-root'), coachInfo.data, { onQuiz: () => show('quiz') });
  renderCopyCard();

  const tb = $('#history');
  tb.textContent = '';
  const last = progress.history.slice(-10).reverse();
  $('#history-empty').hidden = last.length > 0;
  for (const h of last) {
    const tr = document.createElement('tr');
    const d = new Date(h.at).toLocaleString('cs-CZ', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
    for (const txt of [d, h.mode === 'skluz' ? 'skluz' : `${h.level} zn.`, `${Math.round(h.acc * 100)} %`, h.ttr ? `${h.ttr} ms` : '–']) {
      const td = document.createElement('td'); td.textContent = txt; tr.append(td);
    }
    tb.append(tr);
  }
}

// ================= PŘÍJEM VE SKLUZU (M7) =================
const copyCtl = initCopy({
  player, kbd, show, settings, progress, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind, currentLoad,
  fallbackChars: () => charsForLevel(progress.level),
});
$('#btn-copy').addEventListener('click', () => copyCtl.start());
$('#btn-copy-again').addEventListener('click', () => copyCtl.start());

function renderCopyCard() {
  const cp = coachInfo.data?.copy;
  $('#copy-card').hidden = !cp?.available;
  if (!cp?.available) return;
  $('#copy-step').textContent = `(U${cp.ulevel || 3} · krok ${cp.step} z ${cp.of})`;
  $('#copy-desc').textContent = `Znaky běží proudem bez čekání – piš průběžně, klidně o znak či celé slovo později. `
    + `Teď: ${cp.name}, ${cp.gap}, ${cp.wpm ? `${cp.wpm}/${cp.wpm}` : `${settings.wpm}/${settings.fwpm}`} WPM. `
    + 'Hodnotí se zarovnáním celého řádku, oprava přijde na jeho konci.'
    + (cp.markLag > 1 ? ' Cíl kroku: skluz celého slova – piš slovo, zatímco zní další; značka ✓/✗ přijde o 2 slova později.' : '')
    + (deviceKind() === 'mobil' ? ' Na mobilu doporučuji psát vždy celé slovo až po jeho doznění.' : '');
  $('#copy-note').textContent = [cp.change?.text, cp.change?.why, cp.next].filter(Boolean).join(' ');
}

// ================= DOTAZNÍK (M4) =================
function openQuiz() {
  renderQuiz($('#quiz-root'), {
    onDone: (info) => {
      // navržené nastavení se použije hned (dá se změnit v Nastavení); meze jako u stepperů
      const s = info.prefs?.settings || {};
      if (Number.isFinite(s.lessonMin)) settings.lessonMin = Math.min(10, Math.max(1, s.lessonMin));
      if (Number.isFinite(s.wpm)) settings.wpm = Math.min(40, Math.max(12, s.wpm));
      if (Number.isFinite(s.fwpm)) settings.fwpm = Math.min(settings.wpm, Math.max(3, s.fwpm));
      saveSettings();
      setCoachInfo(info);
      show('home');
    },
    onCancel: () => show('home'),
  });
}

$('#btn-start').addEventListener('click', startTraining);
$('#btn-again').addEventListener('click', startTraining);

async function startTraining() {
  if (!(await ensureAudio())) { alert('Zvuk se nepodařilo zapnout.'); return; }
  const chars = charsForLevel(progress.level);
  kbd.setMode('znak');
  kbd.setActive(chars);
  await keepAwake(true);
  if (coachInfo.data?.speedNotice) setCoachInfo({ ...coachInfo.data, speedNotice: null }); // viděl(a) na Domů
  const fresh = chars.filter((c) => !progress.introduced.includes(c));
  // rozcvička: první lekce nového sezení začíná 1–2 min jen známými znaky (měření zapamatování, R1)
  const ld = currentLoad();
  L.warm = ld.newSession && progress.history.length ? { gapH: ld.gapH, n: null, fresh } : null;
  if (ld.newSession) sessionFat.base = null; // základ únavy patří k sezení
  L.fresh = fresh;
  if (fresh.length) {
    await runIntro(fresh);
    if (!intro.skip) await runDiscrim(fresh, chars);
  }
  kbd.setActive(chars);
  startLesson(chars);
}

// ================= SEZNÁMENÍ =================
// Jen poslech: znak se ukáže a 3× zazní. Bez klávesnice – odpovídá se až v lekci.
const intro = { skip: false, current: null, next: null };

function waitContinue() {
  return new Promise((resolve) => { intro.next = () => { intro.next = null; resolve(); }; });
}

async function runIntro(list) {
  intro.skip = false;
  show('intro');
  repeatHandler = () => { if (intro.current) player.play(intro.current); };
  pauseHandler = null;
  inputHandler = null;
  for (let i = 0; i < list.length && !intro.skip; i++) {
    const c = list[i];
    intro.current = c;
    $('#intro-label').textContent = list.length > 1 ? `Nový znak ${i + 1}/${list.length}` : 'Nový znak';
    $('#intro-char').textContent = c;
    $('#intro-status').textContent = 'Poslouchej, jak zní…';
    $('#intro-next').hidden = true;
    await sleep(i === 0 ? 1000 : 300); // před prvním znakem delší pauza – zvuk se po spuštění ustálí
    for (let k = 0; k < 3 && !intro.skip; k++) { await player.play(c).done; await sleep(450); }
    if (!progress.introduced.includes(c)) progress.introduced.push(c);
    saveProgress();
    if (intro.skip) break;
    $('#intro-status').textContent = 'Zapamatuj si zvuk. Přehrát můžeš znovu.';
    $('#intro-next').textContent = i + 1 < list.length ? '▶ Další znak' : '▶ Začít lekci';
    $('#intro-next').hidden = false;
    await waitContinue();
  }
  if (intro.skip) { for (const c of list) if (!progress.introduced.includes(c)) progress.introduced.push(c); saveProgress(); }
  intro.current = null;
  intro.next = null;
}
$('#intro-replay').addEventListener('click', () => repeatHandler?.());
$('#intro-next').addEventListener('click', () => intro.next?.());
$('#intro-skip').addEventListener('click', () => { intro.skip = true; player.stop(); intro.next?.(); });

// ================= ROZLIŠOVÁNÍ =================
// Po seznámení: krátké rozlišování nového znaku proti 1–2 zvukově podobným / zaměňovaným znakům.
// Okamžitá zpětná vazba, výsledky se neukládají (jen rozcvička před lekcí).
const DS = { skip: false, current: null, toneEnd: 0, timer: null, resolve: null, arm: null };

function discrimPlan(fresh, chars) {
  const targets = fresh.slice(-2);
  const pool = chars.filter((c) => !targets.includes(c));
  const conf = {};
  for (const t of targets) for (const [c, n] of Object.entries(confusionsWith(stats.chars, t))) conf[c] = (conf[c] || 0) + n;
  const contrasts = pool.length ? pickContrasts(targets.at(-1), pool, conf, targets.length === 1 ? 2 : 1, chars.length) : [];
  return { targets, contrasts };
}

async function runDiscrim(fresh, chars) {
  const { targets, contrasts } = discrimPlan(fresh, chars);
  const active = [...targets, ...contrasts];
  if (active.length < 2) return;
  const seq = discrimSequence(targets, contrasts);
  DS.skip = false;
  show('discrim');
  kbd.setActive(active);
  $('#ds-label').textContent = `Rozliš: ${active.join('  ')}`;
  $('#ds-char').textContent = '';
  $('#ds-status').textContent = 'Poznáš nový znak mezi podobnými?';
  repeatHandler = () => { if (DS.resolve) { DS.toneEnd = player.play(DS.current).toneEnd; DS.arm(); } };
  pauseHandler = () => { DS.skip = true; player.stop(); DS.resolve?.(null); };
  await sleep(1200);
  let ok = 0;
  for (let i = 0; i < seq.length && !DS.skip; i++) {
    const c = seq[i];
    DS.current = c;
    $('#ds-char').textContent = '';
    $('#ds-char').className = 'big-char';
    $('#ds-status').textContent = `${i + 1} / ${seq.length}`;
    const ans = await new Promise((resolve) => {
      DS.resolve = resolve;
      DS.arm = () => {
        clearTimeout(DS.timer);
        DS.timer = setTimeout(() => resolve(null), Math.max(0, DS.toneEnd - performance.now()) + ANSWER_TIMEOUT);
      };
      inputHandler = (ch) => { if (active.includes(ch)) resolve(ch); };
      DS.toneEnd = player.play(c).toneEnd;
      DS.arm();
    });
    clearTimeout(DS.timer);
    DS.resolve = null;
    inputHandler = null;
    if (DS.skip) break;
    $('#ds-char').textContent = c;
    if (ans === c) {
      ok++;
      $('#ds-char').className = 'big-char ok';
      $('#ds-status').textContent = 'Správně';
      await sleep(Math.max(700, untilTone(DS.toneEnd) + charGap()));
    } else {
      $('#ds-char').className = ans ? 'big-char bad' : 'big-char miss';
      $('#ds-status').textContent = ans ? `Bylo to „${c}“ (ty: „${ans}“)` : `Bylo to „${c}“`;
      kbd.flash(c, 'hint', 1500);
      await sleep(fixDelay(DS.toneEnd)); // až dozní původní znak
      if (!DS.skip) await player.play(c).done;
      await sleep(afterFixGap());
    }
  }
  if (!DS.skip) {
    $('#ds-char').textContent = '';
    $('#ds-status').textContent = `Rozlišování: ${ok} z ${seq.length}. Teď lekce.`;
    await sleep(1500);
  }
  player.stop();
  DS.current = null;
  inputHandler = repeatHandler = pauseHandler = null;
}
$('#ds-replay').addEventListener('click', () => repeatHandler?.());
$('#ds-skip').addEventListener('click', () => pauseHandler?.());

// ================= LEKCE =================
const L = {
  drill: null, prior: {}, running: false, paused: false, answered: true, current: null,
  toneEnd: 0, repeats: 0, activeMs: 0, lastTick: 0, tick: null, pending: null, timeout: null,
  warm: null, // rozcvička {gapH, n (počet pokusů rozcvičky, null = ještě běží), fresh}
  fresh: [], fat: null, fatEvents: [], fatPending: null, pauses: [], pauseAt: 0, rewarmUntil: 0,
  flu: null, // M6: blok plynulosti {main (drill lekce), drill, tempo}
};
// ---- M6: tempo lekce ----
// Lekce hraje nastavené tempo; při potížích (Drill.gapEase) delší mezery, v bloku plynulosti rychleji.
function setTempo() {
  const t = L.flu ? L.flu.tempo : { wpm: settings.wpm, fwpm: L.drill.lessonFwpm(settings.fwpm) };
  player.settings = { ...settings, ...t };
}
// Blok plynulosti (od U2, R1 kap. 6): konec lekce, zvládnuté znaky o stupeň rychleji, nezapočítává se.
function fluencyTempo() {
  const { wpm, fwpm } = settings;
  if (fwpm < wpm) return { wpm, fwpm: Math.min(wpm, fwpm + 3) };
  const w = Math.min(40, wpm + 2);
  return { wpm: w, fwpm: w };
}
function fluencyDue() {
  const ms = (coachInfo.data?.speed?.fluencyS || 0) * 1000;
  return ms > 0 && !L.flu && lessonMs() >= 3 * ms && L.activeMs >= lessonMs() - ms && !inWarmup();
}
function startFluency() {
  const main = L.drill;
  let chars = main.chars.filter((c) => main.isMastered(c));
  if (chars.length < 4) chars = main.chars.filter((c) => c !== main.newChar);
  const tempo = fluencyTempo();
  L.flu = { main, drill: new Drill(chars, null, { prior: L.prior }), tempo };
  L.drill = L.flu.drill;
  $('#ls-phase').textContent = `Blok plynulosti: známé znaky rychleji (${tempo.wpm}/${tempo.fwpm} WPM). Do výsledku se nepočítá.`;
  $('#ls-phase').hidden = false;
}
// M5: základ pro únavu (začátek sezení) přežije mezi lekcemi téhož sezení; čas poslední únavy pro domovskou obrazovku
const sessionFat = { base: null, key: null }; // 0.8.4: základ platí jen pro stejnou sadu znaků
let lastFatigueAt = 0;
const activeS = () => Math.round(L.activeMs / 1000);
const inWarmup = () => (L.warm && L.warm.n === null) || L.activeMs < L.rewarmUntil;

function endRewarm() {
  if (!L.rewarmUntil || L.activeMs < L.rewarmUntil) return;
  L.rewarmUntil = 0;
  if (!(L.warm && L.warm.n === null)) { L.drill.setExclude([]); $('#ls-phase').hidden = true; }
}

function trackFatigue() {
  const t = L.drill.trials.at(-1);
  const r = L.fat.add({ ch: t.ch, ok: t.ok, ttr: t.ttr }, activeS(), !inWarmup() && !L.flu);
  if (r.propose && !L.fatPending) L.fatPending = r;
}

function proposeFatigue() {
  const r = L.fatPending;
  L.fatPending = null;
  L.fatEvents.push({ t: activeS(), kind: r.kind, ttrUp: r.ttrUp, accDrop: r.accDrop, action: null });
  pause(false);
  const why = r.kind === 'ttr'
    ? `Reakce je už přes minutu o ${Math.round((r.ttrUp - 1) * 100)} % pomalejší než na začátku sezení.`
    : `Úspěšnost je už přes minutu o ${Math.round(r.accDrop * 100)} p. b. nižší než na začátku sezení.`;
  $('#fat-text').textContent = `${why} To bývá únava – krátká pauza (3–5 min: vstát, protáhnout se, napít) obvykle pomůže víc než další drill.`;
  $('#fatigue-overlay').hidden = false;
}
function fatigueChoice(action) {
  const e = L.fatEvents.at(-1);
  if (e) e.action = action;
  $('#fatigue-overlay').hidden = true;
  if (action === 'pause') { $('#pause-overlay').hidden = false; updatePause(); }
  else if (action === 'end') finishLesson();
  else { L.fat.snooze(activeS()); resume(); }
}
$('#fat-pause').addEventListener('click', () => fatigueChoice('pause'));
$('#fat-end').addEventListener('click', () => fatigueChoice('end'));
$('#fat-continue').addEventListener('click', () => fatigueChoice('continue'));

function updatePause() {
  if (!L.paused || $('#pause-overlay').hidden) return;
  const s = Math.floor((Date.now() - L.pauseAt) / 1000);
  const long = s >= REWARM_PAUSE_MIN * 60;
  $('#pause-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  $('#pause-hint').textContent = long
    ? `Po pauze začneš ${REWARM_S} s rozcvičkou známými znaky.`
    : `Čas lekce stojí. Po pauze aspoň ${REWARM_PAUSE_MIN} min začne lekce krátkou rozcvičkou.`;
}

function endWarmup() {
  if (!L.warm || L.warm.n !== null) return;
  L.warm.n = L.drill.trials.length;
  if (L.activeMs < L.rewarmUntil) return; // ještě běží rozcvička po pauze
  L.drill.setExclude([]);
  $('#ls-phase').hidden = true;
}

function schedule(fn, ms) { clearTimeout(L.pending); L.pending = setTimeout(fn, ms); }
function charGap() {
  // Farnsworthova mezera mezi znaky určuje tempo dalšího znaku po odpovědi
  return Math.max(300, Math.round(WPM.charSpace(player.settings.wpm, player.settings.fwpm)));
}
const afterFixGap = () => Math.max(1500, 2 * charGap());
const lessonMs = () => settings.lessonMin * 60000;

function startLesson(chars) {
  L.prior = stats.chars || {}; // dlouhodobá statistika před touto lekcí (váhy výběru, šipky trendu)
  L.drill = new Drill(chars, newestChar(), { prior: L.prior });
  const fatKey = chars.join('');
  const fat = new FatigueMonitor(sessionFat.key === fatKey ? sessionFat.base : null,
    { ref: fatigueRef(L.prior), newChar: newestChar() });
  Object.assign(L, { fat, fatKey, fatEvents: [], fatPending: null, pauses: [], rewarmUntil: 0, flu: null });
  if (L.warm) L.drill.setExclude(L.warm.fresh);
  $('#ls-phase').textContent = 'Rozcvička – nejdřív známé znaky, ať je vidět, co sis zapamatoval(a).';
  $('#ls-phase').hidden = !L.warm;
  Object.assign(L, { running: true, paused: false, answered: true, current: null, activeMs: 0, lastTick: performance.now() });
  show('lesson');
  inputHandler = onAnswer;
  repeatHandler = onRepeat;
  pauseHandler = togglePause;
  $('#ls-char').textContent = '';
  $('#ls-status').textContent = 'Připrav se…';
  updateBar();
  clearInterval(L.tick);
  L.tick = setInterval(() => {
    const now = performance.now();
    if (L.running && !L.paused) L.activeMs += now - L.lastTick;
    L.lastTick = now;
    updateBar();
    updatePause();
  }, 250);
  schedule(nextTrial, 900);
}

function updateBar() {
  const left = Math.max(0, lessonMs() - L.activeMs);
  const s = Math.ceil(left / 1000);
  $('#ls-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  $('#ls-progress').style.width = `${Math.min(100, (L.activeMs / lessonMs()) * 100)}%`;
  const d = L.drill;
  $('#ls-acc').textContent = d && d.trials.length ? `${Math.round(d.accuracy * 100)} % · ${d.trials.length}` : '–';
}

function armTimeout() {
  clearTimeout(L.timeout);
  L.timeout = setTimeout(onTimeout, Math.max(0, L.toneEnd - performance.now()) + ANSWER_TIMEOUT);
}

function nextTrial() {
  if (!L.running || L.paused) return;
  if (L.activeMs >= lessonMs()) return finishLesson();
  if (L.warm && L.warm.n === null && L.activeMs >= WARMUP_S * 1000) endWarmup();
  endRewarm();
  if (L.fatPending) return proposeFatigue();
  if (fluencyDue()) startFluency();
  setTempo();
  L.current = L.drill.next();
  L.answered = false;
  L.repeats = 0;
  $('#ls-char').textContent = '';
  $('#ls-char').className = 'big-char';
  $('#ls-status').textContent = '';
  L.toneEnd = player.play(L.current).toneEnd;
  armTimeout();
}

function onAnswer(ch, ts) {
  if (!L.running || L.paused || L.answered) return;
  L.answered = true;
  clearTimeout(L.timeout);
  const ttr = Math.round(ts - L.toneEnd);
  const ok = L.drill.record(L.current, ch, ttr, { repeats: L.repeats });
  trackFatigue();
  $('#ls-char').textContent = L.current;
  updateBar();
  if (ok) {
    $('#ls-char').className = 'big-char ok';
    $('#ls-status').textContent = `${ttr} ms`;
    schedule(nextTrial, untilTone(L.toneEnd) + charGap()); // odpověď během znaku nesmí znak useknout
  } else {
    $('#ls-char').className = 'big-char bad';
    $('#ls-status').textContent = `Bylo to „${L.current}“ (ty: „${ch}“)`;
    kbd.flash(L.current, 'hint', 1500);
    schedule(playFix, fixDelay(L.toneEnd));
  }
}

function onTimeout() {
  if (!L.running || L.paused || L.answered) return;
  L.answered = true;
  L.drill.record(L.current, null, null, { timeout: true, repeats: L.repeats });
  trackFatigue();
  $('#ls-char').textContent = L.current;
  $('#ls-char').className = 'big-char miss';
  $('#ls-status').textContent = `Bylo to „${L.current}“`;
  kbd.flash(L.current, 'hint', 1500);
  updateBar();
  schedule(playFix, fixDelay(L.toneEnd));
}

// Opravné přehrání správného znaku, pak delší odstup – aby nesplynulo s dalším znakem.
// Vše jde přes schedule(), takže pauza naplánované kroky zruší (dřív Promise .done po pauze
// mohla naplánovat další znak navíc → dva znaky přes sebe).
function playFix() {
  if (!L.running || L.paused) return;
  const { toneEnd } = player.play(L.current);
  schedule(nextTrial, untilTone(toneEnd) + afterFixGap());
}

function onRepeat() {
  if (!L.running || L.paused || L.answered) return;
  L.repeats++;
  L.toneEnd = player.play(L.current).toneEnd;
  armTimeout();
}

function pause(overlay = true) {
  if (!L.running || L.paused) return;
  L.paused = true;
  L.pauseAt = Date.now();
  player.stop();
  clearTimeout(L.timeout);
  clearTimeout(L.pending);
  $('#pause-overlay').hidden = !overlay;
  updatePause();
}

let resuming = false;
async function resume() {
  if (!L.running || !L.paused || resuming) return;
  resuming = true;
  const ps = Math.round((Date.now() - L.pauseAt) / 1000);
  // Zvuk mohl být během pauzy uspán (Android, zhasnutá obrazovka) – probudit ještě v obsluze klepnutí.
  const audioOk = await ensureAudio();
  resuming = false;
  if (!L.running || !L.paused) return;
  if (!audioOk) { alert('Zvuk se nepodařilo zapnout – zkus znovu Pokračovat.'); return; }
  const long = ps >= REWARM_PAUSE_MIN * 60;
  const wait = ps < 5 ? RESUME_SHORT_MS : (long ? RESUME_LONG_MS : RESUME_MS);
  if (ps >= 5) player.warmUp(Math.min(1.5, (wait - 300) / 1000)); // neslyšitelné zahřátí výstupu
  L.paused = false;
  L.lastTick = performance.now();
  $('#pause-overlay').hidden = true;
  $('#fatigue-overlay').hidden = true;
  $('#ls-char').textContent = '';
  $('#ls-char').className = 'big-char';
  $('#ls-status').textContent = ps >= 5 ? 'Připrav se…' : '';
  if (ps >= 5) L.pauses.push([activeS(), ps]);
  if (ps >= 5) L.fat.reset(); // po pauze se únava měří znovu
  if (long) {
    // rozcvička po pauze: krátce jen známé znaky, do únavy ani do „rozcvičky sezení“ se nepočítá
    L.rewarmUntil = L.activeMs + REWARM_S * 1000;
    if (L.fresh.length) L.drill.setExclude(L.fresh);
    $('#ls-phase').textContent = 'Rozcvička po pauze – chvíli jen známé znaky.';
    $('#ls-phase').hidden = false;
  }
  if (!L.answered) {
    // znak přerušený pauzou zahrajeme znovu (nepočítá se jako opakování)
    schedule(() => {
      if (!L.running || L.paused) return;
      $('#ls-status').textContent = '';
      L.toneEnd = player.play(L.current).toneEnd;
      armTimeout();
    }, wait);
  } else {
    schedule(nextTrial, wait);
  }
}
$('#btn-resume').addEventListener('click', resume);
$('#btn-finish').addEventListener('click', () => { $('#pause-overlay').hidden = true; finishLesson(); });
// Esc / tlačítko pauzy při návrhu únavy = pauza
const togglePause = () => { if (!$('#fatigue-overlay').hidden) fatigueChoice('pause'); else if (L.paused) resume(); else pause(); };

function fatigueNote(trials) {
  // M5: průběžná detekce (FatigueMonitor). Náhradní srovnání první a poslední třetiny jen bez základu sezení.
  const ev = L.fatEvents.at(-1);
  if (ev) {
    const what = ev.kind === 'ttr' ? `reakce byla o ${Math.round((ev.ttrUp - 1) * 100)} % pomalejší` : `úspěšnost byla o ${Math.round(ev.accDrop * 100)} p. b. nižší`;
    return `Během lekce se ukázala únava (${what} než na začátku sezení). Před další lekcí si dej delší pauzu – aspoň ${SESSION_BREAK_MIN} min, nebo pokračuj zítra.`;
  }
  if (L.fat?.base) {
    if (!L.fat.last.held) return null;
    return `Ke konci lekce ${L.fat.last.ttrUp >= FATIGUE_TTR ? 'se zpomalila reakce' : 'klesla úspěšnost'} proti začátku sezení – možná únava. Dej si před další lekcí pauzu.`;
  }
  if (trials.length < 30) return null;
  const third = Math.floor(trials.length / 3);
  const part = (ts) => ({ acc: ts.filter((t) => t.ok).length / ts.length, ttr: median(ts.filter((t) => t.ok && t.ttr != null).map((t) => t.ttr)) });
  const f = fatigueSignal(part(trials.slice(0, third)), part(trials.slice(-third)));
  if (!f.tired) return null;
  const why = f.ttrUp >= FATIGUE_TTR ? `reakce se zpomalila o ${Math.round((f.ttrUp - 1) * 100)} %` : `úspěšnost klesla o ${Math.round(f.accDrop * 100)} p. b.`;
  return `Ke konci lekce ${why} – možná únava. Dej si před další lekcí pauzu.`;
}

const ARROWS = { up: '↑', down: '↓', flat: '→' };
const ARROW_TITLES = { up: 'lepší než dlouhodobě', down: 'horší než dlouhodobě', flat: 'jako dlouhodobě' };

function finishLesson() {
  L.running = false;
  L.paused = false;
  clearInterval(L.tick); clearTimeout(L.timeout); clearTimeout(L.pending);
  inputHandler = repeatHandler = pauseHandler = null;
  player.stop();
  keepAwake(false);
  $('#ls-phase').hidden = true;
  $('#fatigue-overlay').hidden = true;
  $('#pause-overlay').hidden = true;
  if (L.fat?.base) Object.assign(sessionFat, { base: L.fat.base, key: L.fatKey });
  if (L.fatEvents.length || L.fat?.last.held) lastFatigueAt = Date.now();
  const prevAcc = progress.history.filter((h) => (h.mode || 'znak') === 'znak').at(-1)?.acc ?? null;
  player.settings = settings;
  let flu = null;
  if (L.flu) {
    const fs = L.flu.drill.summary();
    if (fs.trials) flu = { n: fs.trials, acc: fs.accuracy, ttr: fs.medianTtr, ...L.flu.tempo };
    L.drill = L.flu.main;
    L.flu = null;
  }
  const sum = L.drill.summary();
  if (sum.trials === 0) { show('home'); return; }
  const warmup = L.warm ? warmupStats(L.drill.trials.slice(0, L.warm.n ?? L.drill.trials.length), L.warm.gapH) : null;

  const levelBefore = progress.level;
  const a = sum.advance;
  // smyčka b: postup v lekci musí platit v jiném sezení, než kdy přibyl nejnovější znak (upevnění spánkem)
  const gate = a.ok ? confirmGate([...progress.history, { at: new Date().toISOString(), level: levelBefore }], levelBefore, Date.now()) : null;
  const adv = !a.ok ? a.reason : (progress.level >= KOCH_ORDER.length ? 'full' : (gate.ok ? 'ok' : 'confirm'));
  addLesson({
    at: new Date().toISOString(), device: deviceKind(), level: levelBefore, durS: Math.round(L.activeMs / 1000),
    trials: sum.trials, correct: sum.correct, acc: sum.accuracy, ttr: sum.medianTtr,
    wpm: settings.wpm, fwpm: settings.fwpm,
    detail: {
      perChar: sum.perChar.filter((r) => r.n > 0), confusions: sum.confusions.slice(0, 30),
      diff: sum.diff, diffLog: sum.diffLog.slice(-60), adv, ...(warmup ? { warmup } : {}),
      ...(L.fat.base || L.fatEvents.length ? { fatigue: { base: L.fat.base, events: L.fatEvents } } : {}),
      ...(L.pauses.length ? { pauses: L.pauses } : {}),
      ...(sum.gapLog.length ? { gapLog: sum.gapLog.slice(-30) } : {}),
      ...(flu ? { fluency: flu } : {}),
    },
  });
  let verdict;
  const rec = a.recent === null ? null : Math.round(a.recent * 100);
  const nc = a.newChar ? `„${a.newChar}“` : '';
  if (adv === 'confirm') {
    verdict = `Výborně, ${rec} %! Znak ${nc} se potvrdí v příštím sezení (za ${String(Math.max(0.5, gate.waitH)).replace('.', ',')} h nebo zítra) – paměť si ho přes pauzu a spánek upevní. Pak přibude další znak.`;
  } else if (a.ok && progress.level < KOCH_ORDER.length) {
    progress.level++;
    verdict = `Výborně! ${rec} % v posledních ${ADVANCE_WINDOW} znacích. Další lekce přidá znak „${KOCH_ORDER[progress.level - 1]}“.`;
  } else if (a.ok) {
    verdict = `Výborně! ${rec} % – máš celou sadu.`;
  } else if (a.reason === 'few') {
    verdict = `Pro přidání znaku je potřeba aspoň ${ADVANCE_WINDOW} znaků v lekci (teď ${sum.trials}).`;
  } else if (a.reason === 'acc') {
    verdict = `Pro přidání znaku je potřeba ${Math.round(ADVANCE_ACCURACY * 100)} % v posledních ${ADVANCE_WINDOW} znacích (teď ${rec} %). Pokračuj se stejnou sadou – plato je normální.`;
  } else if (a.reason === 'ttrUnstable') {
    verdict = `Celkově ${rec} %, ale ke konci se reakce zpomalila (${Math.round((a.ttrRatio - 1) * 100)} %). Znak přidáme, až bude reakce stabilní – zkus to po pauze.`;
  } else if (a.reason === 'newFew') {
    verdict = `Celkově ${rec} %, ale nový znak ${nc} zazněl jen ${a.newN}× (potřeba ${NEW_MIN_N}×). Zkus delší lekci.`;
  } else if (a.reason === 'newAcc') {
    verdict = `Celkově ${rec} %, ale nový znak ${nc} jen ${Math.round(a.newAcc * 100)} % (potřeba ${Math.round(NEW_ACCURACY * 100)} %). Ještě ho procvič.`;
  } else {
    verdict = `Celkově ${rec} %, ale na nový znak ${nc} reaguješ pomaleji (${a.newTtr} ms, ostatní ${a.othersTtr} ms). Ještě ho procvič, ať ho poznáš okamžitě.`;
  }
  saveProgress();

  $('#rs-acc').textContent = `${Math.round(sum.accuracy * 100)} %`;
  $('#rs-ttr').textContent = sum.medianTtr !== null ? `${sum.medianTtr} ms` : '–';
  $('#rs-n').textContent = sum.trials;
  const fat = fatigueNote(L.drill.trials);
  // M6: tempo v lekci
  const notes = [verdict];
  if (fat) notes.push(fat);
  if (sum.gapLog.length) notes.push('Část lekce běžela s delšími mezerami (úspěšnost klesla pod 75 %) – to je v pořádku, trenér tak dává víc času na rozpoznání.');
  if (flu) notes.push(`Blok plynulosti: ${Math.round(flu.acc * 100)} % při ${flu.wpm}/${flu.fwpm} WPM${flu.ttr ? `, reakce ${flu.ttr} ms` : ''} (do výsledku se nepočítá).`);
  $('#rs-verdict').textContent = notes.join(' ');
  const ld = currentLoad();
  const rl = $('#rs-load');
  rl.hidden = false;
  rl.className = ld.suggestEnd || ld.dayWarn ? 'hint warn' : 'hint';
  const gapTxt = warmup?.gapH != null ? ` po pauze ${warmup.gapH >= 24 ? `${Math.round(warmup.gapH / 24)} d` : `${String(warmup.gapH).replace('.', ',')} h`}` : '';
  const drop = warmup && prevAcc != null && warmup.acc < prevAcc - 0.03;
  const wu = warmup ? `Rozcvička: ${Math.round(warmup.acc * 100)} % z ${warmup.n} znaků${gapTxt}${prevAcc != null ? ` (konec minulého sezení ${Math.round(prevAcc * 100)} %)` : ''}${drop
    ? ' – mírný pokles po pauze je normální, není to regres; během lekce se srovná. '
    : ' – tak dobře si znaky pamatuješ. '}` : '';
  rl.textContent = wu + (ld.dayWarn
    ? `Dnes už ${fmtMin(ld.dayMin)} min. Víc než ${DAY_WARN_MIN} min denně už moc nepřidá – pokračuj raději zítra.`
    : ld.suggestEnd
      ? `Sezení trvá ${fmtMin(ld.sessionMin)} min – po ${SESSION_END_MIN} min klesá soustředění. Navrhuji skončit; přes pauzu a spánek se naučené upevní.`
      : `Sezení ${fmtMin(ld.sessionMin)} min. Před dalším blokem si dej aspoň 30 s pauzu.`);

  const rows = sum.perChar.filter((r) => r.n > 0)
    .sort((a, b) => (a.acc - b.acc) || ((b.ttr || 0) - (a.ttr || 0)));
  const tb = $('#rs-perchar');
  tb.textContent = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    const arrow = trendArrow(r, L.prior[r.ch]);
    for (const txt of [r.ch, r.n, `${Math.round(r.acc * 100)} %`, r.ttr !== null ? `${r.ttr} ms` : '–', ARROWS[arrow] || '']) {
      const td = document.createElement('td'); td.textContent = txt; tr.append(td);
    }
    if (arrow) { tr.lastChild.className = `arrow ${arrow}`; tr.lastChild.title = ARROW_TITLES[arrow]; }
    if (r.acc < 0.9) tr.className = 'weak';
    tb.append(tr);
  }
  $('#rs-conf').textContent = sum.confusions.length
    ? `Záměny: ${sum.confusions.slice(0, 5).map((c) => `${c.pair} ${c.n}×`).join(', ')}`
    : 'Žádné záměny.';
  show('result');
}

// ================= STATISTIKA =================
function drawStats() {
  renderDashboard($('#dash-root'), coachInfo.data?.dashboard || null);
  renderStats($('#stats-root'), {
    stats, level: progress.level,
    onPlay: async (ch) => { if (await ensureAudio()) player.play(ch); },
  });
}

// ================= NASTAVENÍ =================
const steppers = [];
const target = (d) => (d.target === 'progress' ? progress : settings);

function renderSteppers() {
  for (const { el, out, minus, plus } of steppers) {
    const d = el.dataset;
    const v = target(d)[d.key];
    out.textContent = Math.round(v * Number(d.scale || 1)) + d.unit;
    minus.disabled = v <= Number(d.min) + 1e-9;
    plus.disabled = v >= Number(d.max) - 1e-9 || (d.key === 'fwpm' && v >= settings.wpm);
  }
  $('#wpm-warn').hidden = settings.wpm >= 15;
  $('#auto-speed').checked = settings.autoSpeed !== 0;
}
$('#auto-speed').addEventListener('change', (e) => {
  settings.autoSpeed = e.target.checked ? 1 : 0;
  saveSettings();
});

function initSteppers() {
  for (const el of document.querySelectorAll('.stepper')) {
    const d = el.dataset;
    const mk = (txt, label, dir) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'st-btn'; b.textContent = txt; b.setAttribute('aria-label', label);
      b.addEventListener('click', () => {
        const obj = target(d);
        const step = Number(d.step);
        let v = Math.round((obj[d.key] + dir * step) / step) * step;
        obj[d.key] = Math.min(Number(d.max), Math.max(Number(d.min), Number(v.toFixed(3))));
        if (settings.fwpm > settings.wpm) settings.fwpm = settings.wpm; // mezery nesmí být rychlejší než znak
        if (d.target === 'progress') saveProgress(); else saveSettings();
        renderSteppers();
      });
      return b;
    };
    const minus = mk('−', 'snížit', -1);
    const out = document.createElement('output');
    const plus = mk('+', 'zvýšit', +1);
    el.append(minus, out, plus);
    steppers.push({ el, out, minus, plus });
  }
}

$('#play-k').addEventListener('click', async () => { if (await ensureAudio()) player.play('K'); });
$('#play-paris').addEventListener('click', async () => { if (await ensureAudio()) player.play('PARIS PARIS'); });

// ================= diagnostika a instalace =================
let installEvt = null;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvt = e; $('#install').hidden = false; });
window.addEventListener('appinstalled', () => { $('#install').hidden = true; });
$('#install').addEventListener('click', () => { if (installEvt) { installEvt.prompt(); installEvt = null; $('#install').hidden = true; } });

async function refreshDiag() {
  const lat = player.latencyInfo();
  let ver = '?';
  try { ver = (await (await fetch('/api/health')).json()).version; } catch (e) { ver = 'server nedostupný'; }
  const standalone = matchMedia('(display-mode: standalone)').matches;
  const rows = [
    ['Verze', ver],
    ['HTTPS', window.isSecureContext ? 'ano ✓' : 'NE'],
    ['Spuštěno jako aplikace', standalone ? 'ano ✓' : 'ne (v prohlížeči)'],
    ['Wake Lock', 'wakeLock' in navigator ? 'ano ✓' : 'ne'],
    ['Zvuk', player.ctx ? player.ctx.state : 'zatím nezapnut'],
    ['Latence zvuku', lat ? `základní ${lat.base} ms, výstup ${lat.output} ms` : '– (zapni zvuk tlačítkem Přehrát)'],
    ['Uloženo lekcí', String(progress.history.length)],
    ['Neodeslané lekce', String(sync.outbox.length)],
    ['Zařízení', deviceKind() === 'mobil' ? 'mobil (dotyk)' : 'PC'],
    ['Adresa', isPublic() ? 'venku přes internet' : 'domácí síť'],
  ];
  const tb = $('#diag');
  tb.textContent = '';
  for (const [k, v] of rows) {
    const tr = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = k;
    const td = document.createElement('td'); td.textContent = v;
    tr.append(th, td); tb.append(tr);
  }
}

// ================= start =================
initSteppers();
{ // 0.8.2: odkaz na druhou verzi aplikace (domácí ↔ venkovní) v Diagnostice
  const o = otherSite();
  const a = $('#other-site');
  if (o) { a.href = o.url; a.textContent = `${o.label} (${o.name})`; } else a.hidden = true;
  if (isPublic()) document.title = 'Morse venku';
}
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});

// Data ze serveru (jiné zařízení) – překreslit, ale nikdy ne uprostřed lekce.
onDataChange(() => {
  if (view === 'home') renderHome();
  else if (view === 'settings') renderSteppers();
  else if (view === 'account') renderAccount();
  else if (view === 'stats') drawStats();
});
// Návrat do aplikace (telefon ↔ PC) → stáhnout novinky.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && ['home', 'settings', 'account', 'result', 'stats', 'copyresult'].includes(view)) backgroundSync();
  if (document.visibilityState === 'hidden' && view === 'copy') copyCtl.hold(); // proud nesmí běžet do prázdna
  player.keepAlive(document.visibilityState === 'visible' && ['lesson', 'intro', 'discrim', 'copy'].includes(view));
});
window.addEventListener('online', () => backgroundSync());

startAuth(show).then((ok) => { if (ok) show('home'); });
