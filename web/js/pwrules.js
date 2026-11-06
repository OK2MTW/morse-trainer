// SPDX-License-Identifier: EUPL-1.2
// E3: password rules – checked while typing. The server checks the same (server/auth.py password_rules).
import { t } from './i18n.js';

export const PW_MIN = 10;
export const PW_MAX = 32;

const isLower = (c) => c !== c.toUpperCase() && c === c.toLowerCase();
const isUpper = (c) => c !== c.toLowerCase() && c === c.toUpperCase();
const isDigit = (c) => /\p{Nd}/u.test(c);
const isSpecial = (c) => !/[\p{L}\p{N}]/u.test(c);

// id = the same rule code as on the server (server/auth.py), text = UI label
export const RULES = [
  { id: 'length', text: () => t('pw.rule.length', { min: PW_MIN, max: PW_MAX }), ok: (pw) => [...pw].length >= PW_MIN && [...pw].length <= PW_MAX },
  { id: 'lower', text: () => t('pw.rule.lower'), ok: (pw) => [...pw].some(isLower) },
  { id: 'upper', text: () => t('pw.rule.upper'), ok: (pw) => [...pw].some(isUpper) },
  { id: 'digit', text: () => t('pw.rule.digit'), ok: (pw) => [...pw].some(isDigit) },
  { id: 'special', text: () => t('pw.rule.special'), ok: (pw) => [...pw].some(isSpecial) },
  { id: 'nick', text: () => t('pw.rule.nick'), ok: (pw, nick) => !nick || nick.length < 3 || !pw.toLowerCase().includes(nick.toLowerCase()) },
];

/**
 * Adds the list of rules with ✓/✗, a check that both passwords match and "Show password" to a form.
 * @param {HTMLInputElement} input new password, @param {HTMLInputElement|null} again confirmation,
 * @param {() => string} getNick nickname. Returns a function valid() → true when everything holds.
 */
export function bindPasswordRules(input, again, getNick) {
  const box = document.createElement('div');
  box.className = 'pw-rules';
  const intro = document.createElement('p');
  intro.className = 'hint';
  intro.textContent = t('pw.mustContain');
  const ul = document.createElement('ul');
  const items = RULES.map((r) => {
    const li = document.createElement('li');
    li.textContent = r.text();
    ul.append(li);
    return li;
  });
  let matchLi = null;
  if (again) {
    matchLi = document.createElement('li');
    matchLi.textContent = t('pw.rule.match');
    ul.append(matchLi);
  }
  const tip = document.createElement('p');
  tip.className = 'hint';
  tip.textContent = t('pw.tip');
  const showLbl = document.createElement('label');
  showLbl.className = 'check';
  const showCb = document.createElement('input');
  showCb.type = 'checkbox';
  showLbl.append(showCb, ` ${t('pw.show')}`);
  box.append(intro, ul, tip, showLbl);
  (again || input).closest('label').after(box);

  input.maxLength = PW_MAX;
  if (again) again.maxLength = PW_MAX;
  showCb.addEventListener('change', () => {
    for (const el of [input, again]) if (el) el.type = showCb.checked ? 'text' : 'password';
  });

  const valid = () => {
    const pw = input.value;
    const nick = getNick();
    let all = true;
    RULES.forEach((r, i) => {
      const ok = r.ok(pw, nick);
      items[i].className = ok ? 'ok' : 'bad';
      all &&= ok;
    });
    if (matchLi) {
      const ok = pw.length > 0 && pw === again.value;
      matchLi.className = ok ? 'ok' : 'bad';
      all &&= ok;
    }
    return all;
  };
  for (const el of [input, again]) el?.addEventListener('input', valid);
  valid();
  const form = input.form;
  form.addEventListener('reset', () => setTimeout(() => { showCb.checked = false; showCb.dispatchEvent(new Event('change')); valid(); }));
  return valid;
}
