# Scoop Bucket 101: Example Add CodeCharta Visualization from a GitHub Release URL

## Goal
- Create a Scoop manifest for CodeCharta Visualization using only the GitHub Release URL
- Use the repository scripts to generate and maintain the manifest automatically

## Target Release and Asset
- Release tag: `https://github.com/MaibornWolff/codecharta/releases/tag/vis-1.141.0`
- Windows asset: `https://github.com/MaibornWolff/codecharta/releases/download/vis-1.141.0/codecharta-visualization-win32-x64.zip`

## Prerequisites
- `git`, `python` available on PATH
- Scoop installed and working: `scoop checkup`
- This repository cloned locally and your working directory set to it

## Quick Path: Interactive Wizard
- Run: `python scripts/automate-scoop.py`
- When prompted, select GitHub Releases as source and paste the asset URL:
  - `https://github.com/MaibornWolff/codecharta/releases/download/vis-1.141.0/codecharta-visualization-win32-x64.zip`
- Provide package name: `codecharta`
- The wizard creates `bucket/codecharta.json` and configures `checkver`/`autoupdate` to follow visualization tags (`vis-$version`).
- The script downloads the asset to compute `sha256` automatically.

## Manual Path: Add Manifest Directly
1. Create `bucket/codecharta.json` with:
   - `version`: `1.141.0`
   - `url`: release asset URL shown above
   - `hash`: computed from the asset (the automation scripts can fill this)
   - `homepage`: `https://github.com/MaibornWolff/codecharta`
   - `license`: `BSD-3-Clause`
   - `checkver`: parse `vis-<version>` tags
   - `autoupdate`: `https://github.com/MaibornWolff/codecharta/releases/download/vis-$version/codecharta-visualization-win32-x64.zip`

2. Optional: add `bin` or `shortcuts` after confirming the exe name inside the zip.

## Verify Locally
- Add the bucket: `scoop bucket add scoop-alts <path-to-repo>`
- Install: `scoop install codecharta`
- Check: `scoop info codecharta` shows correct `version`, `url`, `hash`

## Automation: Keep It Updated
- Generate a per-app updater script (already provided in `scripts/update-codecharta.py`):
  - Detects latest visualization tag via GitHub API (`tag_name` starting with `vis-`)
  - Updates `version`, `url`, and recalculates `hash`
  - Writes changes to `bucket/codecharta.json`
- Run all updates: `python scripts/update-all.py`
  - Use `--only codecharta` to update just this package

## Notes
- CodeCharta publishes separate `analysis-` and `vis-` releases; this bucket tracks `vis-` tags.
- The updater script uses the GitHub Releases API and the asset naming pattern to stay in sync automatically.

