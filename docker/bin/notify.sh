#!/bin/sh
set -eu

MSG=${1:-"Job failed"}
LOG=${2:-}

if [ -n "${LOG}" ] && [ -f "$LOG" ]; then
  TAIL=$(tail -n 50 "$LOG" | sed 's/"/\\"/g')
  BODY="{\"text\":\"${MSG}\n\n${TAIL}\"}"
else
  BODY="{\"text\":\"${MSG}\"}"
fi

curl -s -X POST -H "Content-Type: application/json" -d "$BODY" "${NOTIFY_WEBHOOK_URL}"

