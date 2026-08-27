#!/bin/sh
set -eu

# Healthy while the cron daemon (PID 1) is alive — independent of the
# heartbeat timestamp, so the status is green immediately after start.
kill -0 1

