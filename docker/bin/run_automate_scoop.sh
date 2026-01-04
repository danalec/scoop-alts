#!/bin/sh
set -eu

: "${AUTOMATE_FLAGS:=generate-all}"

TIMESTAMP=$(date +%F_%H%M%S)
OUT="/data/logs/automate-scoop-${TIMESTAMP}.log"

if python -u /app/scripts/automate-scoop.py ${AUTOMATE_FLAGS} >"$OUT" 2>&1; then
  ln -sf "$OUT" /data/logs/automate-scoop-latest.log
  date -Iseconds > /data/last_success_automate_scoop
else
  date -Iseconds > /data/last_failure_automate_scoop
  if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
    /app/bin/notify.sh "automate-scoop failed" "$OUT"
  fi
  exit 1
fi

