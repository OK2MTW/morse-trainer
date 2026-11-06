#!/bin/bash
# SPDX-License-Identifier: EUPL-1.2
# Creates an own certificate authority (CA) for the LAN and a server certificate.
# The CA is restricted (nameConstraints) to the home network only (MORSE_LAN from site.env), *.local and localhost,
# so even if its key leaked, it could not sign a certificate for a foreign site (google.com etc.).
# Run as root:  sudo deploy/make-certs.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run it with sudo."; exit 1; }
source "$(dirname "$0")/common.sh"
ensure_site_env
load_site_env
LAN_IP=${MORSE_LAN%/*}
LAN_MASK=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_network(sys.argv[1], strict=False).netmask)" "$MORSE_LAN")
SAN_IPS=$(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | sed 's/^/IP:/' | paste -sd, -)
PKI=/etc/morse-trainer/pki
PUB=/etc/morse-trainer/public
mkdir -p "$PKI" "$PUB"
chmod 700 "$PKI"; chmod 755 "$PUB"
cd "$PKI"

if [[ ! -f ca.key ]]; then
  echo "== Creating the CA (valid for 10 years)"
  openssl ecparam -name prime256v1 -genkey -noout -out ca.key
  chmod 600 ca.key
  cat > ca.cnf <<EOF
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no
[dn]
CN = Morse trenazer - domaci CA
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, permitted;IP:${LAN_IP}/${LAN_MASK}, permitted;IP:127.0.0.0/255.0.0.0, permitted;DNS:.local, permitted;DNS:localhost
EOF
  openssl req -x509 -new -key ca.key -sha256 -days 3650 -config ca.cnf -out ca.crt
fi

echo "== Creating the server certificate (valid for 397 days)"
HOST=$(hostname | tr 'A-Z' 'a-z')
openssl ecparam -name prime256v1 -genkey -noout -out server.key
chmod 600 server.key
cat > server.cnf <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ${HOST}.local
[v3]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = ${SAN_IPS:+${SAN_IPS}, }IP:127.0.0.1, DNS:${HOST}.local, DNS:localhost
EOF
openssl req -new -key server.key -config server.cnf -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 397 -sha256 \
  -extfile server.cnf -extensions v3 -out server.crt
cat server.crt ca.crt > server-chain.crt

# Public part of the CA for downloading to a phone (DER and PEM)
cp ca.crt "$PUB/morse-ca.crt"
openssl x509 -in ca.crt -outform der -out "$PUB/morse-ca.der.crt"
chmod 644 "$PUB"/*
echo "== Done. CA fingerprint (SHA-256) – check it on the phone during installation:"
openssl x509 -in ca.crt -noout -fingerprint -sha256
