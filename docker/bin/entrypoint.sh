#!/bin/sh
set -eu

: "${SCHEDULE_UPDATE_ALL:=0 * * * *}"
: "${HEARTBEAT_SCHEDULE:=*/5 * * * *}"
: "${REPO_DIR:=/app/repo}"

mkdir -p /var/spool/cron/crontabs /data/logs

# SSH setup for git push (deploy key + host key policy).
if [ -f /data/deploy_key ]; then
  mkdir -p /root/.ssh
  cp /data/deploy_key /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519
  {
    echo 'Host *'
    echo '  StrictHostKeyChecking accept-new'
    echo '  IdentityFile /root/.ssh/id_ed25519'
    echo '  User git'
    # A forge that serves git over SSH on a non-default port needs its own
    # block: SSH matches the most specific Host pattern, and "Host *" would
    # otherwise send the forge request to port 22. The alias is what the push
    # url uses, so the same name has to be configured on the host as well.
    if [ -n "${DEPLOY_KEY_SSH_HOST:-}" ]; then
      echo "Host ${DEPLOY_KEY_SSH_HOST}"
      if [ -n "${DEPLOY_KEY_SSH_HOSTNAME:-}" ]; then
        echo "  HostName ${DEPLOY_KEY_SSH_HOSTNAME}"
      fi
      if [ -n "${DEPLOY_KEY_SSH_PORT:-}" ]; then
        echo "  Port ${DEPLOY_KEY_SSH_PORT}"
      fi
      echo '  User git'
      echo '  IdentityFile /root/.ssh/id_ed25519'
      echo '  StrictHostKeyChecking accept-new'
    fi
  } > /root/.ssh/config
  chmod 600 /root/.ssh/config
fi

# The scheduler keeps its own clone of the repository.
#
# Sharing the developer's working tree does not work: the runner starts with
# "git reset --hard origin/main", and that discards whatever is checked out
# there - a branch in progress, uncommitted edits, everything. The clone lives
# in a volume, so the runner publishes from its own checkout and the working
# tree of whoever is developing in the repository is never touched.
if [ -n "${REPO_URL:-}" ]; then
  if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning $REPO_URL into $REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
  fi
  # Keep the clone tracking REPO_URL even when it was cloned earlier from a
  # different remote, so the runner always starts from the current tip.
  git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
  git -C "$REPO_DIR" config user.name "scoop-alts-scheduler"
  git -C "$REPO_DIR" config user.email "scoop-alts-scheduler@localhost"
  # The clone inherits a single push url; the scheduler may publish to more
  # than one remote (forge + upstream), so the list is explicit.
  if [ -n "${REPO_PUSH_URLS:-}" ]; then
    git -C "$REPO_DIR" config --unset-all remote.origin.pushurl 2>/dev/null || true
    for url in $(echo "$REPO_PUSH_URLS" | tr ',' ' '); do
      git -C "$REPO_DIR" config --add remote.origin.pushurl "$url"
    done
  fi
  git -C "$REPO_DIR" fetch --quiet origin
fi

CRONFILE=/var/spool/cron/crontabs/root
{
  # busybox crond propagates the daemon env to jobs, but pin the token into
  # the crontab as well so the job keeps working even if env handling changes
  # or the image swaps cron implementations.
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo "GITHUB_TOKEN=$GITHUB_TOKEN"
  fi
  echo "${SCHEDULE_UPDATE_ALL} /usr/local/scoop-bin/run_update_all.sh"
  echo "${HEARTBEAT_SCHEDULE} date +%s > /data/heartbeat"
} > "$CRONFILE"

chmod 600 "$CRONFILE"

exec busybox crond -f -l 8 -L /var/log/cron.log
