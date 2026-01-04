#!/bin/sh
set -eu

NOW=$(date +%s)
if [ -f /data/heartbeat ]; then
  LAST=$(cat /data/heartbeat)
  AGE=$((NOW - LAST))
  [ "$AGE" -le 600 ] && exit 0 || exit 1
else
  exit 1
fi

