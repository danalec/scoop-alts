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
services:
  scheduler:
    build: .
    image: scoop-alts-scheduler:latest
    container_name: scoop-alts-scheduler
    restart: unless-stopped
    environment:
      - SCHEDULE_UPDATE_ALL=0 * * * *        # Run every hour
      - HEARTBEAT_SCHEDULE=*/5 * * * *        # Healthcheck heartbeat every 5 minutes
      - ORCHESTRATOR_FLAGS=--fast --retry 1
      - NOTIFY_WEBHOOK_URL=                  # Optional notification webhook
      - GITHUB_TOKEN=                         # Optional GitHub PAT for higher API limits
      - DEPLOY_KEY_SSH_HOST=                  # Alias of a forge on a non-default SSH port
      - DEPLOY_KEY_SSH_HOSTNAME=
      - DEPLOY_KEY_SSH_PORT=
      - REPO_URL=                             # Repository the scheduler clones
      - REPO_PUSH_URLS=                       # Comma-separated push targets
      - SCOOP_GIT_REMOTE=origin
      - SCOOP_GIT_BRANCH=main
      - SYNC_REMOTE=origin
      - SYNC_BRANCH=main
    volumes:
      - scoop-repo:/app/repo                   # The scheduler's own clone
      - ./logs:/data/logs:rw
      - ./cache:/data/cache:rw
      - ./deploy_key:/data/deploy_key:ro
```

> **The scheduler keeps its own clone** (`scoop-repo` volume), not a bind mount of
> your working tree. The runner starts with `git reset --hard origin/main`, and
> that discards whatever sits in the checkout it runs against - a branch in
> progress, uncommitted edits, everything. With its own clone the runner
> publishes from `/app/repo` and your working tree is never touched. Pull to
> pick up the manifests it published.

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
| `SCOOP_GIT_BRANCH` | `main` | Target Git branch to push updates to. |
| `SYNC_REMOTE` | `origin` | Remote the runner fast-forwards to before each run. |
| `SYNC_BRANCH` | `main` | Branch the runner fast-forwards to before each run. |
| `GITHUB_TOKEN` | `""` | GitHub Personal Access Token to avoid rate limits during version discovery. |
| `AUTOMATION_DISABLE_WINMETA` | `1` | Disables Windows-specific binary inspection when running on Linux containers. |
| `REPO_URL` | `""` | Repository the scheduler clones into its own volume. |
| `REPO_PUSH_URLS` | `""` | Comma-separated push targets, e.g. `git@github.com:owner/repo.git,ssh://git@forge/owner/repo.git`. |
| `DEPLOY_KEY_SSH_HOST` | `""` | Alias of a forge whose git SSH lives on a non-default port. |
| `DEPLOY_KEY_SSH_HOSTNAME` | `""` | Real address behind that alias. |
| `DEPLOY_KEY_SSH_PORT` | `""` | Port that alias resolves to. |

> **Supplying `GITHUB_TOKEN`:** create a `.env` file next to `docker-compose.yml`
> (gitignored by default) with `GITHUB_TOKEN=ghp_...`, or export it in the host
> shell before `docker compose up`. A fine-grained PAT with **no permissions**
> is enough — the bucket only queries public release APIs, and the token only
> raises the hourly quota from 60 to 5,000 requests. The compose file forwards
> it into the container, and the entrypoint pins it into the crontab so the
> scheduled job always sees it. Without it, hourly runs share the 60-request
> anonymous quota per IP and can fail mid-run once it is exhausted.

### Why the runner resets before each run

The scheduler is the only automatic writer of the branch, so a checkout that has
fallen behind turns every push into a non-fast-forward rejection. `run_update_all.sh`
therefore fetches `SYNC_REMOTE`/`SYNC_BRANCH` and hard-resets to it before invoking
`update-all.py`. The reset runs on the scheduler's own clone in the `scoop-repo`
volume, so it discards only what a previous interrupted run left in *that* clone —
your working tree is never touched.

---

## 💾 Storage & Persistent Volumes

| Container Mount | Recommended Host Path | Purpose | Access Mode |
| :--- | :--- | :--- | :---: |
| `/app/repo` | `scoop-repo` (named volume) | The scheduler's own clone, where it commits and pushes | Read-Write (`rw`) |
| `/data/logs` | `./logs` | Run summaries, orchestrator logs, and stdout | Read-Write (`rw`) |
| `/data/cache` | `./cache` | Cached HTTP responses and ETag storage | Read-Write (`rw`) |
| `/data/deploy_key` | `./deploy_key` | OpenSSH private key with push permission to Git | Read-Only (`ro`) |

---

## 🔑 Git Authentication (SSH Deploy Key)

To allow the container to push updated manifests back to your Git repository:

1. Generate an SSH keypair — **without a passphrase**, the container copies the
   key into `/root/.ssh` and uses it directly, with no ssh-agent:

   ```bash
   ssh-keygen -t ed25519 -C "scoop-alts-bot" -f ./deploy_key -N ""
   ```

2. Add the **public key** (`deploy_key.pub`) as a Deploy Key with **write access** in Forgejo or GitHub.
3. Mount the **private key** (`deploy_key`) into the container at `/data/deploy_key`.
4. The entrypoint copies the key to `/root/.ssh/id_ed25519` and writes an
   `/root/.ssh/config` that offers it for every host, plus a per-host block for
   `DEPLOY_KEY_SSH_HOST` — the alias a forge on a non-default SSH port needs.
5. Point `REPO_URL` at the repository to clone and `REPO_PUSH_URLS` at the
   remotes to publish to (comma-separated, e.g. a forge and GitHub).

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
