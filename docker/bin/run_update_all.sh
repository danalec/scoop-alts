#!/bin/sh
set -eu

: "${ORCHESTRATOR_FLAGS:=}"
: "${SYNC_BRANCH:=main}"
: "${SYNC_REMOTE:=origin}"
: "${REPO_DIR:=/app/repo}"

TIMESTAMP=$(date +%F_%H%M%S)
OUT="/data/logs/update-all-${TIMESTAMP}.log"

# The scheduler is the only writer of this branch, so it must start from the
# current tip before committing: a stale checkout turns every push into a
# non-fast-forward rejection. The reset runs on the scheduler's own clone
# (REPO_DIR), never on the working tree of the repository checkout.
if [ -d "${REPO_DIR}/.git" ]; then
  if git -C "${REPO_DIR}" fetch --quiet "${SYNC_REMOTE}" "${SYNC_BRANCH}"; then
    git -C "${REPO_DIR}" checkout -B "${SYNC_BRANCH}" "${SYNC_REMOTE}/${SYNC_BRANCH}" --quiet
    git -C "${REPO_DIR}" reset --hard --quiet "${SYNC_REMOTE}/${SYNC_BRANCH}" || \
      echo "WARN: could not reset to ${SYNC_REMOTE}/${SYNC_BRANCH}; continuing with local state" >&2
  else
    echo "WARN: could not fetch ${SYNC_REMOTE}/${SYNC_BRANCH}; continuing with local state" >&2
  fi
fi

if python -u "${REPO_DIR}/scripts/update-all.py" ${ORCHESTRATOR_FLAGS} >"$OUT" 2>&1; then
  # A relative target, so the symlink also resolves from the host mount.
  ln -sf "$(basename "$OUT")" /data/logs/update-all-latest.log
  date -Iseconds > /data/last_success_update_all
else
  date -Iseconds > /data/last_failure_update_all
  if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
    /usr/local/scoop-bin/notify.sh "update-all failed" "$OUT"
  fi
  exit 1
fi
