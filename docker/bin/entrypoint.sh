#!/bin/sh
set -eu

: "${SCHEDULE_UPDATE_ALL:=0 * * * *}"
: "${HEARTBEAT_SCHEDULE:=*/5 * * * *}"

mkdir -p /var/spool/cron/crontabs /data/logs

# SSH setup for git push (deploy key + host key policy). The repo is expected
# to be mounted at /app; its `origin` may carry multiple push URLs (Forgejo +
# GitHub) so a plain `git push` publishes to both.
if [ -f /data/deploy_key ]; then
  mkdir -p /root/.ssh
  cp /data/deploy_key /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519
  printf 'Host *\n  StrictHostKeyChecking accept-new\n  IdentityFile /root/.ssh/id_ed25519\n  User git\n' > /root/.ssh/config
  chmod 600 /root/.ssh/config
  if [ -d /app/.git ]; then
    git -C /app config user.name "scoop-alts-scheduler"
    git -C /app config user.email "scoop-alts-scheduler@localhost"
  fi
fi

CRONFILE=/var/spool/cron/crontabs/root
{
  echo "${SCHEDULE_UPDATE_ALL} /app/bin/run_update_all.sh"
  echo "${HEARTBEAT_SCHEDULE} date +%s > /data/heartbeat"
} > "$CRONFILE"

chmod 600 "$CRONFILE"

exec busybox crond -f -l 8 -L /var/log/cron.log
