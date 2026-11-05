# Morse trenažer

*English: see [README.en.md](README.en.md).*

Bezplatný webový trenažer příjmu Morseovy abecedy: Kochova metoda, Farnsworthovo časování, okamžité
rozpoznání znaku a adaptivní plán podle výsledků žáka. Server běží na Raspberry Pi. Aplikace se do telefonu
nebo počítače instaluje jako PWA a trénovat jde i offline (výsledky se odešlou později).

- účty jen na pozvánku (role správce / trenér / žák), pravidla hesla, hesla argon2id, bez e-mailů a bez sledování
- zvuk, časování a vyhodnocení běží v prohlížeči, server ukládá výsledky a počítá plán (SQLite)
- bez externích služeb a CDN (vše hostované na Pi), rozhraní česky

## Upozornění – amatérský projekt bez záruk
- Jde o **amatérský hobby projekt**, který ve volném čase rozvíjí autor **Martin, OK2MTW**, především pro
  vlastní potřebu. Kód je zveřejněný proto, že to vyžaduje licence EUPL-1.2 a pro inspiraci dalším.
- Software se poskytuje **„tak, jak je“, bez jakýchkoli záruk** a bez odpovědnosti za škody (viz články 7 a 8
  licence EUPL-1.2). Za provoz vlastní instalace, její zabezpečení a ochranu dat uživatelů odpovídá provozovatel.
- Autor **nepřijímá nápady ani úpravy zvenčí** (pull requesty), **neřeší hlášení chyb** a **neposkytuje podporu**.
- Autor **neřeší dopady na kybernetickou bezpečnost** cizích instalací, nevydává bezpečnostní opravy ani
  upozornění. Kdo aplikaci provozuje, zvlášť s přístupem z internetu, dělá to na vlastní riziko.
- Vývoj může kdykoli skončit nebo se změnit bez ohlášení a bez zpětné kompatibility.
- Projekt je **jen v češtině** (rozhraní, dokumentace i komentáře v kódu).

Pokud chcete projekt rozvíjet jinak, udělejte si vlastní kopii (fork) – licence to dovoluje za jejích podmínek.

## Co je potřeba
- Raspberry Pi (vyzkoušeno na 3B+ s 1 GB RAM) s Raspberry Pi OS (Debian 12) a pevnou IP v domácí síti
- balíčky: `sudo apt install git nginx python3-venv python3-flask openssl ufw`
  (ufw je volitelný, bez něj skript firewall přeskočí)

## Instalace v domácí síti
```
git clone https://github.com/OK2MTW/morse-trainer.git
cd morse-trainer
sudo deploy/install.sh
```
Skript při prvním spuštění vytvoří `/etc/morse-trainer/site.env` s odhadnutou adresou Pi a domácí sítí
(vzor `deploy/site.env.example`). Hodnoty zkontrolujte (`sudo nano /etc/morse-trainer/site.env`) a skript spusťte
znovu. Dál skript:
- vytvoří vlastní certifikační autoritu omezenou jen na domácí síť a certifikát serveru (`/etc/morse-trainer/pki`),
- nastaví nginx (HTTPS 443, HTTP 80 jen pro stažení certifikátu CA) a firewall (80/443 jen z domácí sítě),
- nainstaluje Python závislosti do `.venv`, vytvoří databázi `data/morse.db` a službu `morse-trainer`,
- vytiskne pozvánku pro prvního správce.

**Certifikát v zařízeních:** v domácí síti je potřeba jednou nainstalovat certifikát domácí CA
(`http://<adresa-pi>/ca.crt`; Android: Nastavení → Zabezpečení → Šifrování a pověření → Instalovat certifikát →
Certifikát CA). Bez HTTPS nefunguje instalace aplikace ani zvuk v pozadí. CA nemůže podepsat certifikát
pro jiné weby (je omezená na domácí síť).

**Správa** (na Pi, jako vlastník adresáře aplikace):
```
.venv/bin/python -m server.admin pozvanka zak "poznámka"   # odkaz s pozvánkou (platí 7 dní, jednou)
.venv/bin/python -m server.admin uzivatele
.venv/bin/python -m server.admin obnova PREZDIVKA          # odkaz na nové heslo (zapomenuté heslo)
```
Heslo: 10–32 znaků, malé i velké písmeno, číslice a speciální znak, bez přezdívky (aplikace kontroluje
při psaní). Zapomenuté heslo: správce nebo trenér vytvoří odkaz na nové heslo (v aplikaci u uživatele nebo
příkazem `obnova`), trénink zůstane.
Správce aplikaci spravuje, netrénuje. Trenér vidí své žáky, žák trénuje.

## Přístup z internetu přes Pinggy (volitelné)
[Pinggy](https://pinggy.io) vytvoří z Pi **odchozí** SSH tunel, takže na routeru se nic neotevírá. Veřejná adresa
má platný certifikát Let's Encrypt a uživatelé zvenku nic neinstalují. Je potřeba účet Pinggy Pro s trvalou
subdoménou.

1. V `/etc/morse-trainer/site.env` doplňte `MORSE_PUBLIC_URL=https://<subdomena>.a.pinggy.link/`.
2. `sudo deploy/pinggy-setup.sh` vytvoří veřejný vstup nginx (jen `127.0.0.1:8090`), službu `morse-pinggy`
   a `/etc/morse-trainer/pinggy.env`.
3. Do `/etc/morse-trainer/pinggy.env` vložte token z dashboardu Pinggy (soubor čte jen root, do gitu nepatří).
4. `sudo systemctl enable --now morse-pinggy`. Odpojení zvenku: `sudo systemctl stop morse-pinggy`.

Ochrana veřejného vstupu: tunel vede jen na vyhrazený vstup nginx, cizí jméno serveru se odmítne, platí limity
požadavků a přihlášení (na IP i celkově), aplikace blokuje IP po opakovaných chybách a správce se zvenku
nepřihlásí. Venkovní adresa se instaluje jako samostatná aplikace „Morse venku“. Data se synchronizují přes účet.
Přehled přístupů zvenku: `sudo deploy/pinggy-report.sh`.

**Jiné způsoby provozu na internetu** (vlastní doména, veřejná IP, jiný tunel, reverzní proxy, cloud) jsou možné,
ale tento kód je neobsahuje. Vyžadují vlastní úpravy nasazení a zabezpečení.

## Vývoj
- `server/` – Flask API (waitress za nginx), `web/` – frontend (vanilla JS, ES moduly, bez build kroku),
  `web/vendor/morse-pro/` – knihovna morse-pro, `deploy/` – nginx, systemd, certifikáty, Pinggy
- testy: `.venv/bin/python -m unittest discover -s tests`

## Licence a poděkování
Licence **EUPL-1.2** (viz [LICENSE](LICENSE)). Kdo upravenou verzi zpřístupní dalším lidem (i jen přes síť),
musí zpřístupnit i její zdrojový kód. Odkaz na zdroj je ve stránce „O aplikaci“.

Používá [morse-pro](https://github.com/scp93ch/morse-pro) © Stephen C. Phillips (EUPL-1.2),
Flask (BSD-3-Clause), Waitress (ZPL-2.1), argon2-cffi + argon2-cffi-bindings + cffi (MIT), pycparser (BSD-3-Clause),
SQLite (public domain), nginx (BSD-2-Clause).
Metodika inspirována projekty [LCWO.net](https://lcwo.net/), [morsecode.world](https://morsecode.world/),
CWops CW Academy a Long Island CW Club.
