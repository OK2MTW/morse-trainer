// SPDX-License-Identifier: EUPL-1.2
// 0.9.3: what's new – a one-off overview of significant features after an update, shown after login (or opening the
// app with a stored login) until the user dismisses it. Several updates in between = a longer list, newest first.
// Only bigger features a user notices. New entry: next id, version, release time (UTC, ISO with Z), i18n keys of the
// bullet points in web/i18n/*.json (all languages). Never change ids; the server stores the last dismissed id.
import { t, fmtDate } from './i18n.js';
import { api } from './api.js';

export const NEWS = [
  { id: 1, version: '0.9.0', at: '2026-11-06T04:50:00Z', items: ['news.i18n'] },
  { id: 2, version: '0.9.2', at: '2026-11-06T05:20:00Z', items: ['news.demo'] },
  { id: 3, version: '0.9.6', at: '2026-11-06T17:14:00Z', items: ['news.extraChars'] },
  { id: 4, version: '0.9.9', at: '2026-11-07T05:24:00Z', items: ['news.earlyCopy'] },
  { id: 5, version: '0.10.0', at: '2026-11-07T05:35:00Z', items: ['news.vocab'] },
  { id: 6, version: '0.10.9', at: '2026-11-07T07:02:00Z', items: ['news.vocabCopy'] },
  { id: 7, version: '0.10.10', at: '2026-11-07T07:36:00Z', items: ['news.nav'] },
  { id: 8, version: '0.10.14', at: '2026-11-07T12:59:00Z', items: ['news.head'] },
  { id: 9, version: '0.10.16', at: '2026-11-07T13:21:00Z', items: ['news.entry'] },
  { id: 10, version: '0.13.2', at: '2026-11-08T02:22:00Z', items: ['news.cwRoom'] },
  { id: 11, version: '0.16.0', at: '2026-11-12T05:24:00Z', items: ['news.vo', 'news.hwOnly'] },
];

const LATEST = Math.max(0, ...NEWS.map((n) => n.id));

/** Entries not dismissed yet and released after the account was created (a new account gets no history). */
export function unseenNews(user) {
  if (!user) return [];
  const seen = Number(user.news_seen) || 0;
  const created = user.created_at || '';
  return NEWS.filter((n) => n.id > seen && n.at > created);
}

const $ = (s) => document.querySelector(s);
let onDismiss = null;

/** Shows the overview if there is something new for the user. onSeen(id) = after dismissing (update the user copy). */
export function showNews(user, onSeen) {
  const list = unseenNews(user);
  const ov = $('#news-overlay');
  if (!list.length || !ov.hidden) return false;
  const root = $('#news-list');
  root.textContent = '';
  for (const n of [...list].reverse()) {
    const h = document.createElement('h3');
    h.textContent = t('news.version', {
      version: n.version, date: fmtDate(n.at, { day: 'numeric', month: 'numeric', year: 'numeric' }),
    });
    const ul = document.createElement('ul');
    for (const key of n.items) {
      const li = document.createElement('li');
      li.textContent = t(key);
      ul.append(li);
    }
    root.append(h, ul);
  }
  onDismiss = () => {
    ov.hidden = true;
    onDismiss = null;
    onSeen?.(LATEST);
    // a failed request only means the overview comes again next time
    api('POST', '/news/seen', { id: LATEST }).catch(() => {});
  };
  ov.hidden = false;
  $('#news-ok').focus();
  return true;
}

$('#news-ok').addEventListener('click', () => onDismiss?.());
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && onDismiss) { e.preventDefault(); onDismiss(); }
});
