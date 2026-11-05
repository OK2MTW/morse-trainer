// SPDX-License-Identifier: EUPL-1.2
// M2 – přihlášení, registrace z pozvánky, karta Účet, správa pozvánek a uživatelů.
import { otherSite } from './site.js';
import { api, setCsrf, deviceKind, ApiError } from './api.js';
import { bindPasswordRules } from './pwrules.js';
import {
  progress, sync, cachedUser, rememberUser, openUser, forgetUser, syncNow, resetTraining,
} from './storage.js';

const $ = (s) => document.querySelector(s);
const ROLE_NAMES = { admin: 'správce', trener: 'trenér', zak: 'žák' };
const AGE_NAMES = { do15: 'do 15 let', '15-17': '15–17 let', '18-59': '18–59 let', '60+': '60 a více' };

export const session = { user: null, offline: false };
let show = () => {};
let inviteToken = null;
let resetToken = null; // E3: odkaz pro nové heslo (#heslo=…)

export function banner(text, warn = false) {
  const b = $('#banner');
  b.textContent = text || '';
  b.className = warn ? 'banner warn' : 'banner';
  b.hidden = !text;
}

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString('cs-CZ', {
  day: 'numeric', month: 'numeric', year: '2-digit', hour: '2-digit', minute: '2-digit',
}) : '–');

function formError(form, msg) { form.querySelector('.form-error').textContent = msg || ''; }
function busy(form, on) { for (const b of form.querySelectorAll('button')) b.disabled = on; }

// ================= start =================
/** Zjistí přihlášení. Vrací true, pokud lze trénovat (online, nebo offline z cache). */
export async function startAuth(showFn) {
  show = showFn;
  const m = location.hash.match(/pozvanka=([\w-]{20,64})/);
  const r = location.hash.match(/heslo=([\w-]{20,64})/);
  if (m) inviteToken = m[1];
  if (r) resetToken = r[1];
  if (m || r) history.replaceState(null, '', location.pathname); // token nenechávat v adrese ani historii
  if (resetToken) { openReset(); return false; } // E3: odkaz na nové heslo platí i při přihlášení (nové heslo = nové přihlášení)
  try {
    const me = await api('GET', '/me');
    if (inviteToken) {
      banner(`Jsi přihlášený jako ${me.user.nick}. Pozvánku otevři v jiném prohlížeči, nebo se nejdřív odhlas.`, true);
      inviteToken = null;
    }
    await loggedIn(me.user, me.csrf);
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.offline) {
      const u = cachedUser();
      if (u && !inviteToken && !resetToken) {
        session.user = u; session.offline = true;
        sync.canTrain = u.role !== 'admin';
        openUser(u.id);
        setNick(u.nick);
        banner('Server je nedostupný – trénuješ offline, výsledky se odešlou později.', true);
        const o = otherSite(); // 0.8.2: mimo domov nabídnout venkovní verzi (a naopak)
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

async function loggedIn(user, csrf, fresh = false) {
  setCsrf(csrf);
  session.user = user; session.offline = false;
  const prev = cachedUser();
  if (prev && prev.id !== user.id) { openUser(prev.id); forgetUser(); } // na zařízení byl jiný uživatel
  rememberUser(user);
  sync.canTrain = user.role !== 'admin'; // správce jen spravuje, netrénuje
  openUser(user.id);
  setNick(user.nick);
  if (user.pw_change) return; // E3: nejdřív nové heslo (show() pustí jen na view-pwchange), synchronizace až potom
  try {
    const imported = await syncNow();
    if (imported) banner(`Data z tohoto zařízení (${imported.lessons} lekcí, ${imported.level} znaků) jsou teď v tvém účtu.`);
    else if (fresh) banner(user.role === 'admin' ? `Vítej, ${user.nick}! Jako správce zveš uživatele a spravuješ účty.`
      : `Vítej, ${user.nick}! Začni první lekcí.`);
  } catch (e) {
    banner(`Synchronizace se nepovedla: ${e.message}`, true);
  }
}

/** Volat při chybě s e.auth – přihlášení vypršelo nebo bylo zrušeno z jiného zařízení. */
export function sessionExpired() {
  session.user = null;
  banner('Přihlášení vypršelo, přihlas se znovu.', true);
  show('login');
}

/** Po offline startu: ověřit session a získat CSRF token, pak synchronizovat. */
async function syncOnline() {
  if (session.offline) {
    const me = await api('GET', '/me');
    if (me.user.id !== session.user.id) throw Object.assign(new Error('Jiný uživatel'), { status: 403, auth: true });
    setCsrf(me.csrf);
    session.user = me.user;
    session.offline = false;
    banner('');
    if (me.user.pw_change) { show('pwchange'); return null; } // E3: vynucená změna hesla
  }
  return syncNow();
}

/** Synchronizace na pozadí (návrat do aplikace, obnova sítě) – chyby jen tiše zaznamená. */
export async function backgroundSync() {
  if (!session.user || session.user.pw_change) return;
  try {
    await syncOnline();
  } catch (e) {
    if (e.auth) sessionExpired();
  }
}

// ================= přihlášení =================
$('#form-login').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  busy(f, true);
  try {
    const r = await api('POST', '/login', { nick: f.nick.value.trim(), password: f.password.value, device: deviceKind() });
    f.password.value = '';
    banner('');
    await loggedIn(r.user, r.csrf);
    show('home');
  } catch (err) {
    formError(f, err.message);
  } finally { busy(f, false); }
});

// ================= registrace =================
async function openRegister() {
  const f = $('#form-register');
  show('register');
  busy(f, true);
  try {
    const r = await api('POST', '/invite/check', { token: inviteToken });
    $('#reg-info').textContent = `Pozvánka pro roli „${ROLE_NAMES[r.role]}“, platí do ${fmtDate(r.expires_at)}.`;
    busy(f, false);
  } catch (err) {
    $('#reg-info').textContent = '';
    formError(f, `${err.message} Požádej o novou pozvánku.`);
    inviteToken = null;
  }
}

const regValid = bindPasswordRules($('#form-register').password, $('#form-register').password2,
  () => $('#form-register').nick.value.trim());
$('#form-register').nick.addEventListener('input', regValid);

$('#form-register').age_group.addEventListener('change', (e) => {
  $('#reg-consent').hidden = e.target.value !== 'do15';
});

$('#form-register').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!regValid()) { formError(f, 'Heslo zatím nesplňuje všechna pravidla (✗ v seznamu).'); return; }
  if (f.age_group.value === 'do15' && !f.parent_consent.checked) { formError(f, 'U dětí do 15 let je potřeba souhlas rodiče.'); return; }
  busy(f, true);
  try {
    const r = await api('POST', '/register', {
      token: inviteToken, nick: f.nick.value.trim(), password: f.password.value,
      age_group: f.age_group.value || null, parent_consent: f.parent_consent.checked, device: deviceKind(),
    });
    inviteToken = null;
    f.reset();
    await loggedIn(r.user, r.csrf, true);
    show('home');
  } catch (err) {
    formError(f, err.message);
    busy(f, false);
  }
});

// ================= karta Účet =================
export function renderAccount() {
  const u = session.user;
  if (!u) return;
  const rows = [
    ['Přezdívka', u.nick],
    ['Role', ROLE_NAMES[u.role] || u.role],
    ['Věková skupina', AGE_NAMES[u.age_group] || 'neuvedena'],
    ['Poslední synchronizace', session.offline ? 'offline' : (sync.error ? `chyba: ${sync.error}` : fmtDate(sync.lastSync))],
    ['Neodeslané lekce', String(sync.outbox.length)],
    ['Lekcí celkem', String(progress.history.length)],
  ];
  const tb = $('#acc-info');
  tb.textContent = '';
  for (const [k, v] of rows) {
    const tr = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = k;
    const td = document.createElement('td'); td.textContent = v;
    tr.append(th, td); tb.append(tr);
  }
  $('#acc-training').hidden = u.role === 'admin' || session.offline;
  const staff = u.role === 'admin' || u.role === 'trener';
  $('#admin').hidden = !staff || session.offline;
  if (staff && !session.offline) {
    for (const o of $('#inv-role').options) o.hidden = u.role !== 'admin' && o.value !== 'zak';
    if (u.role !== 'admin') $('#inv-role').value = 'zak';
    $('#users-title').textContent = u.role === 'admin' ? 'Uživatelé' : 'Moji žáci';
    loadInvites();
    loadUsers();
  }
}

$('#acc-sync').addEventListener('click', async () => {
  try {
    await syncOnline();
  } catch (e) {
    if (e.auth) { sessionExpired(); return; }
    banner(`Synchronizace se nepovedla: ${e.message}`, true);
  }
  renderAccount();
});

const pwValid = bindPasswordRules($('#form-password').new, $('#form-password').new2, () => session.user?.nick || '');

$('#form-password').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!pwValid()) { formError(f, 'Nové heslo zatím nesplňuje všechna pravidla (✗ v seznamu).'); return; }
  busy(f, true);
  try {
    await api('POST', '/password', { old: f.old.value, new: f.new.value });
    f.reset();
    banner('Heslo změněno. Ostatní zařízení jsou odhlášená.');
    window.scrollTo(0, 0);
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});

// ================= E3: vynucená změna hesla =================
const pwcValid = bindPasswordRules($('#form-pwchange').new, $('#form-pwchange').new2, () => session.user?.nick || '');

$('#form-pwchange').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!pwcValid()) { formError(f, 'Nové heslo zatím nesplňuje všechna pravidla (✗ v seznamu).'); return; }
  busy(f, true);
  try {
    await api('POST', '/password', { old: f.old.value, new: f.new.value });
    f.reset();
    session.user = { ...session.user, pw_change: false };
    rememberUser(session.user);
    banner('Heslo změněno. Ostatní zařízení jsou odhlášená.');
    try { await syncNow(); } catch (err) { banner(`Synchronizace se nepovedla: ${err.message}`, true); }
    show('home');
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});
$('#pwchange-logout').addEventListener('click', () => $('#acc-logout').click());

// ================= E3: nové heslo z odkazu (zapomenuté heslo) =================
let resetNick = '';
const resetValid = bindPasswordRules($('#form-reset').password, $('#form-reset').password2, () => resetNick);

async function openReset() {
  const f = $('#form-reset');
  show('reset');
  busy(f, true);
  try {
    const r = await api('POST', '/invite/check', { token: resetToken });
    if (!r.reset) throw new Error('Tohle je pozvánka, ne odkaz pro nové heslo.');
    resetNick = r.reset;
    $('#reset-info').textContent = `Účet „${r.reset}“, odkaz platí do ${fmtDate(r.expires_at)}.`;
    resetValid();
    busy(f, false);
  } catch (err) {
    $('#reset-info').textContent = '';
    formError(f, `${err.message} Požádej o nový odkaz.`);
    resetToken = null;
  }
}

$('#form-reset').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  if (!resetValid()) { formError(f, 'Heslo zatím nesplňuje všechna pravidla (✗ v seznamu).'); return; }
  busy(f, true);
  try {
    const r = await api('POST', '/password/reset', { token: resetToken, password: f.password.value, device: deviceKind() });
    resetToken = null;
    f.reset();
    await loggedIn(r.user, r.csrf);
    banner('Nové heslo uloženo, jsi přihlášený.');
    show('home');
  } catch (err) {
    formError(f, err.message);
    busy(f, false);
  }
});

/** 0.8.6: přezdívka v menu uživatele a iniciála v ikoně. */
function setNick(nick) {
  $('#tab-account').textContent = nick || 'Účet';
  $('#user-initial').textContent = nick ? [...nick][0].toUpperCase() : '?';
  $('#user-btn').title = nick ? `${nick} – účet a nastavení` : 'Účet a nastavení';
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
    try { await syncNow(); } catch (e) { /* ověříme níže */ }
    if (sync.outbox.length && !confirm(`${sync.outbox.length} lekcí ještě není na serveru a odhlášením se ztratí. Přesto odhlásit?`)) return;
  }
  try { await api('POST', all ? '/logout-all' : '/logout'); } catch (e) { /* lokálně odhlásíme i tak */ }
  signedOut(all ? 'Odhlášeno na všech zařízeních.' : 'Odhlášeno.');
}
$('#acc-logout').addEventListener('click', () => logout(false));
$('#acc-logout-all').addEventListener('click', () => logout(true));

$('#acc-delete').addEventListener('click', async () => {
  if (!confirm('Opravdu smazat účet? Smaže se nastavení, pokrok i všechny lekce. Nejde to vrátit.\n\nTip: nejdřív si stáhni svoje data.')) return;
  const pw = prompt('Pro potvrzení zadej své heslo:');
  if (!pw) return;
  try {
    await api('POST', '/account/delete', { password: pw });
    signedOut('Účet a všechna data byla smazána.');
  } catch (e) { alert(e.message); }
});

$('#acc-reset').addEventListener('click', async () => {
  if (!confirm('Opravdu resetovat výcvik? Smažou se všechny lekce a pokrok na všech zařízeních a začneš od 2 znaků.')) return;
  const pw = prompt('Pro potvrzení zadej své heslo:');
  if (!pw) return;
  try {
    await resetTraining(pw);
    banner('Výcvik resetován – začínáš znovu od 2 znaků.');
    renderAccount();
    window.scrollTo(0, 0);
  } catch (e) { alert(e.message); }
});

// ================= pozvánky =================
$('#form-invite').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  busy(f, true);
  try {
    const r = await api('POST', '/invites', { role: $('#inv-role').value, note: f.note.value.trim() });
    $('#inv-link').value = `${location.origin}/#pozvanka=${r.token}`;
    $('#inv-hint').textContent = 'Odkaz platí 7 dní a jen jednou. Pošli ho pozvanému (např. zprávou):';
    $('#inv-result').hidden = false;
    $('#inv-share').hidden = !navigator.share;
    f.note.value = '';
    loadInvites();
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});

$('#inv-copy').addEventListener('click', async () => {
  const inp = $('#inv-link');
  try {
    await navigator.clipboard.writeText(inp.value);
    $('#inv-copy').textContent = 'Zkopírováno ✓';
  } catch (e) {
    inp.select(); // starší prohlížeč – označí text ke ručnímu zkopírování
  }
  setTimeout(() => { $('#inv-copy').textContent = 'Kopírovat'; }, 2000);
});
$('#inv-share').addEventListener('click', () => {
  navigator.share?.({ title: 'Pozvánka – Morse trenažer', text: 'Pozvánka do Morse trenažeru:', url: $('#inv-link').value })
    .catch(() => {});
});

function cell(tr, text, small) {
  const td = document.createElement('td');
  td.textContent = text;
  if (small) { const s = document.createElement('small'); s.textContent = small; td.append(s); }
  tr.append(td);
  return td;
}

function button(text, onClick) {
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

async function loadInvites() {
  const tb = $('#inv-list');
  try {
    const { invites } = await api('GET', '/invites');
    tb.textContent = '';
    if (!invites.length) { cell(tb.insertRow(), 'Zatím žádné pozvánky.'); return; }
    for (const i of invites) {
      const tr = tb.insertRow();
      cell(tr, `${ROLE_NAMES[i.role]}${i.note ? ` – ${i.note}` : ''}`, `vytvořena ${fmtDate(i.created_at)}`);
      cell(tr, i.state, i.used_by_nick ? `→ ${i.used_by_nick}` : (i.state === 'platná' ? `do ${fmtDate(i.expires_at)}` : ''));
      const td = cell(tr, '');
      if (i.state === 'platná') {
        td.append(button('Zrušit', async () => {
          try { await api('DELETE', `/invites/${i.id}`); } catch (e) { alert(e.message); }
          loadInvites();
        }));
      }
    }
  } catch (e) { tb.textContent = ''; cell(tb.insertRow(), e.message); }
}

async function loadUsers() {
  const tb = $('#users-list');
  try {
    const { users } = await api('GET', '/users');
    tb.textContent = '';
    if (!users.length) { cell(tb.insertRow(), 'Zatím nikdo.'); return; }
    const admin = session.user.role === 'admin';
    for (const u of users) {
      const tr = tb.insertRow();
      cell(tr, u.nick + (u.disabled ? ' (zablokován)' : ''), `${ROLE_NAMES[u.role]} · ${AGE_NAMES[u.age_group] || 'věk neuveden'}`);
      cell(tr, `${u.level || 2} zn. · ${u.lessons} lekcí`, `poslední ${fmtDate(u.last_lesson)}`);
      const td = cell(tr, '');
      if (u.id !== session.user.id) {
        td.append(button('Odkaz na nové heslo', async () => {
          if (!confirm(`Vytvořit pro ${u.nick} odkaz na nové heslo? Platí 3 dny, jen jednou; trénink zůstane.`)) return;
          try {
            const r = await api('POST', `/users/${u.id}/password-link`);
            $('#inv-link').value = `${location.origin}/#heslo=${r.token}`;
            $('#inv-hint').textContent = `Odkaz na nové heslo pro ${u.nick} platí 3 dny a jen jednou. Pošli ho jen jemu:`;
            $('#inv-result').hidden = false;
            $('#inv-share').hidden = !navigator.share;
            $('#inv-result').scrollIntoView({ block: 'center' });
            loadInvites();
          } catch (e) { alert(e.message); }
        }));
      }
      if (u.role !== 'admin' && u.lessons + (u.level ? 1 : 0) > 0) {
        td.append(button('Reset výcviku', async () => {
          if (!confirm(`Resetovat výcvik uživatele ${u.nick}? Smažou se jeho lekce a pokrok.`)) return;
          try { await api('POST', `/users/${u.id}/reset-training`); } catch (e) { alert(e.message); }
          loadUsers();
        }));
      }
      if (admin && u.id !== session.user.id) {
        const sel = document.createElement('select');
        for (const [v, t] of Object.entries(ROLE_NAMES)) sel.add(new Option(t, v, false, v === u.role));
        sel.addEventListener('change', () => patchUser(u.id, { role: sel.value }));
        td.append(sel, button(u.disabled ? 'Odblokovat' : 'Zablokovat', () => patchUser(u.id, { disabled: !u.disabled })));
      }
    }
  } catch (e) { tb.textContent = ''; cell(tb.insertRow(), e.message); }
}

async function patchUser(id, data) {
  try { await api('PATCH', `/users/${id}`, data); } catch (e) { alert(e.message); }
  loadUsers();
}
