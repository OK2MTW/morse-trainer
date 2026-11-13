// SPDX-License-Identifier: EUPL-1.2
// 0.14.6: public visit counter – a short line "today / in total since" on the login page and on the home page, for
// everybody. The server caches the numbers for a minute; offline or an older server → the line stays hidden.
import { api } from './api.js';
import { t, fmtNum, fmtDate } from './i18n.js';

const MIN_GAP_MS = 60000;
let last = { at: 0, data: null };

function render(d) {
  for (const el of document.querySelectorAll('.visits-public')) {
    el.hidden = !d;
    if (!d) continue;
    el.textContent = t('visits.public.line', {
      today: fmtNum(d.today, 0), total: fmtNum(d.total, 0),
      since: fmtDate(`${d.since}T12:00:00Z`, { day: 'numeric', month: 'numeric', year: 'numeric' }),
    });
  }
}

/** Shows the counter; asks the server at most once a minute (every view change calls it). */
export async function showVisitCount() {
  if (last.data) render(last.data);
  if (Date.now() - last.at < MIN_GAP_MS) return;
  last.at = Date.now();
  try {
    const d = await api('GET', '/visits/public');
    if (d && Number.isFinite(d.today) && Number.isFinite(d.total)) last.data = d;
  } catch (e) { /* offline, busy, older server – keep what we have */ }
  render(last.data);
}
