// SPDX-License-Identifier: EUPL-1.2
// Translations (I18N, 0.9.0). Texts live in /i18n/<lang>.json (flat keys "area.key", parameters {name},
// plurals as {one, few, many, other} chosen by Intl.PluralRules with parameter n). Fallback: language → en → key.
// Supported languages: /i18n/languages.json – adding a language = adding its JSON file and a line there.
// HTML: data-i18n="key" (text), data-i18n-attr="placeholder:key;title:key" (attributes),
// data-i18n-html="key" (trusted markup from our own dictionaries only, e.g. links in the about page).
const LANG_KEY = 'morse-lang';
export const FALLBACK = 'en';

const fetchJson = async (url) => {
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
};

const readLocal = () => { try { return localStorage.getItem(LANG_KEY); } catch (e) { return null; } };

export const LANGUAGES = (await fetchJson('/i18n/languages.json')) || [{ code: 'en', name: 'English' }];
const supported = (code) => LANGUAGES.some((l) => l.code === code);

/** Language from the browser: first preferred language we support (cs-CZ → cs), otherwise English. */
export function browserLang() {
  for (const l of navigator.languages || [navigator.language || '']) {
    const base = String(l).toLowerCase().split('-')[0];
    if (supported(base)) return base;
  }
  return FALLBACK;
}

export let lang = supported(readLocal()) ? readLocal() : browserLang();
const dicts = {};
dicts[FALLBACK] = (await fetchJson(`/i18n/${FALLBACK}.json`)) || {};
if (lang !== FALLBACK) dicts[lang] = (await fetchJson(`/i18n/${lang}.json`)) || {};

/** BCP 47 locale for Intl formatting (languages.json may refine it, e.g. en → en-GB). */
export const locale = () => LANGUAGES.find((l) => l.code === lang)?.locale || lang;

const has = (d, k) => d && Object.prototype.hasOwnProperty.call(d, k);
const numFmt = new Intl.NumberFormat(locale(), { maximumFractionDigits: 3, useGrouping: false });

/** Number formatted for the current language (decimal comma in Czech). */
export const fmtNum = (x, digits = 3) => (typeof x === 'number' && Number.isFinite(x)
  ? (digits === 3 ? numFmt : new Intl.NumberFormat(locale(), { maximumFractionDigits: digits, useGrouping: false })).format(x)
  : String(x ?? ''));

/** Date/time in the current language; opts as for Intl.DateTimeFormat. */
export const fmtDate = (value, opts) => new Date(value).toLocaleString(locale(), opts);

/** Translated text for key with {name} parameters; plural entries are chosen by params.n. */
export function t(key, params = {}) {
  let v;
  let l = lang;
  if (has(dicts[lang], key)) v = dicts[lang][key];
  else if (has(dicts[FALLBACK], key)) { v = dicts[FALLBACK][key]; l = FALLBACK; }
  else return key;
  if (v && typeof v === 'object') {
    const cat = new Intl.PluralRules(l).select(Number(params.n));
    v = v[cat] ?? v.other ?? '';
  }
  return String(v).replace(/\{(\w+)\}/g, (m, k) => (k in params ? (typeof params[k] === 'number' ? fmtNum(params[k]) : String(params[k])) : m));
}

/** Translate static HTML (data-i18n…) under root. */
export function translateDom(root = document) {
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of root.querySelectorAll('[data-i18n-html]')) el.innerHTML = t(el.dataset.i18nHtml);
  for (const el of root.querySelectorAll('[data-i18n-attr]')) {
    for (const pair of el.dataset.i18nAttr.split(';')) {
      const [attr, key] = pair.split(':').map((s) => s.trim());
      if (attr && key) el.setAttribute(attr, t(key));
    }
  }
  if (root === document) document.documentElement.lang = lang;
}

function rememberLang(code) {
  try { localStorage.setItem(LANG_KEY, code); } catch (e) { /* private mode – language just is not remembered */ }
  // cookie for the server (web app manifest is fetched without our X-Lang header)
  document.cookie = `lang=${code}; path=/; max-age=31536000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
}
rememberLang(lang);

/** Switch language: remember it and reload (all views are re-rendered in the new language). */
export function setLang(code) {
  if (!supported(code) || code === lang) return false;
  rememberLang(code);
  location.reload();
  return true;
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => translateDom());
else translateDom();
