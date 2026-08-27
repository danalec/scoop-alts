#!/bin/sh
set -eu

# Heartbeat is written every 12h (HEARTBEAT_SCHEDULE); treat the container as
# healthy while the heartbeat is newer than 13h. If the cron dies the file goes
# stale and the container reports unhealthy.
NOW=$(date +%s)
if [ -f /data/heartbeat ]; then
  LAST=$(cat /data/heartbeat)
  AGE=$((NOW - LAST))
  [ "$AGE" -le 46800 ] && exit 0 || exit 1
else
  exit 1
fi

