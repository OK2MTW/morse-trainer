# Morse trainer

> **Languages:** the user interface is available in **Czech and English**; the code (identifiers, comments) is in
> English; the detailed documentation ([README.md](README.md)) is in Czech.

A free web application for learning to **receive Morse code**: Koch method, Farnsworth timing, instant character
recognition and an adaptive plan based on the learner's results. The server runs on a Raspberry Pi; the app is
installed on a phone or computer as a PWA and works offline (results are synced later).

- invitation-only accounts (admin / trainer / learner), password rules, argon2id hashing, no e-mail, no tracking
- sound, timing and scoring run in the browser; the server stores results and computes the plan (SQLite)
- no external services or CDNs (everything is self-hosted on the Pi)
- installation on a Raspberry Pi in a home network; optional access from the internet via Pinggy
  (see the Czech README for step-by-step instructions)
- administration CLI: `.venv/bin/python -m server.admin` (`invite`, `users`, `reset-link`, `password`, `role`,
  `debug`, `reset-training`, …; run without arguments for help)

## Languages
The default language follows the browser (`cs*` → Czech, otherwise English); it can be changed in Settings or on
the login page and, once logged in, it is stored in the account and applies on all devices. Texts are not in the
code but in dictionaries:
- `web/i18n/<lang>.json` – browser texts (flat keys `area.key`, parameters `{name}`, plurals as an object
  `{"one": …, "few": …, "many": …, "other": …}` chosen by `Intl.PluralRules`),
- `server/i18n/<lang>.json` – server texts (API errors, questionnaire, coach plan, levels, manifest),
- `web/i18n/languages.json` – list of languages (code, native name, locale for number and date formats).

**Adding a language:** copy `web/i18n/en.json` and `server/i18n/en.json` to `<code>.json`, translate the values
(keep the keys and `{…}` parameters), add a line to `web/i18n/languages.json` and, if needed, a plural rule to
`server/i18n.py` (`PLURAL`). `tests/test_i18n.py` checks that all languages have the same keys and parameters.
A missing text falls back to English.

## Disclaimer – hobby project, no warranty
- This is an **amateur hobby project** developed in spare time by **Martin, OK2MTW**, primarily for personal use.
  The source code is published because the EUPL-1.2 licence requires it, and as inspiration for others.
- The software is provided **"as is", without any warranty** and without liability for damages (see Articles 7
  and 8 of the EUPL-1.2). Whoever runs an installation is responsible for its operation, security and the
  protection of its users' data.
- The author **does not accept outside ideas or contributions** (pull requests), **does not handle bug reports**
  and **provides no support**.
- The author **does not deal with cybersecurity implications** of third-party installations and issues no
  security fixes or advisories. Running the application, especially with access from the internet, is at your
  own risk.
- Development may stop or change at any time without notice and without backward compatibility.

If you want to take the project in a different direction, make your own fork – the licence allows it under its terms.

## Licence
**EUPL-1.2** (see [LICENSE](LICENSE)). Anyone who makes a modified version available to others (including over a
network) must also make its source code available. Third-party components and credits are listed in the Czech
README and on the "O aplikaci" (About) page of the app.
