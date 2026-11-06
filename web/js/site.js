// SPDX-License-Identifier: EUPL-1.2
// Home and outside address of the app (0.8.2, stage E2). For the browser these are two different apps (own cache,
// login and installation), data are synchronized through the account. On the outside address the server sends the
// "Morse outside" manifest. Addresses are not in the code – the server sends them (/site-config.js) from
// /etc/morse-trainer/site.env (E3).
import { HOME_URL, PUBLIC_URL } from '/site-config.js';
import { t } from './i18n.js';

const hostOf = (u) => { try { return new URL(u).hostname; } catch { return ''; } };

export const isPublic = () => !!PUBLIC_URL && location.hostname === hostOf(PUBLIC_URL);

/** The other version of the app: {url, label, name}, or null when not configured. */
export function otherSite() {
  if (isPublic()) {
    return HOME_URL ? { url: HOME_URL, label: t('site.openHome'), name: `${t('site.home')} (${hostOf(HOME_URL)})` } : null;
  }
  return PUBLIC_URL ? { url: PUBLIC_URL, label: t('site.openPublic'), name: t('site.public') } : null;
}
