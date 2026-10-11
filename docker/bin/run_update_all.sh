#!/bin/sh
set -eu

: "${ORCHESTRATOR_FLAGS:=}"
: "${SYNC_BRANCH:=main}"
: "${SYNC_REMOTE:=origin}"

TIMESTAMP=$(date +%F_%H%M%S)
OUT="/data/logs/update-all-${TIMESTAMP}.log"

# The scheduler is the only writer of this branch, so it must start from the
# current tip before committing: a stale checkout turns every push into a
# non-fast-forward rejection. Only manifest changes are ever discarded here --
# scripts and workflow files are never edited by the orchestrator.
if [ -d /app/.git ]; then
  if git -C /app fetch --quiet "${SYNC_REMOTE}" "${SYNC_BRANCH}"; then
    git -C /app reset --hard --quiet "${SYNC_REMOTE}/${SYNC_BRANCH}" || \
      echo "WARN: could not reset to ${SYNC_REMOTE}/${SYNC_BRANCH}; continuing with local state" >&2
  else
    echo "WARN: could not fetch ${SYNC_REMOTE}/${SYNC_BRANCH}; continuing with local state" >&2
  fi
fi

if python -u /app/scripts/update-all.py ${ORCHESTRATOR_FLAGS} >"$OUT" 2>&1; then
  ln -sf "$OUT" /data/logs/update-all-latest.log
  date -Iseconds > /data/last_success_update_all
else
  date -Iseconds > /data/last_failure_update_all
  if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
    /usr/local/scoop-bin/notify.sh "update-all failed" "$OUT"
  fi
  exit 1
fi
