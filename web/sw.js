// SPDX-License-Identifier: EUPL-1.2
// Service worker: aplikace se nainstaluje a statické soubory jdou i při výpadku sítě.
// Strategie „nejdřív síť, při selhání cache“ – při vývoji vždy dostaneš novou verzi.
const CACHE = 'morse-v0.8.8';
const ASSETS = [
  '/', '/index.html', '/css/app.css', '/js/main.js', '/js/audio.js', '/js/keyboard.js', '/js/charset.js', '/js/drill.js', '/js/coach.js', '/js/storage.js',
  '/js/api.js', '/js/account.js', '/js/stats.js', '/js/quiz.js', '/js/plan.js', '/js/dashboard.js',
  '/js/copy.js', '/js/content.js', '/js/words.js', '/js/abbr.js', '/js/site.js', '/site-config.js', '/js/pwrules.js', '/js/copylesson.js', '/o-aplikaci.html',
  '/vendor/morse-pro/morse-pro.js', '/vendor/morse-pro/morse-pro-message.js',
  '/vendor/morse-pro/morse-pro-cw.js', '/vendor/morse-pro/morse-pro-wpm.js',
  '/manifest.webmanifest', '/icons/icon-192.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      })
      .catch(() => caches.match(e.request)),
  );
});
