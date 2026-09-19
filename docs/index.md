# Documentation Index

Welcome to the centralized documentation index for **Dan's Alternative Scoop Bucket (`scoop-alts`)**.

---

## 📖 Architecture & Guides

### 1. Automation Framework
* **[Automation Getting Started Guide](AUTOMATION-GUIDE.md)**: End-to-end introduction to creating new package manifests, using the interactive generator wizard, and setting up automated manifest updates.
* **[Scripts Technical Reference](AUTOMATION-SCRIPTS-DOCUMENTATION.md)**: Deep dive into the shared Python architecture (`version_detector.py`, `manifest_manager.py`, `git_helpers.py`, `update-all.py`).
* **[Advanced Automation & Throttling](AUTOMATION-ADVANCED.md)**: Complex regex patterns, multi-architecture asset matching, GitHub API rate limiting, and CI/CD workflows.

### 2. Infrastructure & Scheduling
* **[Docker Container Scheduler](DOCKER-SETUP.md)**: Instructions for running the headless, cron-driven updater container (`scoop-alts-scheduler`) via Docker or Docker Compose.

### 3. Application Guides
* **[Ungoogled Chromium Manual](ungoogled-chromium.md)**: Detailed instructions on Widevine DRM integration, profile persistence, default browser registration, and clean uninstallation.

---

## 🔍 Quick File Reference

| Document | Scope & Purpose | Audience |
| :--- | :--- | :--- |
| [`../README.md`](../README.md) | Primary project homepage, quick start, and package catalog | Users & Contributors |
| [`AUTOMATION-GUIDE.md`](AUTOMATION-GUIDE.md) | Beginner-to-intermediate guide for package management | Package Maintainers |
| [`AUTOMATION-SCRIPTS-DOCUMENTATION.md`](AUTOMATION-SCRIPTS-DOCUMENTATION.md) | Technical module documentation and contracts | Core Developers |
| [`AUTOMATION-ADVANCED.md`](AUTOMATION-ADVANCED.md) | Resilient updates, circuit breakers, and complex downloads | Power Users |
| [`DOCKER-SETUP.md`](DOCKER-SETUP.md) | Unraid / Docker deployment of the periodic update runner | Sysadmins & DevOps |
| [`ungoogled-chromium.md`](ungoogled-chromium.md) | Configuration and troubleshooting for Ungoogled Chromium | End Users |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution standards, code style, and PR requirements | Open-Source Contributors |
| [`../SECURITY.md`](../SECURITY.md) | Security vulnerability disclosure and integrity verification | Security Researchers |
