// SPDX-License-Identifier: EUPL-1.2
// 0.10.0: vocabulary trainer – overview of the three lists and a multiple-choice quiz (code → 3 meanings), no time limit.
// Results per item go to the server (/api/vocab) at the end of a session; offline they wait in a local queue.
import { t, fmtDate, locale } from './i18n.js';
import { api } from './api.js';
import {
  VOCAB, VOCAB_ITEMS, VOCAB_LISTS, vocabLabel, vocabKey, vocabShown, vocabSorted, mastered, vocabWeight, VOCAB_RETRY_AFTER, VOCAB_RECENT,
  VOCAB_MASTER_N, VOCAB_MASTER_ACC, PROSIGNS, copyAbbrForms,
} from './vocab.js';

const $ = (s) => document.querySelector(s);
const QKEY = (uid) => `morse-vocab-q-${uid}`;
const CKEY = (uid) => `morse-vocab-copy-${uid}`; // 0.10.9: mastered forms for copy behind, for an offline start
const pct = (wrong, n) => (n ? Math.round((wrong / n) * 100) : 0);
const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
  : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join(''));

function readQ(uid) { try { return JSON.parse(localStorage.getItem(QKEY(uid)) || '[]'); } catch (e) { return []; } }
function writeQ(uid, q) { try { localStorage.setItem(QKEY(uid), JSON.stringify(q)); } catch (e) { /* storage blocked */ } }

/** Code as written in the overview: a prefix with its whole series. */
const codeLabel = vocabLabel;

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

/** 0.10.8 (Martin): the quiz also plays the shown code in Morse (checkbox in the quiz, remembered on the device). */
const SOUND_KEY = 'morse-vocab-sound';
export const vocabMorseText = (shown) => PROSIGNS[shown] || shown;

/**
 * deps: {sync (storage.sync: uid, epoch), show, player (MorsePlayer), ensureAudio}
 */
export function initVocab({ sync, show, player = null, ensureAudio = null }) {
  const V = { data: null, chosen: new Set(['abbr']), tab: 'abbr', S: null };

  // ---------- Morse sound of the shown code ----------
  const soundBox = $('#vocab-sound');
  try { soundBox.checked = localStorage.getItem(SOUND_KEY) !== '0'; } catch (e) { soundBox.checked = true; }
  $('#vocab-replay').hidden = !soundBox.checked;

  async function sound() {
    const c = V.S?.cur;
    if (!player || !c || !soundBox.checked) return;
    if (ensureAudio && !(await ensureAudio())) return;
    if (V.S?.cur !== c) return; // the next question came meanwhile
    try { player.play(vocabMorseText(c.shown)); } catch (e) { /* audio not available – the text is enough */ }
  }

  function quiet() { try { player?.stop(); } catch (e) { /* not unlocked */ } }

  soundBox.addEventListener('change', () => {
    try { localStorage.setItem(SOUND_KEY, soundBox.checked ? '1' : '0'); } catch (e) { /* private mode */ }
    $('#vocab-replay').hidden = !soundBox.checked;
    if (soundBox.checked) sound(); else quiet();
  });
  $('#vocab-replay').addEventListener('click', () => sound());

  // ---------- server data & queue ----------
  async function flush() {
    const uid = sync.uid;
    if (uid == null) return;
    let q = readQ(uid);
    if (!q.length) return;
    try {
      await api('POST', '/vocab', { sessions: q, epoch: sync.epoch });
      // sent = done (an invalid session is dropped by the server – it must not be sent forever); keep newer ones
      const sent = new Set(q.map((s) => s.id));
      writeQ(uid, readQ(uid).filter((s) => !sent.has(s.id)));
    } catch (e) {
      if (e.status === 409) writeQ(uid, []); // the training was reset meanwhile – old results do not belong anywhere
    }
  }

  async function load() {
    await flush();
    try { V.data = await api('GET', '/vocab'); } catch (e) { /* offline – keep what we have */ }
    return V.data;
  }

  /** [n, wrong, lastOk] of an item: server + not yet sent sessions + the running session. */
  function itemStat(list, code) {
    const s = V.data?.lists?.[list]?.items?.[code];
    let n = s ? s[0] : 0;
    let wrong = s ? s[1] : 0;
    let last = s ? s[2] : null;
    for (const ses of readQ(sync.uid)) {
      for (const it of ses.items) if (it[0] === list && it[1] === code) { n += it[2]; wrong += it[3]; last = it[4] ? 1 : 0; }
    }
    const r = V.S?.items.get(`${list}:${code}`);
    if (r) { n += r.n; wrong += r.wrong; last = r.lastOk ? 1 : 0; }
    return [n, wrong, last];
  }

  /**
   * 0.10.9: abbreviations and Q codes for copy behind – only items mastered here (server + unsent sessions).
   * Waits for the server at most waitMs; without any data (offline, never loaded) the last stored list is used.
   */
  async function copyForms(waitMs = 1500) {
    await Promise.race([load(), new Promise((r) => setTimeout(r, waitMs))]);
    const uid = sync.uid;
    if (!V.data) {
      try { return JSON.parse(localStorage.getItem(CKEY(uid)) || '[]'); } catch (e) { return []; }
    }
    const forms = copyAbbrForms(itemStat);
    try { localStorage.setItem(CKEY(uid), JSON.stringify(forms)); } catch (e) { /* storage blocked */ }
    return forms;
  }

  // ---------- menu + overview ----------
  function renderMenu() {
    $('#vocab-run').hidden = true;
    $('#vocab-done').hidden = true;
    $('#vocab-menu').hidden = false;
    $('#vocab-need').hidden = true;
    const box = $('#vocab-lists');
    box.textContent = '';
    for (const k of VOCAB_LISTS) {
      const lbl = el('label', 'check');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.checked = V.chosen.has(k);
      cb.addEventListener('change', () => { if (cb.checked) V.chosen.add(k); else V.chosen.delete(k); });
      const m = VOCAB[k].filter((c) => mastered(itemStat(k, c))).length;
      lbl.append(cb, ` ${t(`vocab.list.${k}`)} `, el('small', 'muted', `(${t('vocab.mastered', { m, of: VOCAB[k].length })})`));
      box.append(lbl);
    }
    renderOverview();
  }

  function renderOverview() {
    const tabs = $('#vocab-tabs');
    tabs.textContent = '';
    for (const k of VOCAB_LISTS) {
      const b = el('button', k === V.tab ? 'active' : '', t(`vocab.list.${k}`));
      b.type = 'button';
      b.setAttribute('aria-pressed', String(k === V.tab));
      b.addEventListener('click', () => { V.tab = k; renderOverview(); });
      tabs.append(b);
    }
    $('#vocab-ov-hint').textContent = t('vocab.overviewHint', { n: VOCAB_MASTER_N, acc: Math.round(VOCAB_MASTER_ACC * 100) });
    const body = $('#vocab-table');
    body.textContent = '';
    for (const code of vocabSorted(V.tab, (c) => t(vocabKey(V.tab, c)), locale())) {
      const s = itemStat(V.tab, code);
      const tr = el('tr');
      const meaning = el('td', null, t(vocabKey(V.tab, code)));
      if (VOCAB_ITEMS[V.tab][code].extra) meaning.append(' ', el('small', 'muted', t('vocab.extra'))); // not in the CTU list
      tr.append(el('td', 'vocab-code', codeLabel(V.tab, code)), meaning,
        el('td', 'muted', s[0] ? `${mastered(s) ? '✓ ' : ''}${s[0] - s[1]}/${s[0]}` : '–'));
      body.append(tr);
    }
  }

  // ---------- quiz ----------
  function pickItem() {
    const S = V.S;
    S.count += 1;
    const due = S.retry.findIndex((r) => r.at <= S.count);
    if (due >= 0) return S.retry.splice(due, 1)[0].item;
    const pool = [];
    for (const list of S.lists) for (const code of VOCAB[list]) pool.push({ list, code });
    const fresh = pool.filter((p) => !S.recent.includes(`${p.list}:${p.code}`));
    const cand = fresh.length ? fresh : pool;
    const w = cand.map((p) => vocabWeight(itemStat(p.list, p.code)));
    let r = Math.random() * w.reduce((a, b) => a + b, 0);
    for (let i = 0; i < cand.length; i++) { r -= w[i]; if (r <= 0) return cand[i]; }
    return cand.at(-1);
  }

  function options(item) {
    const right = t(vocabKey(item.list, item.code));
    const others = VOCAB[item.list].filter((c) => c !== item.code).map((c) => t(vocabKey(item.list, c)))
      .filter((m, i, a) => m !== right && a.indexOf(m) === i);
    const opts = [right];
    while (opts.length < 3 && others.length) opts.push(others.splice(Math.floor(Math.random() * others.length), 1)[0]);
    for (let i = opts.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [opts[i], opts[j]] = [opts[j], opts[i]]; }
    return { opts, right };
  }

  function live() {
    const S = V.S;
    $('#vocab-live').textContent = S.n ? t('vocab.live', { n: S.n, err: pct(S.wrong, S.n) }) : t('vocab.liveNone');
  }

  function ask() {
    const S = V.S;
    const item = pickItem();
    S.recent.push(`${item.list}:${item.code}`);
    if (S.recent.length > VOCAB_RECENT) S.recent.shift();
    const { opts, right } = options(item);
    const shown = vocabShown(item.list, item.code); // one of the item's forms (TNX/TKS, QRO?, a prefix of the series)
    S.cur = { item, right, shown, answered: false };
    $('#vocab-q-label').textContent = t(item.list === 'pfx' ? 'vocab.questionPfx' : 'vocab.question');
    $('#vocab-q-list').textContent = t(`vocab.list.${item.list}`);
    $('#vocab-q-code').textContent = shown;
    sound();
    $('#vocab-feedback').textContent = '';
    $('#vocab-next').hidden = true;
    const box = $('#vocab-opts');
    box.textContent = '';
    opts.forEach((o, i) => {
      const b = el('button', 'vocab-opt', `${i + 1}. ${o}`);
      b.type = 'button';
      b.dataset.answer = o;
      b.addEventListener('click', () => answer(o));
      box.append(b);
    });
    live();
  }

  function answer(o) {
    const S = V.S;
    const c = S.cur;
    if (!c || c.answered) return;
    c.answered = true;
    const ok = o === c.right;
    const key = `${c.item.list}:${c.item.code}`;
    const r = S.items.get(key) || { list: c.item.list, code: c.item.code, n: 0, wrong: 0, lastOk: true };
    r.n += 1;
    if (!ok) r.wrong += 1;
    r.lastOk = ok;
    S.items.set(key, r);
    S.n += 1;
    if (!ok) { S.wrong += 1; S.retry.push({ item: c.item, at: S.count + VOCAB_RETRY_AFTER }); }
    for (const b of document.querySelectorAll('#vocab-opts button')) {
      b.disabled = true;
      if (b.dataset.answer === c.right) b.classList.add('right');
      else if (b.dataset.answer === o) b.classList.add('wrong');
    }
    const label = vocabLabel(c.item.list, c.item.code);
    const more = label !== c.shown; // other forms (TNX, TKS) or the whole series of a country
    const full = more ? `${c.right} (${label})` : c.right;
    $('#vocab-feedback').textContent = ok ? `${t('vocab.right')} ${more ? full : ''}`.trim() : t('vocab.wrong', { ans: full });
    $('#vocab-feedback').className = ok ? 'hint' : 'hint warn';
    live();
    if (ok) S.timer = setTimeout(ask, 900);
    else { $('#vocab-next').hidden = false; $('#vocab-next').focus(); }
  }

  function start() {
    const lists = VOCAB_LISTS.filter((k) => V.chosen.has(k));
    if (!lists.length) { $('#vocab-need').hidden = false; return; }
    V.S = { lists, items: new Map(), n: 0, wrong: 0, count: 0, retry: [], recent: [], cur: null, t0: Date.now(), timer: null };
    $('#vocab-menu').hidden = true;
    $('#vocab-done').hidden = true;
    $('#vocab-run').hidden = false;
    ask();
  }

  function finish() {
    const S = V.S;
    if (!S) return;
    clearTimeout(S.timer);
    quiet();
    V.S = null;
    $('#vocab-run').hidden = true;
    if (!S.n) { renderMenu(); return; }
    const items = [...S.items.values()].map((r) => [r.list, r.code, r.n, r.wrong, r.lastOk]);
    const ses = { id: uuid(), at: new Date().toISOString(), durS: Math.round((Date.now() - S.t0) / 1000), items };
    writeQ(sync.uid, [...readQ(sync.uid), ses]);
    // summary
    const sum = $('#vocab-sum');
    sum.textContent = '';
    for (const k of S.lists) {
      const rs = [...S.items.values()].filter((r) => r.list === k);
      const n = rs.reduce((a, r) => a + r.n, 0);
      if (!n) continue;
      const wrong = rs.reduce((a, r) => a + r.wrong, 0);
      sum.append(el('p', null, t('vocab.doneList', { list: t(`vocab.list.${k}`), n, err: pct(wrong, n) })));
    }
    const bad = [...S.items.values()].filter((r) => r.wrong);
    sum.append(el('p', 'hint', bad.length ? t('vocab.doneMistakes') : t('vocab.doneNone')));
    if (bad.length) {
      const ul = el('ul', 'vocab-mistakes');
      for (const r of bad) ul.append(el('li', null, `${codeLabel(r.list, r.code)} – ${t(vocabKey(r.list, r.code))}`));
      sum.append(ul);
    }
    $('#vocab-offline').hidden = true;
    $('#vocab-done').hidden = false;
    load().then(() => { $('#vocab-offline').hidden = !readQ(sync.uid).length; });
  }

  // keys on a PC: 1–3 answer, Enter/space = next
  function onKey(e) {
    if (!V.S || e.repeat || e.ctrlKey || e.altKey || e.metaKey) return false;
    const c = V.S.cur;
    if (c && !c.answered && ['1', '2', '3'].includes(e.key)) {
      const b = document.querySelectorAll('#vocab-opts button')[Number(e.key) - 1];
      if (b) answer(b.dataset.answer);
      return true;
    }
    if (c && c.answered && (e.key === 'Enter' || e.key === ' ') && !$('#vocab-next').hidden) { ask(); return true; }
    if (c && (e.key === 'r' || e.key === 'R') && soundBox.checked) { sound(); return true; } // replay the Morse
    return false;
  }

  /** Card in Progress: per list mastered items and the overall error rate, the last session. */
  function renderStats(root) {
    root.textContent = '';
    root.append(el('h2', null, t('vocab.statsTitle')));
    const d = V.data;
    for (const k of VOCAB_LISTS) {
      const x = d?.lists?.[k];
      if (!x || !x.n) { root.append(el('p', 'muted', t('vocab.statsNone', { list: t(`vocab.list.${k}`) }))); continue; }
      const m = VOCAB[k].filter((c) => mastered(x.items[c])).length;
      root.append(el('p', null, t('vocab.statsList', { list: t(`vocab.list.${k}`), m, of: VOCAB[k].length, err: pct(x.wrong, x.n), n: x.n })));
    }
    const last = d?.sessions?.[0];
    if (last) root.append(el('p', 'hint', t('vocab.statsLast', { date: fmtDate(last.at, { dateStyle: 'short', timeStyle: 'short' }), n: last.n, err: pct(last.wrong, last.n) })));
  }

  /**
   * Printable list of the open overview tab (two columns): with meanings, or a practice sheet with blank lines.
   * The browser's print dialog saves it as PDF – no PDF library (licences, no CDN, memory of the Pi).
   */
  function printList(blank) {
    const list = V.tab;
    let host = document.getElementById('vocab-print');
    if (!host) { host = el('div'); host.id = 'vocab-print'; document.body.append(host); }
    host.textContent = '';
    const title = t(blank ? 'vocab.printBlankTitle' : 'vocab.printTitle', { list: t(`vocab.list.${list}`) });
    host.append(el('h1', null, title));
    const cols = el('div', 'vp-cols');
    for (const code of vocabSorted(list, (c) => t(vocabKey(list, c)), locale())) {
      const row = el('div', 'vp-row');
      row.append(el('span', 'vp-code', codeLabel(list, code)), el('span', blank ? 'vp-blank' : 'vp-meaning', blank ? '' : t(vocabKey(list, code))));
      cols.append(row);
    }
    host.append(cols, el('p', 'vp-foot', list === 'pfx' ? t('vocab.printFoot') : t('app.title')));
    document.body.classList.add('printing');
    // 0.10.3: "Save as PDF" names the file after the page title → the list, not the app
    const appTitle = document.title;
    document.title = blank ? t('vocab.printBlankFile', { list: t(`vocab.list.${list}`) }) : title;
    let restored = false;
    const done = () => {
      if (restored) return;
      restored = true;
      document.body.classList.remove('printing');
      document.title = appTitle;
      window.removeEventListener('afterprint', done);
    };
    window.addEventListener('afterprint', done);
    window.print();
    setTimeout(done, 60000); // some mobile browsers never fire afterprint
  }

  $('#vocab-pdf').addEventListener('click', () => printList(false));
  $('#vocab-pdf-blank').addEventListener('click', () => printList(true));
  $('#vocab-start').addEventListener('click', start);
  $('#vocab-finish').addEventListener('click', finish);
  $('#vocab-next').addEventListener('click', ask);
  $('#vocab-again').addEventListener('click', start);
  $('#vocab-back').addEventListener('click', renderMenu);

  return {
    render: () => { if (!V.S) renderMenu(); load().then(() => { if (!V.S && !$('#vocab-menu').hidden) renderMenu(); }); },
    stop: () => { if (V.S) finish(); },
    onKey,
    renderStats: async (root) => { renderStats(root); await load(); renderStats(root); },
    flush,
    copyForms,
  };
}
