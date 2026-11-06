#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Public access via Pinggy (run: sudo deploy/pinggy-setup.sh, also after changing MORSE_PUBLIC_URL in site.env).
# Installs the public nginx entry (127.0.0.1:8090 only) and the morse-pinggy service. Does not start the tunnel itself.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run it with sudo."; exit 1; }
source "$(dirname "$0")/common.sh"
cd "$DIR"
ensure_site_env
load_site_env
[[ -n "$PUBLIC_HOST" ]] || { echo "MORSE_PUBLIC_URL is missing in $SITE_ENV (https://<subdomain>.a.pinggy.link/)."; exit 1; }

install -m 644 deploy/pinggy-proxy.conf /etc/morse-trainer/pinggy-proxy.conf
printf '%s 1;\n' "$PUBLIC_HOST" > /etc/morse-trainer/pinggy-host.map; chmod 644 /etc/morse-trainer/pinggy-host.map
rm -f /etc/morse-trainer/pinggy.htpasswd   # E3: a shared web password is no longer used
cp deploy/nginx-morse-trainer.conf /etc/nginx/sites-available/morse-trainer
nginx -t
systemctl reload nginx

if [[ ! -f /etc/morse-trainer/pinggy.env ]]; then
  install -m 600 /dev/null /etc/morse-trainer/pinggy.env
  cat > /etc/morse-trainer/pinggy.env <<'ENV'
# Pinggy – fill in and save (sudo nano /etc/morse-trainer/pinggy.env). Only root reads the file. Never share it.
# Token from dashboard.pinggy.io (the one with the permanent subdomain):
PINGGY_TOKEN=
ENV
  echo "Created /etc/morse-trainer/pinggy.env – fill in the token."
fi
install -m 700 -o "$APP_USER" -g "$APP_USER" -d "$APP_HOME/.ssh"
touch "$APP_HOME/.ssh/known_hosts_pinggy" && chown "$APP_USER:$APP_USER" "$APP_HOME/.ssh/known_hosts_pinggy"
install_unit morse-pinggy.service
systemctl daemon-reload
systemctl restart morse-trainer   # loads the addresses from site.env
echo "Done (public address https://${PUBLIC_HOST}/)."
echo "Tunel: sudo systemctl enable --now morse-pinggy | odpojit: sudo systemctl stop morse-pinggy"
ss -tln | grep -q '127.0.0.1:8090' && echo "The public nginx entry listens only on 127.0.0.1:8090 – OK."
