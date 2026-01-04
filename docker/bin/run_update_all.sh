#!/bin/sh
set -eu

: "${ORCHESTRATOR_FLAGS:=}"

TIMESTAMP=$(date +%F_%H%M%S)
OUT="/data/logs/update-all-${TIMESTAMP}.log"

if python -u /app/scripts/update-all.py ${ORCHESTRATOR_FLAGS} >"$OUT" 2>&1; then
  ln -sf "$OUT" /data/logs/update-all-latest.log
  date -Iseconds > /data/last_success_update_all
else
  date -Iseconds > /data/last_failure_update_all
  if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
    /app/bin/notify.sh "update-all failed" "$OUT"
  fi
  exit 1
fi

