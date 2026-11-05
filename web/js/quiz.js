// SPDX-License-Identifier: EUPL-1.2
// Dotazník (M4): ~12 otázek → server spočítá archetyp, modifikátory a preference. Odpovědi se neukládají.
import { api } from './api.js';

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

/**
 * Vykreslí dotazník do root. onDone(info) dostane výsledek serveru (archetyp, modifikátory, preference).
 */
export async function renderQuiz(root, { onDone, onCancel } = {}) {
  root.textContent = '';
  root.append(el('p', 'hint', 'Načítám otázky…'));
  let questions;
  try {
    questions = (await api('GET', '/coach/questions')).questions;
  } catch (e) {
    root.textContent = '';
    root.append(el('p', 'hint warn', `Dotazník se nepodařilo načíst: ${e.message}`));
    return;
  }
  root.textContent = '';
  root.append(el('p', 'hint', 'Odpovědi slouží jen k nastavení plánu. Neukládají se – uloží se jen výsledek '
    + '(typ plánu a preference). Kdykoli ho můžeš vyplnit znovu.'));
  const answers = {};
  const sets = [];
  const form = el('form', 'quiz');
  for (const q of questions) {
    const fs = el('fieldset', 'quiz-q');
    fs.append(el('legend', null, q.text));
    for (const o of q.options) {
      const lab = el('label', 'quiz-opt');
      const inp = document.createElement('input');
      inp.type = 'radio';
      inp.name = `q-${q.id}`;
      inp.value = o.value;
      inp.addEventListener('change', () => { answers[q.id] = o.value; refresh(); });
      lab.append(inp, document.createTextNode(` ${o.label}`));
      fs.append(lab);
    }
    sets.push({ q, fs });
    form.append(fs);
  }
  const msg = el('p', 'hint warn');
  msg.hidden = true;
  const submit = el('button', 'big', 'Sestavit plán');
  submit.type = 'submit';
  const cancel = el('button', null, 'Zpět');
  cancel.type = 'button';
  cancel.addEventListener('click', () => onCancel?.());
  form.append(msg, submit, cancel);
  root.append(form);

  const visible = (q) => !q.when || q.when.in.includes(answers[q.when.q]);
  function refresh() {
    for (const { q, fs } of sets) {
      fs.hidden = !visible(q);
      if (fs.hidden) {
        delete answers[q.id];
        for (const inp of fs.querySelectorAll('input')) inp.checked = false;
      }
    }
  }
  refresh();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const missing = sets.filter(({ q }) => visible(q) && !(q.id in answers)).length;
    if (missing) {
      msg.textContent = `Zbývá odpovědět na ${missing} ${missing === 1 ? 'otázku' : missing < 5 ? 'otázky' : 'otázek'}.`;
      msg.hidden = false;
      return;
    }
    submit.disabled = true;
    try {
      const info = await api('POST', '/coach/profile', { answers });
      onDone?.(info);
    } catch (err) {
      msg.textContent = `Nepodařilo se uložit: ${err.message}`;
      msg.hidden = false;
      submit.disabled = false;
    }
  });
}
