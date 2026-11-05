// SPDX-License-Identifier: EUPL-1.2
// E3: pravidla hesla – průběžná kontrola při psaní. Server kontroluje totéž (server/auth.py password_rules).
export const PW_MIN = 10;
export const PW_MAX = 32;

const isLower = (c) => c !== c.toUpperCase() && c === c.toLowerCase();
const isUpper = (c) => c !== c.toLowerCase() && c === c.toUpperCase();
const isDigit = (c) => /\p{Nd}/u.test(c);
const isSpecial = (c) => !/[\p{L}\p{N}]/u.test(c);

export const RULES = [
  { text: `${PW_MIN} až ${PW_MAX} znaků`, ok: (pw) => [...pw].length >= PW_MIN && [...pw].length <= PW_MAX },
  { text: 'malé písmeno (a–z)', ok: (pw) => [...pw].some(isLower) },
  { text: 'velké písmeno (A–Z)', ok: (pw) => [...pw].some(isUpper) },
  { text: 'číslici (0–9)', ok: (pw) => [...pw].some(isDigit) },
  { text: 'speciální znak (např. ! ? - _ . # @)', ok: (pw) => [...pw].some(isSpecial) },
  { text: 'neobsahuje přezdívku', ok: (pw, nick) => !nick || nick.length < 3 || !pw.toLowerCase().includes(nick.toLowerCase()) },
];

/**
 * Připojí k formuláři seznam pravidel s ✓/✗, kontrolu shody hesel a „Ukázat heslo“.
 * @param {HTMLInputElement} input nové heslo, @param {HTMLInputElement|null} again kontrola,
 * @param {() => string} getNick přezdívka. Vrací funkci valid() → true, když vše platí.
 */
export function bindPasswordRules(input, again, getNick) {
  const box = document.createElement('div');
  box.className = 'pw-rules';
  const intro = document.createElement('p');
  intro.className = 'hint';
  intro.textContent = 'Heslo musí obsahovat:';
  const ul = document.createElement('ul');
  const items = RULES.map((r) => {
    const li = document.createElement('li');
    li.textContent = r.text;
    ul.append(li);
    return li;
  });
  let matchLi = null;
  if (again) {
    matchLi = document.createElement('li');
    matchLi.textContent = 'obě hesla jsou stejná';
    ul.append(matchLi);
  }
  const tip = document.createElement('p');
  tip.className = 'hint';
  tip.textContent = 'Tip: dvě slova, číslo a znak, třeba Ranni4!Kava (tohle ale nepoužívej). Heslo nepoužívej jinde.';
  const showLbl = document.createElement('label');
  showLbl.className = 'check';
  const showCb = document.createElement('input');
  showCb.type = 'checkbox';
  showLbl.append(showCb, ' Ukázat heslo');
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
