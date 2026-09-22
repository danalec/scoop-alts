# Docker Container Scheduler Guide

This guide details the deployment and operational lifecycle of the containerized automation runner for **Dan's Alternative Scoop Bucket (`scoop-alts`)**.

The scheduler runs periodic update sweeps across all package manifests, validates generated schemas, records persistent audit logs, and automatically commits and pushes fresh manifests to Git.

---

## 🏗️ Architecture Overview

The scheduler service is packaged as a lightweight Linux container based on `python:3.12-slim` utilizing BusyBox `crond` to manage scheduled updates:

```text
┌─────────────────────────────────────────────────────────────┐
│                      Docker Container                       │
│  ┌─────────────────┐       ┌──────────────────────────────┐ │
│  │  BusyBox crond  │ ───>  │ scripts/update-all.py        │ │
│  └─────────────────┘       │ (Periodic manifest updates)  │ │
│           │                └──────────────────────────────┘ │
│           │                               │                 │
│           v                               v                 │
│  ┌─────────────────┐       ┌──────────────────────────────┐ │
│  │ /data/heartbeat │       │ Git SSH Deploy Key           │ │
│  │ (Healthcheck)   │       │ (Pushes commits to upstream) │ │
│  └─────────────────┘       └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
          │                                  │
          v                                  v
  Persistent Volumes:                Remote Git Remotes:
  - /data/logs                       - Forgejo (Unraid)
  - /data/cache                      - GitHub
```

---

## 🚀 Deployment

### 1. `docker-compose.yml` Specification

A standard deployment uses the provided [`docker-compose.yml`](../docker-compose.yml):

```yaml
version: '3.8'

services:
  scheduler:
    build: .
    container_name: scoop-alts-scheduler
    restart: unless-stopped
    environment:
      - SCHEDULE_UPDATE_ALL=0 * * * *        # Run every hour
      - HEARTBEAT_SCHEDULE=*/5 * * * *        # Healthcheck heartbeat every 5 minutes
      - ORCHESTRATOR_FLAGS=--workers 6 --structured-output --retry 2
      - NOTIFY_WEBHOOK_URL=                  # Optional notification webhook
      - SCOOP_GIT_REMOTE=origin
      - SCOOP_GIT_BRANCH=master
      - GITHUB_TOKEN=                         # Optional GitHub PAT for higher API limits
    volumes:
      - .:/app                                # Repository root (required for git auto-commit)
      - ./scripts:/app/scripts:ro
      - ./bucket:/app/bucket:rw
      - /mnt/user/data/scoop-alts-logs:/data/logs:rw
      - /mnt/user/data/scoop-alts-cache:/data/cache:rw
      - /mnt/user/data/scoop-alts-config/deploy_key:/data/deploy_key:ro
```

### 2. Starting the Service

```bash
# Build and start container in detached mode
docker compose up -d --build

# View real-time container logs
docker compose logs -f scheduler
```

---

## ⚙️ Environment Variables Reference

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SCHEDULE_UPDATE_ALL` | `0 * * * *` | Cron expression controlling how frequently `update-all.py` executes. |
| `HEARTBEAT_SCHEDULE` | `*/5 * * * *` | Cron expression refreshing `/data/heartbeat` for container health monitoring. |
| `ORCHESTRATOR_FLAGS` | `""` | Command-line flags passed directly to `update-all.py`. |
| `NOTIFY_WEBHOOK_URL` | `""` | Destination webhook URL (Discord, Slack, or generic JSON) for run reports. |
| `SCOOP_GIT_REMOTE` | `origin` | Target Git remote name to push automatic version update commits to. |
| `SCOOP_GIT_BRANCH` | `master` | Target Git branch to push updates to. |
| `GITHUB_TOKEN` | `""` | GitHub Personal Access Token to avoid rate limits during version discovery. |
| `AUTOMATION_DISABLE_WINMETA` | `1` | Disables Windows-specific binary inspection when running on Linux containers. |

> **Supplying `GITHUB_TOKEN`:** create a `.env` file next to `docker-compose.yml`
> (gitignored by default) with `GITHUB_TOKEN=ghp_...`, or export it in the host
> shell before `docker compose up`. A fine-grained PAT with **no permissions**
> is enough — the bucket only queries public release APIs, and the token only
> raises the hourly quota from 60 to 5,000 requests. The compose file forwards
> it into the container, and the entrypoint pins it into the crontab so the
> scheduled job always sees it. Without it, hourly runs share the 60-request
> anonymous quota per IP and can fail mid-run once it is exhausted.

---

## 💾 Storage & Persistent Volumes

| Container Mount | Recommended Host Path | Purpose | Access Mode |
| :--- | :--- | :--- | :---: |
| `/app` | `.` (repository root) | Repository root so the entrypoint finds `/app/.git` for auto-commit/push | Read-Write (`rw`) |
| `/app/scripts` | `./scripts` | Python automation modules and updaters | Read-Only (`ro`) |
| `/app/bucket` | `./bucket` | Scoop JSON manifest files to update | Read-Write (`rw`) |
| `/data/logs` | `.../scoop-alts-logs` | Run summaries, orchestrator logs, and stdout | Read-Write (`rw`) |
| `/data/cache` | `.../scoop-alts-cache` | Cached HTTP responses and ETag storage | Read-Write (`rw`) |
| `/data/deploy_key` | `.../deploy_key` | OpenSSH private key with push permission to Git | Read-Only (`ro`) |

---

## 🔑 Git Authentication (SSH Deploy Key)

To allow the container to push updated manifests back to your Git repository:

1. Generate an SSH keypair:

   ```bash
   ssh-keygen -t ed25519 -C "scoop-alts-bot" -f ./deploy_key -N ""
   ```

2. Add the **public key** (`deploy_key.pub`) as a Deploy Key with **write access** in Forgejo or GitHub.
3. Mount the **private key** (`deploy_key`) into the container at `/data/deploy_key` with permissions `0600`.
4. The container entrypoint automatically loads this key via `GIT_SSH_COMMAND` and pre-configures known hosts.

---

## 🩺 Health Check & Monitoring

The container includes an integrated healthcheck script (`docker/bin/healthcheck.sh`):

* The healthcheck simply verifies the cron daemon (PID 1) is still alive, so the container reports `healthy` immediately after start.
* A separate heartbeat cron refreshes `/data/heartbeat` every 5 minutes; the heartbeat is informational and is not consulted by the healthcheck.

Check health status:

```bash
docker inspect --format '{{.State.Health.Status}}' scoop-alts-scheduler
```

---

## 🛠️ On-Demand Management Commands

Execute tasks inside the running container without restarting:

```bash
# Run a full update cycle immediately
docker compose exec scheduler /usr/local/scoop-bin/run_update_all.sh

# Run manifest schema validation
docker compose exec scheduler python -u /app/scripts/automate-scoop.py validate

# Run updates for a specific package only
docker compose exec scheduler python -u /app/scripts/update-agy.py
```
