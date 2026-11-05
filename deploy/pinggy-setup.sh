#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Veřejný přístup přes Pinggy (spustit: sudo deploy/pinggy-setup.sh, i po změně MORSE_PUBLIC_URL v site.env).
# Nainstaluje veřejný vstup nginx (jen 127.0.0.1:8090) a službu morse-pinggy. Tunel sám nezapíná.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Spusť přes sudo."; exit 1; }
source "$(dirname "$0")/common.sh"
cd "$DIR"
ensure_site_env
load_site_env
[[ -n "$PUBLIC_HOST" ]] || { echo "V $SITE_ENV chybí MORSE_PUBLIC_URL (https://<subdomena>.a.pinggy.link/)."; exit 1; }

install -m 644 deploy/pinggy-proxy.conf /etc/morse-trainer/pinggy-proxy.conf
printf '%s 1;\n' "$PUBLIC_HOST" > /etc/morse-trainer/pinggy-host.map; chmod 644 /etc/morse-trainer/pinggy-host.map
rm -f /etc/morse-trainer/pinggy.htpasswd   # E3: sdílené heslo k webu se už nepoužívá
cp deploy/nginx-morse-trainer.conf /etc/nginx/sites-available/morse-trainer
nginx -t
systemctl reload nginx

if [[ ! -f /etc/morse-trainer/pinggy.env ]]; then
  install -m 600 /dev/null /etc/morse-trainer/pinggy.env
  cat > /etc/morse-trainer/pinggy.env <<'ENV'
# Pinggy – doplň a ulož (sudo nano /etc/morse-trainer/pinggy.env). Soubor čte jen root. Nikam ho nesdílej.
# Token z dashboard.pinggy.io (ten s trvalou subdoménou):
PINGGY_TOKEN=
ENV
  echo "Vytvořen /etc/morse-trainer/pinggy.env – doplň token."
fi
install -m 700 -o "$APP_USER" -g "$APP_USER" -d "$APP_HOME/.ssh"
touch "$APP_HOME/.ssh/known_hosts_pinggy" && chown "$APP_USER:$APP_USER" "$APP_HOME/.ssh/known_hosts_pinggy"
install_unit morse-pinggy.service
systemctl daemon-reload
systemctl restart morse-trainer   # načte adresy ze site.env
echo "Hotovo (veřejná adresa https://${PUBLIC_HOST}/)."
echo "Tunel: sudo systemctl enable --now morse-pinggy | odpojit: sudo systemctl stop morse-pinggy"
ss -tln | grep -q '127.0.0.1:8090' && echo "Veřejný vstup nginx poslouchá jen na 127.0.0.1:8090 – OK."
