// SPDX-License-Identifier: EUPL-1.2
// M2 – login, registration from an invitation, the Account tab (management of users moved to usersui.js in 0.13.0).
import { t, fmtDate as fmtDateL, lang } from './i18n.js';
import { otherSite } from './site.js';
import { api, setCsrf, deviceKind, ApiError, setBusyEndHandler } from './api.js';
import { bindPasswordRules } from './pwrules.js';
import { setTraceUser } from './trace.js';
import { showNews } from './news.js';
import { startOnline, stopOnline } from './online.js';
import {
  progress, settings, sync, cachedUser, rememberUser, openUser, forgetUser, syncNow, saveSettings, resetTraining,
} from './storage.js';

const $ = (s) => document.querySelector(s);
// Roles and age groups are stored values (DB, API) – only their names are translated.
export const ROLE_ADMIN = 'admin';
export const ROLE_COACH = 'trener';
export const ROLE_STUDENT = 'zak';
const ROLES = [ROLE_STUDENT, ROLE_COACH, ROLE_ADMIN];
const AGE_UNDER_15 = 'do15';
const roleName = (r) => (ROLES.includes(r) ? t(`role.${r}`) : r);
const ageName = (a) => (a ? t(`age.${a}`) : t('age.unknown'));
// Link hashes (stored in already sent links): Czech originals and English aliases are both accepted.
const INVITE_HASH = /(?:pozvanka|invite)=([\w-]{20,64})/;
const RESET_HASH = /(?:heslo|reset)=([\w-]{20,64})/;

// langPinned: during an explicit login the language just used wins over the account setting (see loggedIn)
export const session = { user: null, offline: false, langPinned: false };
let show = () => {};
let inviteToken = null;
let resetToken = null; // E3: new-password link (#heslo=… / #reset=…)

export function banner(text, warn = false) {
  const b = $('#banner');
  b.textContent = text || '';
  b.className = warn ? 'banner warn' : 'banner';
  b.hidden = !text;
}

const fmtDate = (iso) => (iso ? fmtDateL(iso, {
  day: 'numeric', month: 'numeric', year: '2-digit', hour: '2-digit', minute: '2-digit',
}) : '–');

function formError(form, msg) { form.querySelector('.form-error').textContent = msg || ''; }
function busy(form, on) { for (const b of form.querySelectorAll('button')) b.disabled = on; }

// 0.9.4: 429 (rate limit) or a server error is not "logged out" – retry a moment later (validation #9)
const transient = (e) => e instanceof ApiError && (e.status === 429 || e.status >= 500);
async function getMe() {
  for (let i = 0; ; i++) {
    try {
      return await api('GET', '/me');
    } catch (e) {
      if (!transient(e) || e.busy || i >= 2) throw e; // full server: wait (api.js), no quick retries
      await new Promise((r) => { setTimeout(r, 1500 * (i + 1)); });
    }
  }
}

// ================= start =================
/** Finds out the login state. Returns true if training is possible (online, or offline from the cache). */
export async function startAuth(showFn) {
  show = showFn;
  const m = location.hash.match(INVITE_HASH);
  const r = location.hash.match(RESET_HASH);
  if (m) inviteToken = m[1];
  if (r) resetToken = r[1];
  if (m || r) history.replaceState(null, '', location.pathname); // do not leave the token in the address bar or history
  if (resetToken) { openReset(); return false; } // E3: a new-password link applies even when logged in (new password = new login)
  try {
    const me = await getMe();
    if (inviteToken) {
      banner(t('auth.inviteWhileLoggedIn', { nick: me.user.nick }), true);
      inviteToken = null;
    }
    await loggedIn(me.user, me.csrf);
    return true;
  } catch (e) {
    if (e instanceof ApiError && (e.offline || transient(e))) {
      const u = cachedUser();
      if (u && !inviteToken && !resetToken) {
        session.user = u; session.offline = true;
        setTraceUser(u);
        sync.canTrain = u.role !== ROLE_ADMIN;
        openUser(u.id);
        setNick(u.nick);
        // Z-19: a full server says so itself ("full, keep training…"), otherwise the general text
        banner(e.offline ? t('auth.offline') : (e.busy && e.status === 503 ? e.message : t('auth.serverBusy', { msg: e.message })), true);
        const o = otherSite(); // 0.8.2: away from home offer the outside version (and vice versa)
        if (o) {
          const a = document.createElement('a');
          a.href = o.url; a.rel = 'noopener'; a.textContent = ` ${o.label} →`;
          $('#banner').append(a);
        }
        return true;
      }
      banner(e.message, true);
    }
    if (resetToken) openReset(); else if (inviteToken) openRegister(); else show('login');
    return false;
  }
}

/** explicit = the user has just logged in / registered / set a password here (not a restored session). */
async function loggedIn(user, csrf, fresh = false, explicit = false) {
  setCsrf(csrf);
  session.user = user; session.offline = false;
  const prev = cachedUser();
  if (prev && prev.id !== user.id) { openUser(prev.id); forgetUser(); } // another user was on this device
  rememberUser(user);
  setTraceUser(user); // V1: debug trace only for accounts with tracing enabled
  sync.canTrain = user.role !== ROLE_ADMIN; // the administrator only manages, does not train
  openUser(user.id);
  setNick(user.nick);
  if (user.pw_change) return; // E3: new password first (show() only allows view-pwchange), sync afterwards
  session.langPinned = explicit;
  try {
    const imported = await syncNow();
    // I18N: the language used for logging in becomes the account language (synchronized to other devices)
    if (explicit && sync.canTrain && settings.lang !== lang) { settings.lang = lang; saveSettings(); }
    if (imported) banner(t('auth.imported', { n: imported.lessons, level: imported.level }));
    else if (fresh) banner(user.role === ROLE_ADMIN ? t('auth.welcomeAdmin', { nick: user.nick }) : t('auth.welcome', { nick: user.nick }));
  } catch (e) {
    banner(t('sync.failed', { msg: e.message }), true);
  } finally {
    session.langPinned = false;
  }
  whatsNew();
}

/** 0.9.3: one-off overview of new features (online only, after a forced password change). */
function whatsNew() {
  const u = session.user;
  if (!u || session.offline || u.pw_change) return;
  showNews(u, (id) => {
    if (session.user?.id !== u.id) return;
    session.user = { ...session.user, news_seen: Math.max(Number(session.user.news_seen) || 0, id) };
    rememberUser(session.user);
  });
}

/** Call on an error with e.auth – the login expired or was revoked from another device. */
export function sessionExpired() {
  session.user = null;
  banner(t('auth.expired'), true);
  show('login');
}

/** After an offline start: verify the session and get a CSRF token, then sync. */
async function syncOnline() {
  if (session.offline) {
    const me = await getMe();
    if (me.user.id !== session.user.id) throw Object.assign(new Error(t('auth.otherUser')), { status: 403, auth: true });
    setCsrf(me.csrf);
    session.user = me.user;
    session.offline = false;
    banner('');
    if (me.user.pw_change) { show('pwchange'); return null; } // E3: forced password change
    whatsNew();
  }
  return syncNow();
}

/** Background sync (back in the app, network restored) – errors are only recorded quietly. */
export async function backgroundSync() {
  if (!session.user || session.user.pw_change) return;
  try {
    await syncOnline();
  } catch (e) {
    if (e.auth) sessionExpired();
  }
}
// Z-19: after the wait for a full server one attempt (refused again → api.js waits longer)
setBusyEndHandler(() => { backgroundSync(); });

// ================= login =================
$('#form-login').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  busy(f, true);
  try {
    const r = await api('POST', '/login', { nick: f.nick.value.trim(), password: f.password.value, device: deviceKind() });
    f.password.value = '';
    banner('');
    await loggedIn(r.user, r.csrf, false, true);
    show('home');
  } catch (err) {
    formError(f, err.message);
  } finally { busy(f, false); }
});

// ================= registration =================
async function openRegister() {
  const f = $('#form-register');
  show('register');
  busy(f, true);
  try {
    const r = await api('POST', '/invite/check', { token: inviteToken });
    $('#reg-info').textContent = t('register.info', { role: roleName(r.role), until: fmtDate(r.expires_at) });
    busy(f, false);
  } catch (err) {
    $('#reg-info').textContent = '';
    if (err.status === 404 || err.status === 409) {
      formError(f, `${err.message} ${t('register.askNew')}`);
      inviteToken = null;
    } else {
      // 0.9.4: network / limit / rejected request – the invitation may be fine, keep it and offer a retry (validation #10)
      formError(f, `${err.message} ${t('register.tryAgain')}`);
      const b = $('#reg-retry');
      b.hidden = false;
      b.disabled = false;
    }
  }
}
$('#reg-retry').addEventListener('click', () => { $('#reg-retry').hidden = true; formError($('#form-register'), ''); openRegister(); });

const regValid = bindPasswordRules($('#form-register').password, $('#form-register').password2,
  () => $('#form-register').nick.value.trim());
$('#form-register').nick.addEventListener('input', regValid);

$('#form-register').age_group.addEventListener('change', (e) => {
  $('#reg-consent').hidden = e.target.value !== AGE_UNDER_15;
});

$('#form-register').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!regValid()) { formError(f, t('pw.notYet')); return; }
  if (f.age_group.value === AGE_UNDER_15 && !f.parent_consent.checked) { formError(f, t('register.consentNeeded')); return; }
  busy(f, true);
  try {
    const r = await api('POST', '/register', {
      token: inviteToken, nick: f.nick.value.trim(), password: f.password.value,
      age_group: f.age_group.value || null, parent_consent: f.parent_consent.checked, device: deviceKind(),
    });
    inviteToken = null;
    f.reset();
    await loggedIn(r.user, r.csrf, true, true);
    show('home');
  } catch (err) {
    formError(f, err.message);
    busy(f, false);
  }
});

// ================= Account tab =================
export function renderAccount() {
  const u = session.user;
  if (!u) return;
  const rows = [
    [t('form.nick'), u.nick],
    [t('invite.role'), roleName(u.role)],
    [t('register.age'), ageName(u.age_group)],
    [t('account.lastSync'), session.offline ? t('account.offline') : (sync.error ? t('account.syncError', { msg: sync.error }) : fmtDate(sync.lastSync))],
    [t('diag.outbox'), String(sync.outbox.length)],
    [t('account.lessonsTotal'), String(progress.history.length)],
  ];
  const tb = $('#acc-info');
  tb.textContent = '';
  for (const [k, v] of rows) {
    const row = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = k;
    const td = document.createElement('td'); td.textContent = v;
    row.append(th, td); tb.append(row);
  }
  $('#acc-training').hidden = u.role === ROLE_ADMIN || session.offline;
}

$('#acc-sync').addEventListener('click', async () => {
  try {
    await syncOnline();
  } catch (e) {
    if (e.auth) { sessionExpired(); return; }
    banner(t('sync.failed', { msg: e.message }), true);
  }
  renderAccount();
});

const pwValid = bindPasswordRules($('#form-password').new, $('#form-password').new2, () => session.user?.nick || '');

$('#form-password').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!pwValid()) { formError(f, t('pw.newNotYet')); return; }
  busy(f, true);
  try {
    await api('POST', '/password', { old: f.old.value, new: f.new.value });
    f.reset();
    banner(t('pw.changed'));
    window.scrollTo(0, 0);
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});

// ================= E3: forced password change =================
const pwcValid = bindPasswordRules($('#form-pwchange').new, $('#form-pwchange').new2, () => session.user?.nick || '');

$('#form-pwchange').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!pwcValid()) { formError(f, t('pw.newNotYet')); return; }
  busy(f, true);
  try {
    await api('POST', '/password', { old: f.old.value, new: f.new.value });
    f.reset();
    session.user = { ...session.user, pw_change: false };
    rememberUser(session.user);
    banner(t('pw.changed'));
    try { await syncNow(); } catch (err) { banner(t('sync.failed', { msg: err.message }), true); }
    show('home');
    whatsNew();
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});
$('#pwchange-logout').addEventListener('click', () => $('#acc-logout').click());

// ================= E3: new password from a link (forgotten password) =================
let resetNick = '';
const resetValid = bindPasswordRules($('#form-reset').password, $('#form-reset').password2, () => resetNick);

async function openReset() {
  const f = $('#form-reset');
  show('reset');
  busy(f, true);
  try {
    const r = await api('POST', '/invite/check', { token: resetToken });
    if (!r.reset) throw new Error(t('reset.isInvite'));
    resetNick = r.reset;
    $('#reset-info').textContent = t('reset.info', { nick: r.reset, until: fmtDate(r.expires_at) });
    resetValid();
    busy(f, false);
  } catch (err) {
    $('#reset-info').textContent = '';
    formError(f, `${err.message} ${t('reset.askNew')}`);
    resetToken = null;
  }
}

$('#form-reset').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!resetValid()) { formError(f, t('pw.notYet')); return; }
  busy(f, true);
  try {
    const r = await api('POST', '/password/reset', { token: resetToken, password: f.password.value, device: deviceKind() });
    resetToken = null;
    f.reset();
    await loggedIn(r.user, r.csrf, false, true);
    banner(t('reset.done'));
    show('home');
  } catch (err) {
    formError(f, err.message);
    busy(f, false);
  }
});

/** 0.8.6: nickname in the user menu and its initial in the icon. */
function setNick(nick) {
  $('#tab-account').textContent = nick || t('nav.account');
  $('#user-initial').textContent = nick ? [...nick][0].toUpperCase() : '?';
  $('#user-btn').title = nick ? t('nav.userTitle', { nick }) : t('nav.accountSettings');
  if (nick) startOnline(); else stopOnline();
}

function signedOut(msg) {
  forgetUser();
  session.user = null;
  setCsrf('');
  setNick(null);
  banner(msg);
  show('login');
}

async function logout(all) {
  if (sync.outbox.length) {
    try { await syncNow(); } catch (e) { /* checked below */ }
    if (sync.outbox.length && !confirm(t('logout.unsent', { n: sync.outbox.length }))) return;
  }
  try { await api('POST', all ? '/logout-all' : '/logout'); } catch (e) { /* log out locally anyway */ }
  signedOut(all ? t('logout.all') : t('logout.done'));
}
$('#acc-logout').addEventListener('click', () => logout(false));
$('#acc-logout-all').addEventListener('click', () => logout(true));

$('#acc-delete').addEventListener('click', async () => {
  if (!confirm(t('account.deleteConfirm'))) return;
  const pw = prompt(t('account.passwordPrompt'));
  if (!pw) return;
  try {
    await api('POST', '/account/delete', { password: pw });
    signedOut(t('account.deleted'));
  } catch (e) { alert(e.message); }
});

$('#acc-reset').addEventListener('click', async () => {
  if (!confirm(t('account.resetConfirm'))) return;
  const pw = prompt(t('account.passwordPrompt'));
  if (!pw) return;
  try {
    await resetTraining(pw);
    banner(t('account.resetDone'));
    renderAccount();
    window.scrollTo(0, 0);
  } catch (e) { alert(e.message); }
});
