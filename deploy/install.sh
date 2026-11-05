#!/bin/bash
# SPDX-License-Identifier: EUPL-1.2
# Nasazení Morse trenažeru na Raspberry Pi (spustit ručně: sudo deploy/install.sh).
# Co udělá:
#   0) /etc/morse-trainer/site.env – adresy této instalace (při prvním spuštění odhadne IP a síť Pi)
#   1) certifikáty (jen pokud ještě nejsou) – vlastní CA omezená na domácí síť
#   2) nginx web: HTTPS 443 + HTTP 80 (jen stažení CA + přesměrování), výchozí web nginx vypne
#   3) firewall ufw (je-li nainstalován): porty 80 a 443 povolí jen z domácí sítě (MORSE_LAN)
#   4) Python závislosti do .venv (jako vlastník adresáře) a databáze (migrace)
#   5) systemd služba morse-trainer (waitress na 127.0.0.1:8080), start i po restartu Pi
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Spusť přes sudo."; exit 1; }
source "$(dirname "$0")/common.sh"
cd "$DIR"
ensure_site_env
load_site_env

[[ -d .venv ]] || sudo -u "$APP_USER" python3 -m venv --system-site-packages .venv
sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt
sudo -u "$APP_USER" .venv/bin/python -c "from server import db; c = db.connect(); db.migrate(c)"

[[ -f /etc/morse-trainer/pki/server.crt ]] || deploy/make-certs.sh
[[ -f /etc/morse-trainer/public/morse-ca.crt ]] || install -m 644 /etc/morse-trainer/pki/ca.crt /etc/morse-trainer/public/morse-ca.crt

install -m 644 deploy/pinggy-proxy.conf /etc/morse-trainer/pinggy-proxy.conf  # hlavičky veřejného vstupu
{ [[ -z "$PUBLIC_HOST" ]] || printf '%s 1;\n' "$PUBLIC_HOST"; } > /etc/morse-trainer/pinggy-host.map  # povolené veřejné jméno
chmod 644 /etc/morse-trainer/pinggy-host.map
cp deploy/nginx-morse-trainer.conf /etc/nginx/sites-available/morse-trainer
ln -sf /etc/nginx/sites-available/morse-trainer /etc/nginx/sites-enabled/morse-trainer
rm -f /etc/nginx/sites-enabled/default
nginx -t

if command -v ufw >/dev/null; then
  ufw allow from "$MORSE_LAN" to any port 80 proto tcp comment 'Morse trenazer HTTP - LAN'
  ufw allow from "$MORSE_LAN" to any port 443 proto tcp comment 'Morse trenazer HTTPS - LAN'
fi

install_unit morse-trainer.service
systemctl daemon-reload
systemctl enable --now morse-trainer
systemctl restart morse-trainer
systemctl reload nginx

for i in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:8080/api/health && break; sleep 1; done
systemctl --no-pager --lines=0 status morse-trainer nginx | grep -E '●|Active'
curl -sk https://127.0.0.1/api/health && echo
HOMEHOST=$(printf '%s' "$MORSE_HOME_URL" | sed -E 's#^https?://##; s#/.*$##')
echo "Hotovo: ${MORSE_HOME_URL}   (CA pro telefon: http://${HOMEHOST}/ca.crt)"
if ! sudo -u "$APP_USER" .venv/bin/python -c "from server import db; import sys; sys.exit(0 if db.connect().execute(\"SELECT 1 FROM users WHERE role='admin'\").fetchone() else 1)"; then
  echo "Zatím žádný správce. Pozvánka pro správce:"
  sudo -u "$APP_USER" .venv/bin/python -m server.admin pozvanka admin
fi
