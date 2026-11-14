// SPDX-License-Identifier: EUPL-1.2
// Koch-method lessons (M1) + accounts and sync (M2) + statistics and discrimination (M3) + coach: plan, load, levels (M4)
// + fatigue in a lesson, warm-up after a break, progress dashboard (M5).
import { t, fmtNum, fmtDate, setLang, lang, LANGUAGES } from './i18n.js';
import { isPublic, otherSite } from './site.js';
import { traceBegin, traceEnd, tr, traceAudio, audioMeta, setBeforeHide } from './trace.js';
import { MorsePlayer } from './audio.js';
import { TouchKeyboard } from './keyboard.js';
import { normalizeKey, KOCH_ORDER, maxLevel } from './charset.js';
import {
  Drill, charsForLevel, median, trendArrow, pickContrasts, discrimSequence,
  ADVANCE_WINDOW, ADVANCE_ACCURACY, NEW_MIN_N, NEW_ACCURACY,
} from './drill.js';
import {
  settings, progress, sync, stats, coachInfo, setCoachInfo, saveSettings, saveProgress, addLesson, onDataChange,
  MODE_CHAR, MODE_COPY, MODE_HEAD,
} from './storage.js';
import { renderQuiz } from './quiz.js';
import { renderPlan } from './plan.js';
import { renderDashboard } from './dashboard.js';
import { renderStats, confusionsWith } from './stats.js';
import {
  confirmGate, sessionLoad, warmupStats, fatigueSignal, WARMUP_S, SESSION_END_MIN, DAY_WARN_MIN, FATIGUE_TTR,
  FatigueMonitor, PaceWatch, fatigueRef, lessonPace, SLOW_DAY, REWARM_PAUSE_MIN, REWARM_S, SESSION_BREAK_MIN,
} from './coach.js';
import { startAuth, renderAccount, backgroundSync, session, sessionExpired } from './account.js';
import { deviceKind, DEVICE_MOBILE } from './api.js';
import { initCopy } from './copylesson.js';
import { initHead } from './headlesson.js';
import { initEntry } from './entrytest.js';
import { initDemo } from './demo.js';
import { initBandLab } from './bandlab.js';
import { initKeyerUi } from './keyerui.js';
import { renderUsers } from './usersui.js';
import { initCwRoom } from './cwroomui.js';
import { initCwBell } from './cwbell.js';
import { initCwChannel } from './cwchannel.js';
import { initVoUi } from './voui.js';
import { initDemoBand } from './demoband.js';
import { initVocab } from './vocabui.js';
import { showVisitCount } from './visitcount.js';
import { initFwUi } from './fwui.js';
import * as WPM from '../vendor/morse-pro/morse-pro-wpm.js';

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ANSWER_TIMEOUT = 6000; // ms after the end of the character → "don't know"
// 0.5.1: the correction is played at the earliest FIX_AFTER_PRESS after the answer AND FIX_AFTER_TONE after the
// original character has finished (the answer may come while the character still plays – the correction used to clash with it).
const FIX_AFTER_PRESS = 600;
const FIX_AFTER_TONE = 700;
const untilTone = (toneEnd) => Math.max(0, toneEnd - performance.now());
const fixDelay = (toneEnd) => Math.max(FIX_AFTER_PRESS, untilTone(toneEnd) + FIX_AFTER_TONE);
// Delay of the first character after a pause in a lesson (with a pause ≥ 5 s the audio is also warmed up)
const RESUME_SHORT_MS = 600;   // pause < 5 s
const RESUME_MS = 1500;        // pause < REWARM_PAUSE_MIN
const RESUME_LONG_MS = 2500;   // long pause – Android puts the audio output to sleep meanwhile

const player = new MorsePlayer();
player.settings = settings; // shared object (wpm, fwpm, freq, volume)

// ================= navigation =================
let view = 'home';
const PUBLIC_VIEWS = ['login', 'register', 'reset', 'demo'];
const TRAINING_VIEWS = ['home', 'intro', 'discrim', 'lesson', 'result', 'stats', 'quiz', 'copyhome', 'copy', 'copyresult', 'vocab', 'head', 'headresult', 'entry', 'entryresult'];
// 0.8.6: user menu (icon top right)
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

// 0.9.7 (Z-08): new app version activated by the service worker → reload outside a lesson
// 0.13.4: + management, account and settings (the administrator lands in User management and never saw Home)
const UPDATE_SAFE_VIEWS = ['home', 'stats', 'copyhome', 'login', 'demo', 'users', 'account', 'settings'];
const updateReload = { pending: false, done: false };
function reloadForUpdate() {
  updateReload.done = true;
  tr('swUpdate', view);
  location.reload();
}

// 0.13.9 (Martin): a reload (F5, pull to refresh in the PWA) stays on the page – the last restorable view of this
// tab is kept in sessionStorage per user; lessons and results are not restored (a reload aborts the lesson → the page
// the lesson started from). A new tab / app start opens Home as before.
const RESTORE_VIEWS = ['home', 'copyhome', 'stats', 'vocab', 'account', 'users', 'cw', 'settings', 'band', 'key', 'demo'];
const RESTORE_KEY = 'morse.view';
function rememberView(name) {
  if (!RESTORE_VIEWS.includes(name)) return;
  try { sessionStorage.setItem(RESTORE_KEY, JSON.stringify({ u: session.user?.id ?? null, v: name })); } catch (e) { /* private mode */ }
}
function restoredView(fallback) {
  try {
    const r = JSON.parse(sessionStorage.getItem(RESTORE_KEY) || 'null');
    if (r && RESTORE_VIEWS.includes(r.v) && r.u === (session.user?.id ?? null)) return r.v;
  } catch (e) { /* private mode, damaged value */ }
  return fallback;
}

function show(name) {
  if (!session.user && !PUBLIC_VIEWS.includes(name)) name = 'login';
  if (session.user?.pw_change) name = 'pwchange'; // E3: new password first
  const admin = session.user?.role === 'admin'; // the administrator only manages, does not train
  const staff = admin || session.user?.role === 'trener';
  if (admin && TRAINING_VIEWS.includes(name)) name = 'users'; // 0.13.0: management is the administrator's home
  if (name === 'users' && !staff) name = 'account';
  const out = !session.user; // 0.9.2: logged out = tabs Log in / Try it (demo)
  $('.tabs [data-go="home"]').hidden = admin || out;
  for (const el of document.querySelectorAll('.training-only')) el.hidden = admin || out;
  for (const el of document.querySelectorAll('.public-only')) el.hidden = !out;
  const coach = session.user?.role === 'trener'; // ZB lab (development) – coaches only
  for (const el of document.querySelectorAll('.coach-only')) el.hidden = !coach;
  for (const el of document.querySelectorAll('.staff-only')) el.hidden = !staff;
  for (const el of document.querySelectorAll('.member-only')) el.hidden = out;
  const keyLab = coach || !!session.user?.key_lab; // 0.14.4: the trainer can open the key page to a student
  for (const el of document.querySelectorAll('.keylab-only')) el.hidden = !keyLab;
  if ((name === 'band' && !coach) || (name === 'key' && !keyLab)) name = 'settings'; // VK (0.11.0): experimental
  $('.usermenu').hidden = out;
  if (view === 'demo' && name !== 'demo') { demo.stop(); demoBand.stop(); }
  if (view === 'band' && name !== 'band') bandLab.stop();
  if (view === 'key' && name !== 'key') keyUi.stop();
  if (view === 'cw' && name !== 'cw') { cwRoom.stop(); voUi.stop(); }
  if (session.user && !session.user.pw_change && name !== 'cw') cwBell.start(); else cwBell.stop(); // 0.13.6
  if (view === 'vocab' && name !== 'vocab') vocab.stop();
  view = name;
  rememberView(name); // before a possible update reload – the new version opens the same page
  if (updateReload.pending && !updateReload.done && UPDATE_SAFE_VIEWS.includes(name)) { reloadForUpdate(); return; }
  for (const v of document.querySelectorAll('.view')) v.hidden = v.id !== `view-${name}`;
  const training = ['lesson', 'intro', 'discrim', 'copy', 'head', 'entry'].includes(name);
  $('#keyboard').hidden = !['lesson', 'discrim', 'copy', 'demo', 'entry'].includes(name);
  player.keepAlive((training || name === 'key' || name === 'cw') && document.visibilityState === 'visible'); // 0.8.5: BT output must not fall asleep
  $('.tabs').hidden = training || name === 'pwchange' || (!session.user && !['login', 'demo'].includes(name));
  $('#user-btn').hidden = name === 'pwchange';
  for (const b of document.querySelectorAll('.tabs button')) b.classList.toggle('active', b.dataset.go === name);
  $('#user-btn').classList.toggle('active', ['settings', 'account', 'stats', 'users'].includes(name));
  closeUserMenu();
  if (name === 'home') renderHome();
  if (name === 'login' || name === 'home') showVisitCount(); // 0.14.6: public visit counter
  if (name === 'settings') { renderSteppers(); refreshDiag(); }
  if (name === 'account') renderAccount();
  if (name === 'users') renderUsers(session.user, session.offline);
  if (name === 'stats') { drawStats(); backgroundSync(); }
  if (name === 'quiz') openQuiz();
  if (name === 'demo') { demo.render(); demoBand.render(); }
  if (name === 'band') bandLab.render();
  if (name === 'key') { sendDefaults(); renderSteppers(); keyUi.render(); fwUi.show(); }
  if (name === 'cw') cwRoom.render();
  if (name === 'vocab') vocab.render();
  if (name === 'copyhome') renderCopyCard();
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

// ================= keyboard and input =================
let inputHandler = null; // (ch, ts) => void – whoever is waiting for an answer right now
const kbd = new TouchKeyboard($('#keyboard'), (ch, ts) => (view === 'copy' ? copyCtl.onChar(ch, ts) : inputHandler?.(ch, ts)), {
  onRepeat: () => repeatHandler?.(),
  onPause: () => (view === 'copy' ? copyCtl.pause() : pauseHandler?.()),
  onSpace: (ts) => copyCtl.onSpace(ts),
});
let repeatHandler = null;
let pauseHandler = null;
const demo = initDemo({
  player, kbd, ensureAudio,
  setHandlers: ({ input = null, repeat = null, pause = null }) => {
    inputHandler = input; repeatHandler = repeat; pauseHandler = pause;
  },
});
const bandLab = initBandLab({ player, ensureAudio }); // ZB listening lab (development, coaches)
// VK (0.11.0): telegraph key (experimental, coaches); 0.12.0 sending exercise from the receive level (≥ 10 characters)
const fwUi = initFwUi(); // 0.15.0: HW key firmware on the key page
// 1.0.2 (Martin): sending has its own characters and tempo; the first time they are taken from receiving
const sendLvl = () => Math.min(maxLvl(), Math.max(2, settings.sendChars || lvl()));
function sendDefaults() {
  let changed = false;
  if (!settings.sendChars) { settings.sendChars = Math.max(2, lvl()); changed = true; }
  if (!settings.sendWpm) { settings.sendWpm = settings.wpm; changed = true; }
  if (changed) saveSettings();
}
const keyUi = initKeyerUi({ player, ensureAudio, getChars: () => charsForLevel(sendLvl()),
  getSendWpm: () => settings.sendWpm || settings.wpm, onHwSeen: () => fwUi.hwSeen(), sync });
const cwLink = {}; // 0.13.2: the channel (keying, playback) – filled below, the room calls it on every poll
const cwRoom = initCwRoom({ player, ensureAudio, onAuth: () => sessionExpired(), link: cwLink }); // 0.13.1
// 0.13.6: who knocks while I am elsewhere in the app – no sound in a lesson or on a sound page
const cwBell = initCwBell({ player, quiet: () => !UPDATE_SAFE_VIEWS.includes(view) || ['login', 'demo'].includes(view) });
Object.assign(cwLink, initCwChannel({ player, ensureAudio, pollSoon: (ms) => cwRoom.pollSoon(ms) }));
// 0.16.0: the virtual operator in the CW room (all in the browser)
const voUi = initVoUi({ player, ensureAudio, getNick: () => session.user?.nick || '', isLinked: () => !!cwRoom.data?.link });
const demoBand = initDemoBand({ player, ensureAudio }); // 0.9.9: band sample in the demo
const vocab = initVocab({ sync, show: (n) => show(n), player, ensureAudio }); // 0.10.0: abbreviations, Q codes, prefixes

document.addEventListener('keydown', (e) => {
  if (view === 'key') { if (keyUi.onKey(e, true)) e.preventDefault(); return; }
  if (view === 'cw') { if (voUi.onKey(e, true) || cwLink.onKey(e, true)) e.preventDefault(); return; }
  if (view === 'copy') { if (copyCtl.onKey(e)) e.preventDefault(); return; }
  if (view === 'head') { if (headCtl.onKey(e)) e.preventDefault(); return; }
  if (view === 'vocab') { if (vocab.onKey(e)) e.preventDefault(); return; }
  if (view !== 'lesson' && view !== 'intro' && view !== 'discrim' && view !== 'demo' && view !== 'entry') return;
  if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
  if (e.key === ' ') { e.preventDefault(); repeatHandler?.(); return; }
  if (view === 'intro') { if (e.key === 'Enter') { e.preventDefault(); intro.next?.(); } return; }
  if (e.key === 'Escape') { e.preventDefault(); pauseHandler?.(); return; }
  const ch = normalizeKey(e.key);
  if (ch) { e.preventDefault(); kbd.flash(ch); inputHandler?.(ch, e.timeStamp); }
});
document.addEventListener('keyup', (e) => {
  if (view === 'key' && keyUi.onKey(e, false)) e.preventDefault(); // VK: paddle released
  if (view === 'cw' && (voUi.onKey(e, false) || cwLink.onKey(e, false))) e.preventDefault(); // 0.13.2: CW room key released
});

// ================= HOME =================
function localMidnight() { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); }
function currentLoad() { return sessionLoad(progress.history, Date.now(), localMidnight()); }
const fmtMin = (m) => fmtNum(Math.round(m));
const pct = (x) => `${Math.round(x * 100)} %`;

// 0.9.6: the set ends with the main programme (44) unless the optional extension is on; the stored level is kept
const maxLvl = () => maxLevel(settings.extraChars === 1);
const lvl = () => Math.min(progress.level, maxLvl());

function newestChar() { return charsForLevel(lvl()).at(-1); }

function renderHome() {
  const chars = charsForLevel(lvl());
  $('#level-count').textContent = t('home.levelCount', { n: chars.length, of: maxLvl() });
  const box = $('#level-chars');
  box.textContent = '';
  for (const c of chars) {
    const s = document.createElement('span');
    s.textContent = c;
    if (c === newestChar()) s.className = 'newest';
    box.append(s);
  }
  const next = chars.length < maxLvl() ? KOCH_ORDER[chars.length] : null;
  $('#level-next').textContent = next
    ? t('home.nextChar', { ch: next, acc: Math.round(ADVANCE_ACCURACY * 100), n: ADVANCE_WINDOW })
    : (settings.extraChars === 1 ? t('home.allChars') : t('home.allCore', { n: maxLvl() }));
  // Z-14: entry test offered on Home to returning/active operators (questionnaire) until they get past the start
  $('#entry-card').hidden = !(coachInfo.data?.prefs?.entryTest && progress.level <= 2);
  $('#lesson-info').textContent = t('home.lessonInfo', { min: settings.lessonMin, wpm: settings.wpm, fwpm: settings.fwpm, freq: settings.freq });
  // M6: pace change by the coach (stays visible until the next lesson)
  const sn = coachInfo.data?.speedNotice;
  const sp = coachInfo.data?.speed;
  const snEl = $('#speed-note');
  snEl.hidden = !sn && !(sp?.change && !sp.change.applied);
  if (sn) snEl.textContent = `${sn.text} ${sn.why}`;
  else if (sp?.change && !sp.change.applied) {
    snEl.textContent = t('home.speedProposal', { wpm: sp.change.to.wpm, fwpm: sp.change.to.fwpm, why: sp.change.why });
  }
  const ld = currentLoad();
  const li = $('#load-info');
  li.hidden = ld.dayMin === 0;
  li.className = ld.suggestEnd || ld.dayWarn ? 'hint center warn' : 'hint center';
  li.textContent = ld.dayWarn
    ? t('home.loadDayWarn', { min: fmtMin(ld.dayMin), max: DAY_WARN_MIN })
    : ld.suggestEnd
      ? t('home.loadSessionEnd', { min: fmtMin(ld.sessionMin) })
      : (ld.newSession ? t('home.loadToday', { min: fmtMin(ld.dayMin) })
        : t('home.loadTodaySession', { min: fmtMin(ld.dayMin), session: fmtMin(ld.sessionMin) }));
  if (!ld.newSession && lastFatigueAt && Date.now() - lastFatigueAt < SESSION_BREAK_MIN * 60000) {
    li.hidden = false;
    li.className = 'hint center warn';
    li.textContent += ` ${t('home.loadFatigue', { min: SESSION_BREAK_MIN })}`;
  }

  renderPlan($('#plan-root'), coachInfo.data, { onQuiz: () => show('quiz') });

  const tb = $('#history');
  tb.textContent = '';
  const last = progress.history.slice(-10).reverse();
  $('#history-empty').hidden = last.length > 0;
  for (const h of last) {
    const row = document.createElement('tr');
    const d = fmtDate(h.at, { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' });
    const what = h.mode === MODE_COPY ? t('home.histCopy') : h.mode === MODE_HEAD ? t('home.histHead') : t('home.histChars', { n: h.level });
    for (const txt of [d, what, pct(h.acc), h.ttr ? `${h.ttr} ms` : '–']) {
      const td = document.createElement('td'); td.textContent = txt; row.append(td);
    }
    tb.append(row);
  }
}

// ================= COPY BEHIND (M7) =================
const copyCtl = initCopy({
  player, kbd, show, settings, progress, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind, currentLoad,
  fallbackChars: () => charsForLevel(lvl()), level: lvl,
  vocabForms: () => vocab.copyForms(), // 0.10.9: abbreviations in copy behind only from the vocabulary trainer
});
$('#btn-copy').addEventListener('click', () => withDndTip(() => copyCtl.start()));
$('#btn-copy-again').addEventListener('click', () => copyCtl.start());

// ================= HEAD COPY (U6, 0.10.14) =================
const headCtl = initHead({
  player, show, settings, coachInfo, addLesson, ensureAudio, keepAwake, deviceKind, currentLoad,
  fallbackChars: () => charsForLevel(lvl()), level: lvl,
});
$('#btn-head').addEventListener('click', () => withDndTip(() => headCtl.start()));
$('#btn-head-again').addEventListener('click', () => headCtl.start());

// ================= ENTRY TEST (Z-14, 0.10.16) =================
const entryCtl = initEntry({
  player, kbd, show, settings, progress, addLesson, saveProgress, ensureAudio, keepAwake, deviceKind, level: lvl,
  setHandlers: ({ input = null, repeat = null, pause = null }) => { inputHandler = input; repeatHandler = repeat; pauseHandler = pause; },
});
for (const b of document.querySelectorAll('.btn-entry')) b.addEventListener('click', () => withDndTip(() => entryCtl.start()));

const COPY_EARLY_MIN = 10; // = server/coach.py COPY_EARLY_MIN (test): trial copy behind from this many mastered characters

/** 0.10.10: own view of copy behind (top bar) – the lesson card, or when locked what unlocks it. */
function renderCopyCard() {
  const cp = coachInfo.data?.copy;
  $('#copy-card').hidden = !cp?.available;
  $('#copy-locked').hidden = !!cp?.available;
  if (!cp?.available) {
    $('#copy-locked-text').textContent = t('copy.locked', { n: COPY_EARLY_MIN, m: cp?.chars?.length ?? 0 });
    renderHeadCard();
    return;
  }
  $('#copy-step').textContent = cp.early ? t('home.copyEarly', { step: cp.step }) // Z-16: trial before U3
    : t('home.copyStep', { ulevel: cp.ulevel || 3, step: cp.step, of: cp.of });
  const speed = cp.wpm ? `${cp.wpm}/${cp.wpm}` : `${settings.wpm}/${settings.fwpm}`;
  $('#copy-desc').textContent = t('home.copyDesc', { name: cp.name, gap: cp.gap, speed })
    + (cp.markLag > 1 ? ` ${t('home.copyWordLag')}` : '')
    + (deviceKind() === DEVICE_MOBILE ? ` ${t('home.copyMobile')}` : '');
  $('#copy-note').textContent = [cp.change?.text, cp.change?.why, cp.next].filter(Boolean).join(' ');
  renderHeadCard();
}

/** 0.10.14: head copy card under copy behind – trial from U4, the full ladder from U5. */
function renderHeadCard() {
  const hd = coachInfo.data?.head;
  $('#head-card').hidden = !hd?.available;
  if (!hd?.available) return;
  $('#head-step').textContent = hd.early ? t('home.headEarly') : t('home.headStep', { step: hd.step, of: hd.of });
  $('#head-desc').textContent = t('home.headDesc', { name: hd.name })
    + (deviceKind() === DEVICE_MOBILE ? ` ${t('home.headMobile')}` : '');
  $('#head-note').textContent = [hd.change?.text, hd.change?.why, hd.next].filter(Boolean).join(' ');
}

// ================= QUESTIONNAIRE (M4) =================
function openQuiz() {
  renderQuiz($('#quiz-root'), {
    onDone: (info) => {
      // the suggested settings apply right away (can be changed in Settings); limits as with the steppers
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

// 0.9.7 (Z-07): a new account (no lesson, no questionnaire) gets the questionnaire offered before the first lesson –
// the card on Home alone was overlooked. Once a lesson exists it is never offered again (nothing stored).
let quizOfferSkipped = false;
const quizOfferDue = () => !quizOfferSkipped && !progress.history.length && coachInfo.data && !coachInfo.data.archetype;
$('#btn-start').addEventListener('click', () => {
  if (quizOfferDue()) { tr('quizOffer'); $('#quiz-offer').hidden = false; $('#quiz-offer-fill').focus(); return; }
  withDndTip(startTraining);
});
$('#quiz-offer-fill').addEventListener('click', () => { $('#quiz-offer').hidden = true; show('quiz'); });
$('#quiz-offer-skip').addEventListener('click', () => { $('#quiz-offer').hidden = true; quizOfferSkipped = true; withDndTip(startTraining); });
// 0.9.7 (Z-02): once per phone – a notification interrupts the sound and the focus → tip to turn on Do not disturb.
// Remembered in this browser only (a per-device thing); the callback runs from the button click (audio unlock still works).
const DND_KEY = 'morse-dnd-tip';
let dndNext = null;
function withDndTip(fn) {
  let seen = true;
  try { seen = deviceKind() !== DEVICE_MOBILE || localStorage.getItem(DND_KEY) === '1'; } catch (e) { /* storage blocked */ }
  if (seen) { fn(); return; }
  dndNext = fn;
  tr('dndTip');
  $('#dnd-tip').hidden = false;
  $('#dnd-tip-ok').focus();
}
$('#dnd-tip-ok').addEventListener('click', () => {
  try { localStorage.setItem(DND_KEY, '1'); } catch (e) { /* storage blocked */ }
  $('#dnd-tip').hidden = true;
  const fn = dndNext; dndNext = null; fn?.();
});
$('#btn-again').addEventListener('click', startTraining);

async function startTraining() {
  if (!(await ensureAudio())) { alert(t('audio.failed')); return; }
  const chars = charsForLevel(lvl());
  kbd.setMode(MODE_CHAR);
  kbd.setActive(chars);
  await keepAwake(true);
  if (coachInfo.data?.speedNotice) setCoachInfo({ ...coachInfo.data, speedNotice: null }); // seen on Home
  const fresh = chars.filter((c) => !progress.introduced.includes(c));
  traceAudio(player.ctx);
  traceBegin(MODE_CHAR, {
    level: lvl(), chars: chars.join(''), fresh: fresh.join(''), device: deviceKind(),
    standalone: matchMedia('(display-mode: standalone)').matches, public: isPublic(),
    set: { wpm: settings.wpm, fwpm: settings.fwpm, freq: settings.freq, vol: settings.volume, min: settings.lessonMin },
    load: currentLoad(), audio: audioMeta(player), ulevel: coachInfo.data?.ulevel ?? null, ua: navigator.userAgent.slice(0, 200),
  });
  // warm-up: the first lesson of a new session starts with 1–2 min of known characters only (retention measure, R1)
  const ld = currentLoad();
  L.warm = ld.newSession && progress.history.length ? { gapH: ld.gapH, n: null, fresh } : null;
  if (ld.newSession) sessionFat.base = null; // the fatigue baseline belongs to the session
  L.fresh = fresh;
  if (fresh.length) {
    tr('intro', fresh.join(''));
    await runIntro(fresh);
    tr(intro.skip ? 'introSkip' : 'discrim');
    if (!intro.skip) await runDiscrim(fresh, chars);
  }
  kbd.setActive(chars);
  startLesson(chars);
}

// ================= INTRODUCTION =================
// Listening only: the character is shown and plays 3×. No keyboard – answers come in the lesson.
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
    $('#intro-label').textContent = list.length > 1 ? t('intro.labelOf', { i: i + 1, n: list.length }) : t('intro.label');
    $('#intro-char').textContent = c;
    $('#intro-status').textContent = t('intro.listen');
    $('#intro-next').hidden = true;
    await sleep(i === 0 ? 1000 : 300); // longer pause before the first character – audio settles after start
    for (let k = 0; k < 3 && !intro.skip; k++) { await player.play(c).done; await sleep(450); }
    if (!progress.introduced.includes(c)) progress.introduced.push(c);
    saveProgress();
    if (intro.skip) break;
    $('#intro-status').textContent = t('intro.remember');
    $('#intro-next').textContent = i + 1 < list.length ? t('intro.nextChar') : t('home.start');
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

// ================= DISCRIMINATION =================
// After the introduction: short discrimination of the new character against 1–2 similar-sounding / confused ones.
// Immediate feedback, results are not stored (just a warm-up before the lesson).
const DS = { skip: false, current: null, toneEnd: 0, timer: null, resolve: null, arm: null };

function discrimPlan(fresh, chars) {
  const targets = fresh.slice(-2);
  const pool = chars.filter((c) => !targets.includes(c));
  const conf = {};
  for (const tg of targets) for (const [c, n] of Object.entries(confusionsWith(stats.chars, tg))) conf[c] = (conf[c] || 0) + n;
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
  $('#ds-label').textContent = t('discrim.labelChars', { chars: active.join('  ') });
  $('#ds-char').textContent = '';
  $('#ds-status').textContent = t('discrim.question');
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
      $('#ds-status').textContent = t('lesson.correct');
      await sleep(Math.max(700, untilTone(DS.toneEnd) + charGap()));
    } else {
      $('#ds-char').className = ans ? 'big-char bad' : 'big-char miss';
      $('#ds-status').textContent = ans ? t('lesson.wasYou', { ch: c, ans }) : t('lesson.was', { ch: c });
      kbd.flash(c, 'hint', 1500);
      await sleep(fixDelay(DS.toneEnd)); // until the original character has finished
      if (!DS.skip) await player.play(c).done;
      await sleep(afterFixGap());
    }
  }
  if (!DS.skip) {
    $('#ds-char').textContent = '';
    $('#ds-status').textContent = t('discrim.done', { ok, n: seq.length });
    await sleep(1500);
  }
  player.stop();
  DS.current = null;
  inputHandler = repeatHandler = pauseHandler = null;
}
$('#ds-replay').addEventListener('click', () => repeatHandler?.());
$('#ds-skip').addEventListener('click', () => pauseHandler?.());

// ================= LESSON =================
const L = {
  drill: null, prior: {}, running: false, paused: false, answered: true, current: null,
  toneEnd: 0, repeats: 0, activeMs: 0, lastTick: 0, tick: null, pending: null, timeout: null,
  warm: null, // warm-up {gapH, n (warm-up trials, null = still running), fresh}
  fresh: [], fat: null, fatEvents: [], fatPending: null, pauses: [], pauseAt: 0, rewarmUntil: 0,
  flu: null, // M6: fluency block {main (lesson drill), drill, tempo}
};
// ---- M6: lesson pace ----
// The lesson plays the configured pace; with difficulties (Drill.gapEase) longer gaps, in the fluency block faster.
function setTempo() {
  const tp = L.flu ? L.flu.tempo : { wpm: settings.wpm, fwpm: L.drill.lessonFwpm(settings.fwpm) };
  player.settings = { ...settings, ...tp };
}
// Fluency block (from U2, R1 ch. 6): end of the lesson, mastered characters one step faster, not counted.
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
  tr('flu');
  const main = L.drill;
  let chars = main.chars.filter((c) => main.isMastered(c));
  if (chars.length < 4) chars = main.chars.filter((c) => c !== main.newChar);
  const tempo = fluencyTempo();
  L.flu = { main, drill: new Drill(chars, null, { prior: L.prior }), tempo };
  L.drill = L.flu.drill;
  $('#ls-phase').textContent = t('lesson.fluency', { wpm: tempo.wpm, fwpm: tempo.fwpm });
  $('#ls-phase').hidden = false;
}
// M5: the fatigue baseline (start of the session) survives between lessons of the same session; time of the last fatigue for Home
const sessionFat = { base: null, key: null }; // 0.8.4: the baseline only applies to the same character set
let lastFatigueAt = 0;
const activeS = () => Math.round(L.activeMs / 1000);
const inWarmup = () => (L.warm && L.warm.n === null) || L.activeMs < L.rewarmUntil;

function endRewarm() {
  if (!L.rewarmUntil || L.activeMs < L.rewarmUntil) return;
  L.rewarmUntil = 0;
  tr('rewarmEnd');
  if (!(L.warm && L.warm.n === null)) { L.drill.setExclude([]); $('#ls-phase').hidden = true; }
}

function trackFatigue() {
  const tl = L.drill.trials.at(-1);
  const count = !inWarmup() && !L.flu;
  const r = L.fat.add({ ch: tl.ch, ok: tl.ok, ttr: tl.ttr }, activeS(), count);
  if (r.propose && !L.fatPending) L.fatPending = r;
  // Z-17 shadow mode (owner 2026-11-07): the long-term detector only writes to the debug trace, it proposes nothing
  const pw = L.paceWatch.add({ ch: tl.ch, ok: tl.ok, ttr: tl.ttr }, activeS(), count);
  if (pw.propose) tr('pw', [Math.round(activeS()), Math.round(pw.med * 1000) || null, pw.lapses]);
}

function proposeFatigue() {
  const r = L.fatPending;
  L.fatPending = null;
  L.fatEvents.push({ t: activeS(), kind: r.kind, ttrUp: r.ttrUp, accDrop: r.accDrop, action: null });
  tr('fat', { kind: r.kind, ttrUp: r.ttrUp, accDrop: r.accDrop });
  pause(false);
  const why = r.kind === 'ttr'
    ? t('fatigue.whyTtr', { pct: Math.round((r.ttrUp - 1) * 100) })
    : t('fatigue.whyAcc', { pp: Math.round(r.accDrop * 100) });
  $('#fat-text').textContent = `${why} ${t('fatigue.advice')}`;
  $('#fatigue-overlay').hidden = false;
}
function fatigueChoice(action) {
  tr('fatChoice', action);
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
    ? t('pause.rewarm', { s: REWARM_S })
    : t('pause.hint', { min: REWARM_PAUSE_MIN });
}

function endWarmup() {
  if (!L.warm || L.warm.n !== null) return;
  L.warm.n = L.drill.trials.length;
  tr('warmEnd', L.warm.n);
  if (L.activeMs < L.rewarmUntil) return; // the warm-up after a pause is still running
  L.drill.setExclude([]);
  $('#ls-phase').hidden = true;
}

function schedule(fn, ms) { clearTimeout(L.pending); L.pending = setTimeout(fn, ms); }
function charGap() {
  // the Farnsworth gap between characters sets the pace of the next character after an answer
  return Math.max(300, Math.round(WPM.charSpace(player.settings.wpm, player.settings.fwpm)));
}
const afterFixGap = () => Math.max(1500, 2 * charGap());
const lessonMs = () => settings.lessonMin * 60000;

function startLesson(chars) {
  L.prior = stats.chars || {}; // long-term statistics before this lesson (selection weights, trend arrows)
  L.drill = new Drill(chars, newestChar(), { prior: L.prior });
  const fatKey = chars.join('');
  const fat = new FatigueMonitor(sessionFat.key === fatKey ? sessionFat.base : null,
    { ref: fatigueRef(L.prior), newChar: newestChar() });
  Object.assign(L, { fat, fatKey, fatEvents: [], fatPending: null, paceWatch: new PaceWatch(fatigueRef(L.prior)), pauses: [], rewarmUntil: 0, flu: null });
  if (L.warm) L.drill.setExclude(L.warm.fresh);
  tr('lesson', { warm: !!L.warm, fatBase: !!fat.base });
  $('#ls-phase').textContent = t('lesson.warmup');
  $('#ls-phase').hidden = !L.warm;
  Object.assign(L, { running: true, paused: false, answered: true, current: null, activeMs: 0, lastTick: performance.now() });
  show('lesson');
  inputHandler = onAnswer;
  repeatHandler = onRepeat;
  pauseHandler = togglePause;
  $('#ls-char').textContent = '';
  $('#ls-status').textContent = t('lesson.getReady');
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
  $('#ls-acc').textContent = d && d.trials.length ? `${pct(d.accuracy)} · ${d.trials.length}` : '–';
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
  // p: character, WPM, Farnsworth, ms until the tone ends, difficulty, phase (w warm-up, r after a pause, f fluency)
  tr('p', [L.current, player.settings.wpm, player.settings.fwpm, Math.round(L.toneEnd - performance.now()),
    L.drill.diff ?? null, inWarmup() ? 'w' : (L.rewarmUntil ? 'r' : (L.flu ? 'f' : ''))]);
  armTimeout();
}

function onAnswer(ch, ts) {
  if (!L.running || L.paused || L.answered) return;
  L.answered = true;
  clearTimeout(L.timeout);
  const ttr = Math.round(ts - L.toneEnd);
  const ok = L.drill.record(L.current, ch, ttr, { repeats: L.repeats });
  tr('a', [ch, ttr, ok ? 1 : 0]);
  trackFatigue();
  $('#ls-char').textContent = L.current;
  updateBar();
  if (ok) {
    $('#ls-char').className = 'big-char ok';
    $('#ls-status').textContent = `${ttr} ms`;
    schedule(nextTrial, untilTone(L.toneEnd) + charGap()); // an answer during the character must not cut it off
  } else {
    $('#ls-char').className = 'big-char bad';
    $('#ls-status').textContent = t('lesson.wasYou', { ch: L.current, ans: ch });
    kbd.flash(L.current, 'hint', 1500);
    schedule(playFix, fixDelay(L.toneEnd));
  }
}

function onTimeout() {
  if (!L.running || L.paused || L.answered) return;
  L.answered = true;
  L.drill.record(L.current, null, null, { timeout: true, repeats: L.repeats });
  tr('to');
  trackFatigue();
  $('#ls-char').textContent = L.current;
  $('#ls-char').className = 'big-char miss';
  $('#ls-status').textContent = t('lesson.was', { ch: L.current });
  kbd.flash(L.current, 'hint', 1500);
  updateBar();
  schedule(playFix, fixDelay(L.toneEnd));
}

// Corrective playback of the right character, then a longer gap – so it does not merge with the next character.
// Everything goes through schedule(), so a pause cancels the planned steps (a Promise .done after a pause
// used to schedule an extra character → two characters on top of each other).
function playFix() {
  if (!L.running || L.paused) return;
  tr('fix');
  const { toneEnd } = player.play(L.current);
  schedule(nextTrial, untilTone(toneEnd) + afterFixGap());
}

function onRepeat() {
  if (!L.running || L.paused || L.answered) return;
  L.repeats++;
  tr('rep');
  L.toneEnd = player.play(L.current).toneEnd;
  armTimeout();
}

function pause(overlay = true) {
  if (!L.running || L.paused) return;
  L.paused = true;
  L.pauseAt = Date.now();
  tr('pause', overlay ? 1 : 0);
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
  // The audio may have been suspended during the pause (Android, screen off) – wake it up still inside the tap handler.
  const audioOk = await ensureAudio();
  resuming = false;
  if (!L.running || !L.paused) return;
  tr('resume', [ps, audioOk ? 1 : 0, player.ctx?.state]);
  if (!audioOk) { alert(t('audio.failedResume')); return; }
  const long = ps >= REWARM_PAUSE_MIN * 60;
  const wait = ps < 5 ? RESUME_SHORT_MS : (long ? RESUME_LONG_MS : RESUME_MS);
  if (ps >= 5) player.warmUp(Math.min(1.5, (wait - 300) / 1000)); // inaudible warm-up of the output
  L.paused = false;
  L.lastTick = performance.now();
  $('#pause-overlay').hidden = true;
  $('#fatigue-overlay').hidden = true;
  $('#ls-char').textContent = '';
  $('#ls-char').className = 'big-char';
  $('#ls-status').textContent = ps >= 5 ? t('lesson.getReady') : '';
  if (ps >= 5) L.pauses.push([activeS(), ps]);
  if (ps >= 5) { L.fat.reset(); L.paceWatch.reset(); } // after a pause fatigue is measured anew
  if (long) {
    // warm-up after a pause: briefly known characters only, counted neither for fatigue nor as the session warm-up
    L.rewarmUntil = L.activeMs + REWARM_S * 1000;
    if (L.fresh.length) L.drill.setExclude(L.fresh);
    $('#ls-phase').textContent = t('lesson.rewarm');
    $('#ls-phase').hidden = false;
  }
  if (!L.answered) {
    // the character interrupted by the pause is played again (does not count as a repeat)
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
// Esc / pause button while fatigue is proposed = pause
const togglePause = () => { if (!$('#fatigue-overlay').hidden) fatigueChoice('pause'); else if (L.paused) resume(); else pause(); };

function fatigueNote(trials) {
  // M5: continuous detection (FatigueMonitor). Fallback comparison of the first and last third only without a session baseline.
  const ev = L.fatEvents.at(-1);
  if (ev) {
    const what = ev.kind === 'ttr'
      ? t('fatigue.noteTtr', { pct: Math.round((ev.ttrUp - 1) * 100) })
      : t('fatigue.noteAcc', { pp: Math.round(ev.accDrop * 100) });
    return t('fatigue.noteEvent', { what, min: SESSION_BREAK_MIN });
  }
  if (L.fat?.base) {
    if (!L.fat.last.held) return null;
    return L.fat.last.ttrUp >= FATIGUE_TTR ? t('fatigue.noteEndTtr') : t('fatigue.noteEndAcc');
  }
  if (trials.length < 30) return null;
  const third = Math.floor(trials.length / 3);
  const part = (ts) => ({ acc: ts.filter((x) => x.ok).length / ts.length, ttr: median(ts.filter((x) => x.ok && x.ttr != null).map((x) => x.ttr)) });
  const f = fatigueSignal(part(trials.slice(0, third)), part(trials.slice(-third)));
  if (!f.tired) return null;
  return f.ttrUp >= FATIGUE_TTR
    ? t('fatigue.noteThirdTtr', { pct: Math.round((f.ttrUp - 1) * 100) })
    : t('fatigue.noteThirdAcc', { pp: Math.round(f.accDrop * 100) });
}

const ARROWS = { up: '↑', down: '↓', flat: '→' };

/** aborted (0.9.7, Z-06): the page is being closed/reloaded – save what was done, never advance. */
function finishLesson(aborted = false) {
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
  const prevAcc = progress.history.filter((h) => (h.mode || MODE_CHAR) === MODE_CHAR).at(-1)?.acc ?? null;
  player.settings = settings;
  let flu = null;
  if (L.flu) {
    const fs = L.flu.drill.summary();
    if (fs.trials) flu = { n: fs.trials, acc: fs.accuracy, ttr: fs.medianTtr, ...L.flu.tempo };
    L.drill = L.flu.main;
    L.flu = null;
  }
  const sum = L.drill.summary();
  if (sum.trials === 0) { traceEnd(null, { empty: true }); show('home'); return; }
  const warmup = L.warm ? warmupStats(L.drill.trials.slice(0, L.warm.n ?? L.drill.trials.length), L.warm.gapH) : null;

  const levelBefore = lvl();
  const a = sum.advance;
  // loop b: advancing in a lesson must hold in a different session than the one where the newest character was added (consolidation by sleep)
  const gate = a.ok ? confirmGate([...progress.history, { at: new Date().toISOString(), level: levelBefore }], levelBefore, Date.now()) : null;
  const adv = aborted ? 'aborted' : !a.ok ? a.reason : (levelBefore >= maxLvl() ? 'full' : (gate.ok ? 'ok' : 'confirm'));
  const saved = addLesson({
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
      ...(aborted ? { aborted: true } : {}),
    },
  });
  // 0.9.8 (Z-17): slow day – the whole lesson against the long-term reaction (fatigue present from the start is otherwise unseen)
  const pace = lessonPace(L.drill.trials.slice(L.warm?.n ?? 0), fatigueRef(L.prior)); // after the warm-up, newest char by its own ref
  // 0.10.11: written before traceEnd – after it tr() is a no-op (pace and pwEnd were lost in 0.9.8–0.10.10)
  if (pace !== null) tr('pace', Math.round(pace * 1000));
  const pwMax = L.paceWatch?.max;
  if (pwMax && pwMax.med !== null) tr('pwEnd', [L.paceWatch.events.length, Math.round(pwMax.med * 1000), pwMax.lapses]);
  traceEnd(saved.id, { trials: sum.trials, acc: sum.accuracy, ttr: sum.medianTtr, adv, activeS: Math.round(L.activeMs / 1000) });
  let verdict;
  const rec = a.recent === null ? null : Math.round(a.recent * 100);
  const nc = a.newChar || '';
  if (aborted) {
    verdict = t('verdict.aborted');
  } else if (adv === 'confirm') {
    verdict = t('verdict.confirm', { pct: rec, ch: nc, h: Math.max(0.5, gate.waitH) });
  } else if (a.ok && levelBefore < maxLvl()) {
    progress.level = levelBefore + 1;
    verdict = t('verdict.advance', { pct: rec, n: ADVANCE_WINDOW, ch: KOCH_ORDER[progress.level - 1] });
  } else if (a.ok) {
    verdict = t('verdict.full', { pct: rec });
  } else if (a.reason === 'few') {
    verdict = t('verdict.few', { n: ADVANCE_WINDOW, trials: sum.trials });
  } else if (a.reason === 'acc') {
    verdict = t('verdict.acc', { need: Math.round(ADVANCE_ACCURACY * 100), n: ADVANCE_WINDOW, pct: rec });
  } else if (a.reason === 'ttrUnstable') {
    verdict = t('verdict.ttrUnstable', { pct: rec, slower: Math.round((a.ttrRatio - 1) * 100) });
  } else if (a.reason === 'newFew') {
    verdict = t('verdict.newFew', { pct: rec, ch: nc, n: a.newN, need: NEW_MIN_N });
  } else if (a.reason === 'newAcc') {
    verdict = t('verdict.newAcc', { pct: rec, ch: nc, acc: Math.round(a.newAcc * 100), need: Math.round(NEW_ACCURACY * 100) });
  } else {
    verdict = t('verdict.newSlow', { pct: rec, ch: nc, ttr: a.newTtr, others: a.othersTtr });
  }
  saveProgress();

  $('#rs-acc').textContent = pct(sum.accuracy);
  $('#rs-ttr').textContent = sum.medianTtr !== null ? `${sum.medianTtr} ms` : '–';
  $('#rs-n').textContent = sum.trials;
  const fat = fatigueNote(L.drill.trials);
  // M6: pace within the lesson
  const notes = [verdict];
  if (fat) notes.push(fat);
  if (sum.gapLog.length) notes.push(t('result.gapEase'));
  if (!aborted && pace !== null && pace >= SLOW_DAY) notes.push(t('result.slowDay', { pct: Math.round((pace - 1) * 100) }));
  if (flu) {
    notes.push(flu.ttr ? t('result.fluencyTtr', { pct: Math.round(flu.acc * 100), wpm: flu.wpm, fwpm: flu.fwpm, ttr: flu.ttr })
      : t('result.fluency', { pct: Math.round(flu.acc * 100), wpm: flu.wpm, fwpm: flu.fwpm }));
  }
  $('#rs-verdict').textContent = notes.join(' ');
  const ld = currentLoad();
  const rl = $('#rs-load');
  rl.hidden = false;
  rl.className = ld.suggestEnd || ld.dayWarn ? 'hint warn' : 'hint';
  let wu = '';
  if (warmup) {
    const gap = warmup.gapH == null ? ''
      : warmup.gapH >= 24 ? t('result.afterDays', { n: Math.round(warmup.gapH / 24) }) : t('result.afterHours', { h: warmup.gapH });
    const drop = prevAcc != null && warmup.acc < prevAcc - 0.03;
    wu = t('result.warmup', { pct: Math.round(warmup.acc * 100), n: warmup.n, gap })
      + (prevAcc != null ? t('result.warmupPrev', { pct: Math.round(prevAcc * 100) }) : '')
      + (drop ? t('result.warmupDrop') : t('result.warmupOk'));
  }
  rl.textContent = wu + (ld.dayWarn
    ? t('result.loadDayWarn', { min: fmtMin(ld.dayMin), max: DAY_WARN_MIN })
    : ld.suggestEnd
      ? t('result.loadSessionEnd', { min: fmtMin(ld.sessionMin), max: SESSION_END_MIN })
      : t('result.loadSession', { min: fmtMin(ld.sessionMin) }));

  const rows = sum.perChar.filter((r) => r.n > 0)
    .sort((x, y) => (x.acc - y.acc) || ((y.ttr || 0) - (x.ttr || 0)));
  const tb = $('#rs-perchar');
  tb.textContent = '';
  for (const r of rows) {
    const row = document.createElement('tr');
    const arrow = trendArrow(r, L.prior[r.ch]);
    for (const txt of [r.ch, r.n, pct(r.acc), r.ttr !== null ? `${r.ttr} ms` : '–', ARROWS[arrow] || '']) {
      const td = document.createElement('td'); td.textContent = txt; row.append(td);
    }
    if (arrow) { row.lastChild.className = `arrow ${arrow}`; row.lastChild.title = t(`result.trend.${arrow}`); }
    if (r.acc < 0.9) row.className = 'weak';
    tb.append(row);
  }
  $('#rs-conf').textContent = sum.confusions.length
    ? t('result.confusions', { list: sum.confusions.slice(0, 5).map((c) => `${c.pair} ${c.n}×`).join(', ') })
    : t('result.noConfusions');
  show('result');
}

// ================= STATISTICS =================
function drawStats() {
  renderDashboard($('#dash-root'), coachInfo.data?.dashboard || null);
  renderStats($('#stats-root'), {
    stats, level: lvl(), of: maxLvl(),
    onPlay: async (ch) => { if (await ensureAudio()) player.play(ch); },
  });
  vocab.renderStats($('#vocab-stats')); // 0.10.0
}

// ================= SETTINGS =================
const steppers = [];
const target = (d) => (d.target === 'progress' ? progress : settings);

function renderSteppers() {
  for (const { el, out, minus, plus } of steppers) {
    const d = el.dataset;
    const v = target(d)[d.key];
    out.textContent = Math.round(v * Number(d.scale || 1)) + (d.unitKey ? t(d.unitKey) : d.unit);
    minus.disabled = v <= Number(d.min) + 1e-9;
    plus.disabled = v >= Number(d.max) - 1e-9 || (d.key === 'fwpm' && v >= settings.wpm)
      || (d.key === 'sendChars' && v >= maxLvl());
  }
  $('#send-chars-list').textContent = `(${charsForLevel(sendLvl()).join(' ')})`;
  $('#wpm-warn').hidden = settings.wpm >= 15;
  $('#auto-speed').checked = settings.autoSpeed !== 0;
  $('#extra-chars').checked = settings.extraChars === 1;
  for (const sel of document.querySelectorAll('.lang-select')) sel.value = lang;
  renderTheme();
}
$('#auto-speed').addEventListener('change', (e) => {
  settings.autoSpeed = e.target.checked ? 1 : 0;
  saveSettings();
});
$('#extra-chars').addEventListener('change', (e) => { // 0.9.6: optional extension (rare punctuation)
  settings.extraChars = e.target.checked ? 1 : 0;
  saveSettings();
  renderHome();
});

function initSteppers() {
  for (const el of document.querySelectorAll('.stepper[data-key]')) { // the key page has its own (keyerui.js)
    const d = el.dataset;
    const mk = (txt, label, dir) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'st-btn'; b.textContent = txt; b.setAttribute('aria-label', label);
      b.addEventListener('click', () => {
        const obj = target(d);
        const step = Number(d.step);
        let v = Math.round((obj[d.key] + dir * step) / step) * step;
        obj[d.key] = Math.min(Number(d.max), Math.max(Number(d.min), Number(v.toFixed(3))));
        if (settings.fwpm > settings.wpm) settings.fwpm = settings.wpm; // gaps must not be faster than the character
        if (d.target === 'progress') saveProgress(); else saveSettings();
        renderSteppers();
        if (d.key.startsWith('send')) keyUi.refresh();
      });
      return b;
    };
    const minus = mk('−', t('settings.decrease'), -1);
    const out = document.createElement('output');
    const plus = mk('+', t('settings.increase'), +1);
    el.append(minus, out, plus);
    steppers.push({ el, out, minus, plus });
  }
}

// ---- 1.0.2: Settings topics – one open at a time (also where <details name> is not supported) ----
for (const d of document.querySelectorAll('#view-settings details.set-sec')) {
  d.addEventListener('toggle', () => {
    if (!d.open) return;
    for (const x of document.querySelectorAll('#view-settings details.set-sec')) if (x !== d) x.open = false;
  });
}

// ---- 1.0.2: appearance – light / dark / by the system / by day and night; this device only (js/theme.js) ----
const fmtClock = (m) => { const r = Math.round(m); return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`; };
function renderTheme() {
  const th = window.morseTheme;
  const sel = $('#theme-select');
  if (!th || !sel) return;
  if (!sel.options.length) for (const m of th.MODES) sel.add(new Option(t(`settings.theme.${m}`), m));
  else for (const o of sel.options) o.text = t(`settings.theme.${o.value}`);
  sel.value = th.get();
  const now = new Date();
  const s = th.sunTimes(now);
  $('#theme-hint').textContent = sel.value === 'sun'
    ? t('settings.themeHint.sun', { rise: fmtClock(s.rise), set: fmtClock(s.set) })
    : t(`settings.themeHint.${sel.value}`);
}
$('#theme-select')?.addEventListener('change', (e) => { window.morseTheme?.set(e.target.value); renderTheme(); });

// ---- language (I18N): login page and Settings; stored locally and, when logged in, in the account settings ----
function initLangSelects() {
  for (const sel of document.querySelectorAll('.lang-select')) {
    for (const l of LANGUAGES) sel.add(new Option(l.name, l.code, false, l.code === lang));
    sel.addEventListener('change', () => {
      if (session.user && session.user.role !== 'admin') { settings.lang = sel.value; saveSettings(); }
      setLang(sel.value);
    });
  }
}
// The language chosen on another device (account settings) wins over the local one – applied after a sync.
function applyAccountLang() {
  if (session.langPinned) return;
  if (settings.lang && settings.lang !== lang && !sync.dirtySettings && LANGUAGES.some((l) => l.code === settings.lang)) {
    setLang(settings.lang);
  }
}

$('#play-k').addEventListener('click', async () => { if (await ensureAudio()) player.play('K'); });
$('#play-paris').addEventListener('click', async () => { if (await ensureAudio()) player.play('PARIS PARIS'); });

// ================= diagnostics and installation =================
let installEvt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault(); installEvt = e; $('#install').hidden = false; $('#install-hint').hidden = true;
});
window.addEventListener('appinstalled', () => { $('#install').hidden = true; });
$('#install').addEventListener('click', () => { if (installEvt) { installEvt.prompt(); installEvt = null; $('#install').hidden = true; } });

async function refreshDiag() {
  const lat = player.latencyInfo();
  let ver = '?';
  try { ver = (await (await fetch('/api/health')).json()).version; } catch (e) { ver = t('diag.serverDown'); }
  const standalone = matchMedia('(display-mode: standalone)').matches;
  $('#install-hint').hidden = standalone || !!installEvt; // 0.14.4: no install offer (e.g. Family Link) → how to
  const yes = t('diag.yes');
  const rows = [
    [t('diag.version'), ver],
    ['HTTPS', window.isSecureContext ? yes : t('diag.NO')],
    [t('diag.standalone'), standalone ? yes : t('diag.inBrowser')],
    ['Wake Lock', 'wakeLock' in navigator ? yes : t('diag.no')],
    [t('diag.audio'), player.ctx ? player.ctx.state : t('diag.audioOff')],
    [t('diag.latency'), lat ? t('diag.latencyVal', { base: lat.base, output: lat.output }) : t('diag.latencyNone')],
    [t('diag.lessons'), String(progress.history.length)],
    [t('diag.outbox'), String(sync.outbox.length)],
    [t('diag.device'), deviceKind() === DEVICE_MOBILE ? t('diag.mobile') : 'PC'],
    [t('diag.address'), isPublic() ? t('site.public') : t('site.home')],
  ];
  const tb = $('#diag');
  tb.textContent = '';
  for (const [k, v] of rows) {
    const row = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = k;
    const td = document.createElement('td'); td.textContent = v;
    row.append(th, td); tb.append(row);
  }
}

// ================= start =================
initSteppers();
initLangSelects();
{ // 0.8.2: link to the other version of the app (home ↔ outside) in Diagnostics
  const o = otherSite();
  const a = $('#other-site');
  if (o) { a.href = o.url; a.textContent = `${o.label} (${o.name})`; } else a.hidden = true;
  if (isPublic()) document.title = t('app.titlePublic');
  $('#login-ca').hidden = isPublic() || matchMedia('(display-mode: standalone)').matches; // Z-27 A (0.17.2): home CA only in the LAN browser
}
if ('serviceWorker' in navigator && window.isSecureContext) {
  // 0.9.7 (Z-08): app files come from the cache → a new version takes over in the background; reload once it is active,
  // but never in the middle of a lesson (then at the next return to Home). First install = no previous controller.
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || updateReload.done) return;
    updateReload.pending = true;
    if (UPDATE_SAFE_VIEWS.includes(view)) reloadForUpdate();
  });
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// Data from the server (another device) – redraw, but never in the middle of a lesson.
onDataChange(() => {
  if (['home', 'settings', 'account', 'stats', 'result', 'copyhome', 'copyresult', 'headresult'].includes(view)) applyAccountLang();
  if (view === 'home') renderHome();
  else if (view === 'copyhome') renderCopyCard();
  else if (view === 'settings') renderSteppers();
  else if (view === 'account') renderAccount();
  else if (view === 'stats') drawStats();
});
// Back in the app (phone ↔ PC) → fetch news.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && ['home', 'settings', 'account', 'result', 'stats', 'copyresult'].includes(view)) backgroundSync();
  if (document.visibilityState === 'hidden' && view === 'copy') copyCtl.hold(); // the stream must not run into the void
  if (document.visibilityState === 'hidden' && view === 'head') headCtl.hold();
  if (document.visibilityState === 'hidden' && view === 'entry') entryCtl.hold();
  if (document.visibilityState === 'hidden' && view === 'demo') { demo.stop(); demoBand.stop(); }
  if (document.visibilityState === 'hidden' && view === 'band') bandLab.stop();
  if (document.visibilityState === 'hidden' && view === 'key') keyUi.stop(); // release paddles, silence
  if (document.visibilityState === 'visible' && view === 'key') keyUi.render();
  player.keepAlive(document.visibilityState === 'visible' && ['lesson', 'intro', 'discrim', 'copy', 'head', 'entry', 'key', 'cw'].includes(view));
});
window.addEventListener('online', () => { backgroundSync(); vocab.flush(); });
// 0.9.7 (Z-06): closing/reloading the page in the middle of a lesson – keep it as an aborted lesson (sent with the next sync)
setBeforeHide(() => {
  if (L.running) finishLesson(true);
  else if (copyCtl.running) copyCtl.abort();
  else if (headCtl.running) headCtl.abort();
});

startAuth(show).then((ok) => { if (ok) { applyAccountLang(); show(restoredView('home')); } });
