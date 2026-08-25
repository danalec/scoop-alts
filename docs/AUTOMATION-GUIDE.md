# Scoop Bucket Automation Guide

Quick links:
- [Overview](#overview)
- [Quick Start](#quick-start)
- [Creating or Updating a Package](#creating-or-updating-a-package)
- [Running Updates](#running-updates)
- [Summaries and Webhooks](#summaries-and-webhooks)
- [Git Options](#git-options)
- [Troubleshooting](#troubleshooting)

This guide covers the practical workflow for the Python automation in this repository. For module-by-module implementation details, see [AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md).

## Overview

The automation flow is intentionally simple:

1. Define or generate a package update script in `scripts/update-*.py`.
2. Let `version_detector.py` fetch the latest version and artifact hash.
3. Let `manifest_manager.py` update the matching manifest in `bucket/`.
4. Use `update-all.py` to run one script or the whole set.

The shared modules matter more than the individual package scripts. Package scripts should mostly contain package-specific configuration, not custom orchestration logic.

## Quick Start

Install Python dependencies:

```powershell
pip install -r scripts/requirements-automation.txt
```

Run every update script:

```powershell
python scripts/update-all.py
```

Run a single package:

```powershell
python scripts/update-all.py --scripts ripgrep-all
```

Run sequentially:

```powershell
python scripts/update-all.py --sequential --delay 0.5
```

Use faster parallel defaults:

```powershell
python scripts/update-all.py --fast
```

## Creating or Updating a Package

### Recommended pattern

Keep package scripts very small and delegate shared work:

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

### What belongs in the package script

Keep:
- package name
- homepage or API URL
- version regex patterns
- download URL template
- package-specific metadata needed by `SoftwareVersionConfig`

Avoid:
- custom manifest rewrite logic
- custom summary formatting
- duplicated git logic

### Manifest updates

`ManifestUpdater` handles:
- loading the existing manifest
- comparing versions
- updating `version`
- updating `url` and `hash`
- updating the preferred `architecture` entry when present
- emitting the structured JSON status line used by the orchestrator

## Running Updates

### Common commands

Run all scripts:

```powershell
python scripts/update-all.py
```

Run specific scripts:

```powershell
python scripts/update-all.py --scripts corecycler esptool
```

Skip specific scripts:

```powershell
python scripts/update-all.py --skip-scripts windhawk esptool
```

Retry failures:

```powershell
python scripts/update-all.py --retry 2
```

Prefer strict JSON child output:

```powershell
python scripts/update-all.py --structured-output
```

Resume only previously failed scripts:

```powershell
python scripts/update-all.py --resume .temp/update-summary.json
```

### Provider filtering

Filter by provider classification:

```powershell
python scripts/update-all.py --only-providers github google
python scripts/update-all.py --skip-providers other
```

Provider detection uses:
- `scripts/providers.json` when present
- otherwise a lightweight scan of each update script for known provider domains

### HTTP cache

Enable short-lived caching for repeated runs:

```powershell
python scripts/update-all.py --http-cache --http-cache-ttl 1800
```

This sets:
- `AUTOMATION_HTTP_CACHE=1`
- `AUTOMATION_HTTP_CACHE_TTL=<seconds>`

`version_detector.py` uses those environment variables when `requests-cache` is available.

## Summaries and Webhooks

Write machine-readable and Markdown summaries:

```powershell
python scripts/update-all.py `
  --json-summary .temp/update-summary.json `
  --md-summary .temp/update-summary.md
```

Send a webhook after the run:

```powershell
python scripts/update-all.py `
  --json-summary .temp/update-summary.json `
  --webhook-url https://example.invalid/webhook `
  --webhook-type slack
```

Supported webhook formats:
- `generic`
- `slack`
- `discord`

## Git Options

Skip git integration entirely:

```powershell
python scripts/update-all.py --skip-git
```

Commit each updated manifest separately:

```powershell
python scripts/update-all.py --git-per-package
```

Commit staged bucket changes in grouped commits:

```powershell
python scripts/update-all.py --git-aggregate
```

Create commits but skip the push step:

```powershell
python scripts/update-all.py --git-dry-run
```

Push to a specific remote or branch:

```powershell
python scripts/update-all.py --git-remote origin --git-branch main
```

Environment equivalents:
- `SCOOP_GIT_DRY_RUN`
- `SCOOP_GIT_REMOTE`
- `SCOOP_GIT_BRANCH`

## Troubleshooting

### No version found

Check the package script configuration first:
- Is `homepage` pointing to the page or API that actually contains the latest version?
- Do the regex patterns still match the current response?
- Does the package need a direct-download fallback instead of page scraping?

### Script succeeds but no update is detected

Check:
- the manifest already contains the detected version
- the script prints the structured JSON status line
- `--structured-output` is not hiding a malformed child output format

### Provider throttling feels wrong

Audit or override provider mappings in `scripts/providers.json` so the orchestrator does not infer them from script content alone.

### Git push should not happen

Use:

```powershell
python scripts/update-all.py --git-dry-run
```

or set:

```powershell
$env:SCOOP_GIT_DRY_RUN = "1"
```

[← Back to Docs Index](index.md)
