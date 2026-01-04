#!/bin/sh
set -eu

: "${SCHEDULE_UPDATE_ALL:=0 * * * *}"
: "${HEARTBEAT_SCHEDULE:=*/5 * * * *}"

mkdir -p /var/spool/cron/crontabs /data/logs

CRONFILE=/var/spool/cron/crontabs/root
{
  echo "${SCHEDULE_UPDATE_ALL} /app/bin/run_update_all.sh"
  echo "${HEARTBEAT_SCHEDULE} date +%s > /data/heartbeat"
} > "$CRONFILE"

chmod 600 "$CRONFILE"

exec busybox crond -f -l 8 -L /var/log/cron.log
