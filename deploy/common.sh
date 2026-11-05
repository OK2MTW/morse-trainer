# SPDX-License-Identifier: EUPL-1.2
# Společné pro nasazovací skripty (source). Uživatel služby = vlastník adresáře aplikace, adresy z site.env.
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_USER=$(stat -c %U "$DIR")
APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
SITE_ENV=/etc/morse-trainer/site.env
[[ "$APP_USER" != root ]] || { echo "Adresář aplikace nesmí patřit rootovi (služba běží jako běžný uživatel)."; exit 1; }

# Vytvoří site.env s odhadnutými hodnotami (IP a síť Pi), pokud ještě není.
ensure_site_env() {
  [[ -f "$SITE_ENV" ]] && return 0
  local ip lan
  ip=$(hostname -I | tr ' ' '\n' | grep -m1 -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)
  lan=$(ip -4 route | awk -v ip="$ip" '$0 ~ "src "ip && $1 ~ /\// {print $1; exit}')
  mkdir -p /etc/morse-trainer
  sed -e "s#^MORSE_HOME_URL=.*#MORSE_HOME_URL=https://${ip:-127.0.0.1}/#" \
      -e "s#^MORSE_LAN=.*#MORSE_LAN=${lan:-192.168.0.0/24}#" "$DIR/deploy/site.env.example" > "$SITE_ENV"
  chmod 644 "$SITE_ENV"
  echo "Vytvořen $SITE_ENV (domácí adresa https://${ip}/, síť ${lan}) – zkontroluj: sudo nano $SITE_ENV"
}

load_site_env() {
  MORSE_HOME_URL=$(sed -n 's/^MORSE_HOME_URL=//p' "$SITE_ENV")
  MORSE_LAN=$(sed -n 's/^MORSE_LAN=//p' "$SITE_ENV")
  MORSE_PUBLIC_URL=$(sed -n 's/^MORSE_PUBLIC_URL=//p' "$SITE_ENV")
  PUBLIC_HOST=$(printf '%s' "$MORSE_PUBLIC_URL" | sed -E 's#^https?://##; s#[:/].*$##')
}

# Šablona služby → /etc/systemd/system (doplní @USER@, @DIR@, @HOME@)
install_unit() {
  sed -e "s#@USER@#$APP_USER#g" -e "s#@DIR@#$DIR#g" -e "s#@HOME@#$APP_HOME#g" "$DIR/deploy/$1" \
    > "/etc/systemd/system/$1"
  chmod 644 "/etc/systemd/system/$1"
}
