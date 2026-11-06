#!/bin/bash
# SPDX-License-Identifier: EUPL-1.2
# Deployment of the Morse trainer on a Raspberry Pi (run by hand: sudo deploy/install.sh).
# What it does:
#   0) /etc/morse-trainer/site.env – addresses of this installation (on the first run it estimates the IP and network of the Pi)
#   1) certificates (only if not present yet) – own CA restricted to the home network
#   2) nginx site: HTTPS 443 + HTTP 80 (only CA download + redirect), disables the default nginx site
#   3) ufw firewall (if installed): ports 80 and 443 allowed only from the home network (MORSE_LAN)
#   4) Python dependencies into .venv (as the directory owner) and the database (migrations)
#   5) systemd service morse-trainer (waitress on 127.0.0.1:8080), starts also after a reboot of the Pi
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run it with sudo."; exit 1; }
source "$(dirname "$0")/common.sh"
cd "$DIR"
ensure_site_env
load_site_env

[[ -d .venv ]] || sudo -u "$APP_USER" python3 -m venv --system-site-packages .venv
sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt
sudo -u "$APP_USER" .venv/bin/python -c "from server import db; c = db.connect(); db.migrate(c)"

[[ -f /etc/morse-trainer/pki/server.crt ]] || deploy/make-certs.sh
[[ -f /etc/morse-trainer/public/morse-ca.crt ]] || install -m 644 /etc/morse-trainer/pki/ca.crt /etc/morse-trainer/public/morse-ca.crt

install -m 644 deploy/pinggy-proxy.conf /etc/morse-trainer/pinggy-proxy.conf  # headers of the public entry
{ [[ -z "$PUBLIC_HOST" ]] || printf '%s 1;\n' "$PUBLIC_HOST"; } > /etc/morse-trainer/pinggy-host.map  # allowed public host name
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
  echo "No administrator yet. Invitation for an administrator:"
  sudo -u "$APP_USER" .venv/bin/python -m server.admin invite admin
fi
