# Docker Container Scheduler

## Overview
- Runs update-all.py on a schedule; automate-scoop.py is manual (on-demand)
- Uses busybox crond for scheduling inside container
- Provides logging, health checks, and optional webhook notifications

## Files
- Dockerfile
- docker-compose.yml
- docker/bin/*

## Build and Run
1. docker compose build
2. docker compose up -d

## Configuration
- SCHEDULE_UPDATE_ALL: cron expression for update-all.py
- HEARTBEAT_SCHEDULE: cron expression for heartbeat
- ORCHESTRATOR_FLAGS: flags for update-all.py
- NOTIFY_WEBHOOK_URL: optional webhook for failures

## Volumes
- ./scripts mounted read-only at /app/scripts
- ./bucket mounted at /app/bucket
- ./logs mounted at /data/logs
- ./cache mounted at /data/cache

## Health Check
- Fails if /data/heartbeat is older than 10 minutes

## Updating Scripts
- Edit local scripts; container uses bind-mounted scripts
- Restart container if schedules or environment change

## Manual: Add/Expand Bucket Recipes
- Run wizard:
  - docker compose exec scheduler python -u /app/scripts/automate-scoop.py wizard
- Generate update scripts/manifests for selected software:
  - docker compose exec scheduler python -u /app/scripts/automate-scoop.py generate-all --software app1 app2
- Validate manifests:
  - docker compose exec scheduler python -u /app/scripts/automate-scoop.py validate
- Test update scripts:
  - docker compose exec scheduler python -u /app/scripts/automate-scoop.py test

Convenience:
- You may also run: docker compose exec scheduler /app/bin/run_automate_scoop.sh
