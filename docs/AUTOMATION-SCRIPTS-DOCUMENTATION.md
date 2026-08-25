# Scripts Technical Reference

Quick links:
- [Overview](#overview)
- [Core Modules](#core-modules)
- [Update Script Contract](#update-script-contract)
- [Orchestrator Workflow](#orchestrator-workflow)
- [Git Integration](#git-integration)
- [Summary Files and Webhooks](#summary-files-and-webhooks)
- [Configuration Files](#configuration-files)

This document describes the current Python automation stack under `scripts/`. It is intentionally focused on the shared modules that generated and hand-maintained update scripts rely on.

## Overview

The automation layer is organized around a small set of shared building blocks:

- `version_detector.py`
  Fetches versions, constructs download URLs, and calculates hashes.
- `manifest_manager.py`
  Applies version metadata to an existing Scoop manifest and emits structured status output.
- `update-all.py`
  Discovers update scripts, runs them, filters by provider, and writes run summaries.
- `git_helpers.py`
  Stages, commits, and optionally pushes manifest changes.
- `summary_utils.py`
  Formats JSON run summaries for Slack and Discord webhooks.
- `update-*.py`
  Package-specific scripts that define a `SoftwareVersionConfig` and delegate the update work to `ManifestUpdater`.

## Core Modules

### `scripts/version_detector.py`

Purpose:
- Centralize HTTP access, version parsing, URL construction, and hash calculation.

Important pieces:
- `SoftwareConfig` / `SoftwareVersionConfig`
  Dataclass used by update scripts and generators.
- `VersionDetector.fetch_latest_version()`
  Scrapes a page or API response with one or more regex patterns.
- `VersionDetector.construct_download_url()`
  Replaces `$version` and optional `$match...` placeholders.
- `VersionDetector.calculate_hash()`
  Downloads the artifact and returns the SHA256 digest.
- `get_version_info()`
  High-level helper that returns:

```json
{
  "version": "1.2.3",
  "download_url": "https://example.invalid/app-1.2.3.zip",
  "hash": "..."
}
```

Behavior notes:
- `AUTOMATION_HTTP_CACHE=1` enables optional request caching when `requests-cache` is installed.
- `AUTOMATION_HTTP_CACHE_TTL` controls cache expiry.
- `GITHUB_TOKEN` or `GH_TOKEN` is used automatically for GitHub API requests.

### `scripts/manifest_manager.py`

Purpose:
- Keep manifest rewriting logic in one place.

Main API:
- `ManifestUpdater(config, bucket_dir, manifest_filename=None)`
- `ManifestUpdater.update() -> bool`

What it does:
1. Calls `get_version_info(config)`.
2. Loads the target manifest.
3. Compares the detected version with the current manifest version.
4. Updates `version`, `url`, and `hash`.
5. Writes the manifest back with consistent JSON formatting.
6. Emits a one-line JSON status object for `update-all.py`.

Structured output contract:

```json
{"updated": true, "name": "demo", "version": "1.2.3"}
```

Possible error codes:
- `version_info_unavailable`
- `manifest_not_found`
- `invalid_manifest_json`
- `manifest_read_failed`
- `manifest_update_failed`
- `save_failed`

Architecture handling:
- If the manifest contains an `architecture` block, `ManifestUpdater` prefers `64bit`, then `arm64`, then `32bit`, then the first available entry.
- If no usable architecture block exists, it updates top-level `url` and `hash`.

### `scripts/update-all.py`

Purpose:
- Run update scripts and produce a clean summary of the run.

Main responsibilities:
- Discover `update-*.py` files.
- Normalize CLI selections such as `corecycler` into `update-corecycler.py`.
- Filter scripts by provider classification.
- Run scripts sequentially or in parallel.
- Prefer structured JSON child output when `--structured-output` is enabled.
- Write JSON and Markdown summaries.
- Send webhook notifications.
- Stage, commit, and optionally push changed manifests.

Key helper functions:
- `discover_update_scripts()`
- `parse_script_output()`
- `filter_by_providers()`
- `run_sequential()`
- `run_parallel()`
- `write_json_summary()`
- `write_md_summary()`
- `handle_git_integration()`

### `scripts/git_helpers.py`

Purpose:
- Provide a thin, reusable layer around the git commands used by automation.

Main functions:
- `run_git_command()`
- `commit_manifest_change()`
- `commit_with_message()`
- `stage_bucket_changes()`
- `get_staged_bucket_changes()`
- `list_untracked_manifests()`
- `push_changes()`

Environment variables honored by `push_changes()`:
- `SCOOP_GIT_DRY_RUN=1`
  Skip the push step.
- `SCOOP_GIT_REMOTE=<name>`
  Push to a specific remote.
- `SCOOP_GIT_BRANCH=<name>`
  Push a specific branch.

### `scripts/summary_utils.py`

Purpose:
- Convert the JSON run summary into small provider-specific webhook payloads.

Supported formats:
- `generic`
  Sends the JSON summary as-is.
- `slack`
  Sends `{ "text": "..." }`.
- `discord`
  Sends `{ "content": "..." }`.

## Update Script Contract

Each update script should stay small and package-focused:

```python
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

config = SoftwareVersionConfig(
    name="demo",
    homepage="https://example.invalid/releases",
    version_patterns=[r"v([0-9.]+)"],
    download_url_template="https://example.invalid/download/v$version/demo.zip",
)

bucket_dir = Path(__file__).parent.parent / "bucket"
success = ManifestUpdater(config, bucket_dir).update()
```

Expected behavior:
- The script prints normal log lines unless `STRUCTURED_ONLY=1`.
- The final status line is always JSON.
- Exit code `0` means success, including "already up to date".
- Exit code non-zero means the update failed.

## Orchestrator Workflow

`update-all.py` follows this flow:

1. Read CLI arguments and optional environment defaults.
2. Discover update scripts under `scripts/`.
3. Apply script name filters, resume filters, and provider filters.
4. Export runtime flags for child scripts:
   - `STRUCTURED_ONLY`
   - `AUTOMATION_HTTP_CACHE`
   - `AUTOMATION_HTTP_CACHE_TTL`
   - `SCOOP_GIT_DRY_RUN`
   - `SCOOP_GIT_REMOTE`
   - `SCOOP_GIT_BRANCH`
5. Run scripts sequentially or in parallel.
6. Summarize the results.
7. Optionally write summary files and send a webhook.
8. Optionally stage, commit, and push manifest changes.

Provider classification sources:
- Explicit overrides from `scripts/providers.json`
- Fallback content inspection for GitHub, Microsoft, and Google URLs inside each script

## Git Integration

Two commit strategies are supported:

- Per-package:
  Each updated manifest is committed separately.
- Aggregate:
  Staged `bucket/*.json` changes are grouped into "updated" and "added" commits.

Related CLI flags:
- `--skip-git`
- `--git-per-package`
- `--git-aggregate`
- `--git-dry-run`
- `--git-remote`
- `--git-branch`

## Summary Files and Webhooks

### JSON summary

`--json-summary <path>` writes a machine-readable file like:

```json
{
  "mode": "Parallel",
  "timeout": 120,
  "workers": 4,
  "counts": {
    "total": 3,
    "successful": 2,
    "failed": 1,
    "updated": 1,
    "no_updates": 1
  },
  "results": [
    {
      "script": "update-demo.py",
      "package": "demo",
      "success": true,
      "updated": true,
      "duration_seconds": 1.234,
      "version": "1.2.3",
      "error_preview": ""
    }
  ]
}
```

### Markdown summary

`--md-summary <path>` writes a simple dashboard table intended for quick review in CI artifacts or docs pages.

### Webhooks

Webhook delivery requires both:
- `--json-summary`
- `--webhook-url`

Optional webhook flags:
- `--webhook-type generic|slack|discord`
- `--webhook-header-name`
- `--webhook-header-value`

## Configuration Files

Files used by the shared automation layer:

- `scripts/providers.json`
  Optional provider overrides for throttling and filtering.
- `scripts/software-configs.json`
  Input data used by the generation tools.
- `scripts/manifest_schema.json`
  JSON schema used for manifest validation.
- `scripts/requirements-automation.txt`
  Python dependencies for the automation toolchain.

[← Back to Docs Index](index.md)
