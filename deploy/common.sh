# SPDX-License-Identifier: EUPL-1.2
# Shared by the deployment scripts (source). Service user = owner of the application directory, addresses from site.env.
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_USER=$(stat -c %U "$DIR")
APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
SITE_ENV=/etc/morse-trainer/site.env
[[ "$APP_USER" != root ]] || { echo "The application directory must not belong to root (the service runs as a normal user)."; exit 1; }

# Creates site.env with estimated values (IP and network of the Pi) if it does not exist yet.
ensure_site_env() {
  [[ -f "$SITE_ENV" ]] && return 0
  local ip lan
  ip=$(hostname -I | tr ' ' '\n' | grep -m1 -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)
  lan=$(ip -4 route | awk -v ip="$ip" '$0 ~ "src "ip && $1 ~ /\// {print $1; exit}')
  mkdir -p /etc/morse-trainer
  sed -e "s#^MORSE_HOME_URL=.*#MORSE_HOME_URL=https://${ip:-127.0.0.1}/#" \
      -e "s#^MORSE_LAN=.*#MORSE_LAN=${lan:-192.168.0.0/24}#" "$DIR/deploy/site.env.example" > "$SITE_ENV"
  chmod 644 "$SITE_ENV"
  echo "Created $SITE_ENV (home address https://${ip}/, network ${lan}) – check it: sudo nano $SITE_ENV"
}

load_site_env() {
  MORSE_HOME_URL=$(sed -n 's/^MORSE_HOME_URL=//p' "$SITE_ENV")
  MORSE_LAN=$(sed -n 's/^MORSE_LAN=//p' "$SITE_ENV")
  MORSE_PUBLIC_URL=$(sed -n 's/^MORSE_PUBLIC_URL=//p' "$SITE_ENV")
  PUBLIC_HOST=$(printf '%s' "$MORSE_PUBLIC_URL" | sed -E 's#^https?://##; s#[:/].*$##')
}

# Z-18c (0.10.18): fingerprint of the deployed files → /etc/morse-trainer/deployed.json (python -m tools.deployed
# then tells "deploy/ is newer, run install.sh" from "edited by hand after the installation")
record_deployed() {
  local tmp
  tmp=$(mktemp)
  if sudo -u "$APP_USER" "$DIR/.venv/bin/python" -m tools.deployed --record > "$tmp"; then
    install -m 644 "$tmp" /etc/morse-trainer/deployed.json
  else
    echo "Warning: the fingerprint of the deployed files was not recorded."
  fi
  rm -f "$tmp"
}

# Ignores comment lines (the unit comments were translated in 0.9.0 – a restart only for a real change)
unit_body() { grep -v '^[[:space:]]*#' "$1" 2>/dev/null || true; }

# Service template → /etc/systemd/system (fills in @USER@, @DIR@, @HOME@)
install_unit() {
  sed -e "s#@USER@#$APP_USER#g" -e "s#@DIR@#$DIR#g" -e "s#@HOME@#$APP_HOME#g" "$DIR/deploy/$1" \
    > "/etc/systemd/system/$1"
  chmod 644 "/etc/systemd/system/$1"
}
