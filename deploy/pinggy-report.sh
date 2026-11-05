#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Přehled přístupů zvenku přes Pinggy (týdenní kontrola). Spuštění: sudo deploy/pinggy-report.sh
# Čte /var/log/nginx/morse-pinggy.log (+ předchozí rotaci).
set -euo pipefail
LOGS=$(ls /var/log/nginx/morse-pinggy.log /var/log/nginx/morse-pinggy.log.1 2>/dev/null || true)
[[ -n "$LOGS" ]] || { echo "Log zatím neexistuje."; exit 0; }
echo "== Služba tunelu: $(systemctl is-active morse-pinggy) / autostart: $(systemctl is-enabled morse-pinggy)"
echo "== Požadavky podle IP (nejčastější):"
cat $LOGS | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Stavové kódy:"
cat $LOGS | grep -o '" [0-9]\{3\} ' | tr -d '"' | sort | uniq -c | sort -rn
echo "== Neúspěšná přihlášení do aplikace (403 na /api/login) podle IP:"
cat $LOGS | grep -E '"POST /api/login[^"]*" 403' | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Omezení / blokace (429) podle IP (aplikace blokuje IP po 30 chybách na 24 h):"
cat $LOGS | grep '" 429 ' | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Odmítnutá cizí jména (444):"
cat $LOGS | grep -c '" 444 ' || true
