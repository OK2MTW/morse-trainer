#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# Overview of access from outside via Pinggy (weekly check). Run: sudo deploy/pinggy-report.sh
# Reads /var/log/nginx/morse-pinggy.log (+ the previous rotation).
set -euo pipefail
LOGS=$(ls /var/log/nginx/morse-pinggy.log /var/log/nginx/morse-pinggy.log.1 2>/dev/null || true)
[[ -n "$LOGS" ]] || { echo "The log does not exist yet."; exit 0; }
echo "== Tunnel service: $(systemctl is-active morse-pinggy) / autostart: $(systemctl is-enabled morse-pinggy)"
echo "== Requests by IP (most frequent):"
cat $LOGS | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Status codes:"
cat $LOGS | grep -o '" [0-9]\{3\} ' | tr -d '"' | sort | uniq -c | sort -rn
echo "== Failed logins to the app (403 on /api/login) by IP:"
cat $LOGS | grep -E '"POST /api/login[^"]*" 403' | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Limits / blocks (429) by IP (the app blocks an IP after 30 failures for 24 h):"
cat $LOGS | grep '" 429 ' | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
echo "== Rejected foreign host names (444):"
cat $LOGS | grep -c '" 444 ' || true
