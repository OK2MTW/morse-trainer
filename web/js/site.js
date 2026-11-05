// SPDX-License-Identifier: EUPL-1.2
// Domácí a venkovní adresa aplikace (0.8.2, etapa E2). Pro prohlížeč jsou to dvě různé aplikace (vlastní cache,
// přihlášení a instalace), data se synchronizují přes účet. Server posílá na venkovní adrese manifest „Morse venku“.
// Adresy nejsou v kódu – posílá je server (/site-config.js) podle /etc/morse-trainer/site.env (E3).
import { HOME_URL, PUBLIC_URL } from '/site-config.js';

const hostOf = (u) => { try { return new URL(u).hostname; } catch { return ''; } };

export const isPublic = () => !!PUBLIC_URL && location.hostname === hostOf(PUBLIC_URL);

/** Druhá verze aplikace: {url, label, name}, nebo null, pokud není nastavená. */
export function otherSite() {
  if (isPublic()) {
    return HOME_URL ? { url: HOME_URL, label: 'Otevřít domácí verzi', name: `domácí síť (${hostOf(HOME_URL)})` } : null;
  }
  return PUBLIC_URL ? { url: PUBLIC_URL, label: 'Otevřít venkovní verzi', name: 'venku přes internet' } : null;
}
