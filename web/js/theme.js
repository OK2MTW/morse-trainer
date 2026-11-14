// SPDX-License-Identifier: EUPL-1.2
// 1.0.2 (Martin): appearance – light / dark background chosen per device (a phone and a PC may differ), or automatic:
// by the system, or by day and night (sunrise and sunset). A classic script in <head> so the page never flashes in
// the wrong colours; the Settings card (main.js) uses window.morseTheme. Nothing goes to the server.
(function () {
  var KEY = 'morse-theme';
  var MODES = ['system', 'light', 'dark', 'sun'];
  var LAT = 50;   // the latitude of the Czech Republic – enough for sunrise / sunset within minutes
  var timer = null;

  function get() {
    var m = null;
    try { m = localStorage.getItem(KEY); } catch (e) { /* private mode */ }
    return MODES.indexOf(m) >= 0 ? m : 'system';
  }

  /** Sunrise and sunset today in local minutes after midnight (the longitude from the standard time zone). */
  function sunTimes(d) {
    var y = d.getFullYear();
    var std = Math.max(new Date(y, 0, 1).getTimezoneOffset(), new Date(y, 6, 1).getTimezoneOffset());
    var lon = -std / 4;                                         // 15° for CET
    var day = Math.floor((d - new Date(y, 0, 0)) / 86400000);
    var g = 2 * Math.PI / 365 * (day - 1);
    var eqt = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g)
      - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
    var decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
      + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
    var lat = LAT * Math.PI / 180;
    var cosH = Math.cos(90.833 * Math.PI / 180) / (Math.cos(lat) * Math.cos(decl)) - Math.tan(lat) * Math.tan(decl);
    var ha = Math.acos(Math.max(-1, Math.min(1, cosH))) * 180 / Math.PI;
    var noon = 720 - 4 * lon - eqt - d.getTimezoneOffset();     // local minutes
    return { rise: noon - 4 * ha, set: noon + 4 * ha };
  }

  function isNight(d) {
    var s = sunTimes(d);
    var m = d.getHours() * 60 + d.getMinutes();
    return m < s.rise || m >= s.set;
  }

  /** The theme in use: 'light' / 'dark', or null = by the system (CSS prefers-color-scheme). */
  function effective(mode) {
    if (mode === 'light' || mode === 'dark') return mode;
    if (mode === 'sun') return isNight(new Date()) ? 'dark' : 'light';
    return null;
  }

  function apply() {
    var mode = get();
    var th = effective(mode);
    var root = document.documentElement;
    if (th) root.setAttribute('data-theme', th); else root.removeAttribute('data-theme');
    var dark = th ? th === 'dark' : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#0d1117' : '#14213d');
    clearInterval(timer);
    timer = mode === 'sun' ? setInterval(apply, 60000) : null;   // day ↔ night while the app is open
  }

  function set(mode) {
    try { localStorage.setItem(KEY, MODES.indexOf(mode) >= 0 ? mode : 'system'); } catch (e) { /* private mode */ }
    apply();
  }

  window.morseTheme = { MODES: MODES, get: get, set: set, apply: apply, sunTimes: sunTimes, isNight: isNight };
  apply();
  if (window.matchMedia) {
    var mq = matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', apply);
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) apply(); });
})();
