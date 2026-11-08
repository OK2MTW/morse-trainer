// SPDX-License-Identifier: EUPL-1.2
// 0.13.0 – User management (coach and administrator): users with a filter by name and group, trainer groups,
// invitations (also into a group), CW room switches (room for children, room off for a single student) and the
// former management from the Account tab (role, block, new-password link, training reset).
import { t, fmtDate as fmtDateL } from './i18n.js';
import { api } from './api.js';

const $ = (s) => document.querySelector(s);
// stored values (DB, API) – only their names are translated
const ROLE_ADMIN = 'admin';
const ROLE_COACH = 'trener';
const ROLE_STUDENT = 'zak';
const GROUP_ALL = '';
const GROUP_NONE = 'none';
const roleName = (r) => ([ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT].includes(r) ? t(`role.${r}`) : r);
const ageName = (a) => (a ? t(`age.${a}`) : t('users.ageUnknown'));
const fmtDate = (iso) => (iso ? fmtDateL(iso, {
  day: 'numeric', month: 'numeric', year: '2-digit', hour: '2-digit', minute: '2-digit',
}) : '–');
// filter by name: case and diacritics do not matter
const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

const state = { me: null, users: [], groups: [], kids: false };

function formError(form, msg) { form.querySelector('.form-error').textContent = msg || ''; }
function busy(form, on) { for (const b of form.querySelectorAll('button')) b.disabled = on; }

function cell(row, text, small) {
  const td = document.createElement('td');
  td.textContent = text;
  if (small) { const s = document.createElement('small'); s.textContent = small; td.append(s); }
  row.append(td);
  return td;
}

function button(text, onClick, cls) {
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = text;
  if (cls) b.className = cls;
  b.addEventListener('click', onClick);
  return b;
}

const isAdmin = () => state.me?.role === ROLE_ADMIN;
const isCoach = () => state.me?.role === ROLE_COACH;
const groupById = (id) => state.groups.find((g) => g.id === id);
function groupLabel(g) {
  if (!isAdmin()) return g.name;
  const c = state.users.find((u) => u.id === g.coach_id);
  return c ? `${g.name} (${c.nick})` : g.name;
}

/** Opens the view: me = the logged-in user, offline = no server (management needs it). */
export async function renderUsers(me, offline) {
  state.me = me;
  $('#users-offline').hidden = !offline;
  $('#users-body').hidden = offline;
  if (offline || !me) return;
  $('#users-title').textContent = isAdmin() ? t('users.title') : t('users.myStudents');
  for (const o of $('#inv-role').options) o.hidden = !isAdmin() && o.value !== ROLE_STUDENT;
  if (!isAdmin()) $('#inv-role').value = ROLE_STUDENT;
  for (const el of document.querySelectorAll('#view-users .coach-only')) el.hidden = !isCoach();
  await reload();
  loadInvites();
}

async function reload() {
  try {
    const [u, g] = await Promise.all([api('GET', '/users'), api('GET', '/groups')]);
    state.users = u.users; state.kids = !!u.kids; state.groups = g.groups;
  } catch (e) {
    state.users = []; state.groups = [];
    $('#users-list').textContent = '';
    cell($('#users-list').insertRow(), e.message);
    return;
  }
  $('#cw-kids').checked = state.kids;
  fillGroupFilter();
  fillInviteGroups();
  renderGroups();
  renderUserList();
}

// ================= filter =================
function fillGroupFilter() {
  const sel = $('#users-group');
  const keep = sel.value;
  sel.textContent = '';
  sel.add(new Option(t('users.groupAll'), GROUP_ALL));
  sel.add(new Option(t('users.groupNone'), GROUP_NONE));
  for (const g of state.groups) sel.add(new Option(groupLabel(g), String(g.id)));
  sel.value = [...sel.options].some((o) => o.value === keep) ? keep : GROUP_ALL;
  $('#users-group-row').hidden = !state.groups.length;
}
$('#users-filter').addEventListener('input', () => renderUserList());
$('#users-group').addEventListener('change', () => renderUserList());

function matches(u) {
  const q = fold($('#users-filter').value.trim());
  if (q && !fold(u.nick).includes(q)) return false;
  const g = $('#users-group').value;
  if (g === GROUP_NONE) return u.group_id == null;
  if (g !== GROUP_ALL) return u.group_id === Number(g);
  return true;
}

// ================= users =================
function cwState(u) {
  if (u.disabled) return '';
  if (u.cw_off) return t('users.cwOff');
  if (u.minor) {
    const coach = state.users.find((c) => c.id === u.invited_by);
    const kidsOn = isCoach() ? state.kids : !!coach?.cw_kids;
    if (isCoach() && !kidsOn) return t('users.cwKidsOff');
    if (isAdmin() && !coach) return t('users.cwMinor');
    return kidsOn ? t('users.cwMinorGroup') : t('users.cwKidsOff');
  }
  return '';
}

function renderUserList() {
  const tb = $('#users-list');
  tb.textContent = '';
  const list = state.users.filter(matches);
  $('#users-count').textContent = t('users.count', { n: list.length, total: state.users.length });
  if (!list.length) { cell(tb.insertRow(), state.users.length ? t('users.noMatch') : t('users.none')); return; }
  for (const u of list) {
    const row = tb.insertRow();
    const facts = [roleName(u.role), ageName(u.age_group)];
    const grp = u.group_id != null && groupById(u.group_id);
    if (grp) facts.push(t('users.inGroup', { name: grp.name }));
    if (isAdmin() && u.coach_nick && u.role === ROLE_STUDENT) facts.push(t('users.coachOf', { nick: u.coach_nick }));
    const cw = cwState(u);
    if (cw) facts.push(cw);
    cell(row, u.nick + (u.disabled ? ` ${t('users.blockedMark')}` : ''), facts.join(' · '));
    cell(row, t('users.levelLessons', { level: u.level || 2, n: u.lessons }), t('users.last', { at: fmtDate(u.last_lesson) }));
    const td = cell(row, '');
    if (u.id !== state.me.id) td.append(userActions(u));
  }
}

/** The actions of one user, folded under "Edit" (the list stays short on a phone). */
function userActions(u) {
  const det = document.createElement('details');
  det.className = 'user-edit';
  const sum = document.createElement('summary');
  sum.textContent = t('users.edit');
  const box = document.createElement('div');
  box.className = 'user-actions';
  det.append(sum, box);

  // group: only groups of the student's own trainer (the server checks the same)
  const own = state.groups.filter((g) => g.coach_id === u.invited_by);
  if (u.role === ROLE_STUDENT && own.length) {
    const sel = document.createElement('select');
    sel.add(new Option(t('users.groupNone'), ''));
    for (const g of own) sel.add(new Option(g.name, String(g.id), false, g.id === u.group_id));
    sel.addEventListener('change', async () => {
      try {
        await api('PUT', `/users/${u.id}/group`, { group_id: sel.value ? Number(sel.value) : null });
      } catch (e) { alert(e.message); }
      reload();
    });
    box.append(labelled(t('users.group'), sel));
  }

  // CW room for this user
  if (!u.disabled) {
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !u.cw_off;
    cb.addEventListener('change', async () => {
      try { await api('PUT', '/cw/access', { id: u.id, off: !cb.checked }); } catch (e) { alert(e.message); }
      reload();
    });
    const l = document.createElement('label');
    l.className = 'check';
    const s = document.createElement('span'); s.textContent = t('users.cwAllowed');
    l.append(cb, s);
    box.append(l);
  }

  const btns = document.createElement('div');
  btns.className = 'buttons';
  btns.append(button(t('users.resetLink'), async () => {
    if (!confirm(t('users.resetLinkConfirm', { nick: u.nick }))) return;
    try {
      const r = await api('POST', `/users/${u.id}/password-link`);
      showLink(`${location.origin}/#heslo=${r.token}`, t('users.resetLinkHint', { nick: u.nick })); // stored link format
      loadInvites();
    } catch (e) { alert(e.message); }
  }));
  if (u.role !== ROLE_ADMIN && u.lessons + (u.level ? 1 : 0) > 0) {
    btns.append(button(t('users.resetTraining'), async () => {
      if (!confirm(t('users.resetTrainingConfirm', { nick: u.nick }))) return;
      try { await api('POST', `/users/${u.id}/reset-training`); } catch (e) { alert(e.message); }
      reload();
    }));
  }
  if (isAdmin()) {
    const sel = document.createElement('select');
    for (const v of [ROLE_ADMIN, ROLE_COACH, ROLE_STUDENT]) sel.add(new Option(roleName(v), v, false, v === u.role));
    sel.addEventListener('change', () => patchUser(u.id, { role: sel.value }));
    box.append(labelled(t('invite.role'), sel));
    btns.append(button(u.disabled ? t('users.unblock') : t('users.block'), () => patchUser(u.id, { disabled: !u.disabled }),
      u.disabled ? '' : 'danger'));
  }
  box.append(btns);
  return det;
}

function labelled(text, control) {
  const l = document.createElement('label');
  const s = document.createElement('span'); s.textContent = text;
  l.append(s, control);
  return l;
}

async function patchUser(id, data) {
  try { await api('PATCH', `/users/${id}`, data); } catch (e) { alert(e.message); }
  reload();
}

// the coach: the room for the children of their groups (minors they invited)
$('#cw-kids').addEventListener('change', async (e) => {
  try { await api('PUT', '/cw/kids', { on: e.target.checked }); } catch (err) { alert(err.message); }
  reload();
});

// ================= groups =================
function renderGroups() {
  const tb = $('#groups-list');
  tb.textContent = '';
  $('#groups-card').hidden = !isCoach() && !state.groups.length;
  if (!state.groups.length) { cell(tb.insertRow(), t('groups.none')); return; }
  for (const g of state.groups) {
    const row = tb.insertRow();
    cell(row, groupLabel(g), t('groups.members', { n: g.members }));
    const td = cell(row, '');
    td.append(button(t('groups.show'), () => {
      $('#users-group').value = String(g.id);
      renderUserList();
      $('#users-card').scrollIntoView({ block: 'start' });
    }));
    if (isCoach()) {
      td.append(button(t('groups.invite'), () => {
        $('#inv-role').value = ROLE_STUDENT;
        fillInviteGroups();
        $('#inv-group').value = String(g.id);
        $('#form-invite').scrollIntoView({ block: 'start' });
        $('#form-invite').note.focus();
      }));
    }
    td.append(button(t('groups.rename'), async () => {
      const name = prompt(t('groups.renamePrompt'), g.name);
      if (name == null || !name.trim() || name.trim() === g.name) return;
      try { await api('PATCH', `/groups/${g.id}`, { name }); } catch (e) { alert(e.message); }
      reload();
      loadInvites();
    }));
    td.append(button(t('groups.delete'), async () => {
      if (!confirm(t('groups.deleteConfirm', { name: g.name, n: g.members }))) return;
      try { await api('DELETE', `/groups/${g.id}`); } catch (e) { alert(e.message); }
      if ($('#users-group').value === String(g.id)) $('#users-group').value = GROUP_ALL;
      reload();
      loadInvites();
    }, 'danger'));
  }
}

$('#form-group').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  busy(f, true);
  try {
    await api('POST', '/groups', { name: f.name.value });
    f.name.value = '';
    await reload();
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});

// ================= invitations =================
function fillInviteGroups() {
  const sel = $('#inv-group');
  const keep = sel.value;
  sel.textContent = '';
  sel.add(new Option(t('users.groupNone'), ''));
  const mine = state.groups.filter((g) => g.coach_id === state.me?.id);
  for (const g of mine) sel.add(new Option(g.name, String(g.id)));
  sel.value = [...sel.options].some((o) => o.value === keep) ? keep : '';
  $('#inv-group-row').hidden = !isCoach() || !mine.length || $('#inv-role').value !== ROLE_STUDENT;
}
$('#inv-role').addEventListener('change', fillInviteGroups);

function showLink(url, hint) {
  $('#inv-link').value = url;
  $('#inv-hint').textContent = hint;
  $('#inv-result').hidden = false;
  $('#inv-share').hidden = !navigator.share;
  $('#inv-result').scrollIntoView({ block: 'center' });
}

$('#form-invite').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  formError(f, '');
  busy(f, true);
  try {
    const data = { role: $('#inv-role').value, note: f.note.value.trim() };
    const gid = $('#inv-group').value;
    if (gid && !$('#inv-group-row').hidden) data.group_id = Number(gid);
    const r = await api('POST', '/invites', data);
    showLink(`${location.origin}/#pozvanka=${r.token}`, t('invite.linkHint')); // stored link format, old clients understand it
    f.note.value = '';
    loadInvites();
  } catch (err) { formError(f, err.message); } finally { busy(f, false); }
});

$('#inv-copy').addEventListener('click', async () => {
  const inp = $('#inv-link');
  try {
    await navigator.clipboard.writeText(inp.value);
    $('#inv-copy').textContent = t('invite.copied');
  } catch (e) {
    inp.select(); // older browser – selects the text for manual copying
  }
  setTimeout(() => { $('#inv-copy').textContent = t('invite.copy'); }, 2000);
});
$('#inv-share').addEventListener('click', () => {
  navigator.share?.({ title: t('invite.shareTitle'), text: t('invite.shareText'), url: $('#inv-link').value })
    .catch(() => {});
});

async function loadInvites() {
  const tb = $('#inv-list');
  try {
    const { invites } = await api('GET', '/invites');
    tb.textContent = '';
    if (!invites.length) { cell(tb.insertRow(), t('invite.none')); return; }
    for (const i of invites) {
      const row = tb.insertRow();
      let what = roleName(i.role);
      if (i.group_name) what += ` · ${t('users.inGroup', { name: i.group_name })}`;
      if (i.note) what += ` – ${i.note}`;
      cell(row, what, t('invite.created', { at: fmtDate(i.created_at) }));
      cell(row, t(`invite.state.${i.state}`), i.used_by_nick ? `→ ${i.used_by_nick}` : (i.state === 'valid' ? t('invite.until', { at: fmtDate(i.expires_at) }) : ''));
      const td = cell(row, '');
      if (i.state === 'valid') {
        td.append(button(t('invite.revoke'), async () => {
          try { await api('DELETE', `/invites/${i.id}`); } catch (e) { alert(e.message); }
          loadInvites();
        }));
      }
    }
  } catch (e) { tb.textContent = ''; cell(tb.insertRow(), e.message); }
}
