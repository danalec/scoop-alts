# QWEN.md

Instructional context for AI agents working in this repository.

## Project Overview

`scoop-alts` is an **alternative Scoop bucket for Windows** — a collection of ~23 Scoop
JSON manifests (`bucket/*.json`) for software that needs enhanced packaging: Widevine
DRM integration, persisted user profiles, custom install hooks, and bleeding-edge
builds. A generated index is published to <https://danalec.github.io/scoop-alts/>.

The repo is *two projects at once*:

1. **The bucket** — the actual `bucket/*.json` deliverable consumed by `scoop`.
2. **An automation engine** — a Python pipeline (`scripts/`) that keeps every manifest
   fresh by detecting upstream releases, recomputing hashes, and committing the result.

The Python side is the part agents modify. The bucket is normally machine-written.

**Language/runtime:** Python 3.11+ (CI matrix: 3.11, 3.12, 3.13, 3.14), plus
PowerShell (`bin/`) and Bash (`docker/bin/`) support scripts.

## Architecture

```text
upstream releases → version_detector.py → update-<pkg>.py → manifest_manager.py
                                                                    ↓
                                                            bucket/<pkg>.json
                                                                    ↓
                                            git_helpers.py → commit → push master
```

### Core modules (`scripts/`)

| File | Role |
| :--- | :--- |
| `update-all.py` | **Orchestrator.** Discovers `update-*.py`, runs them (parallel or sequential), summarizes, commits, pushes. |
| `version_detector.py` | Upstream version discovery, asset selection, SHA-256 hash computation, release caching. |
| `manifest_manager.py` | `ManifestUpdater` — schema-aware manifest mutation, `is_forced()`, structured result emission. |
| `git_helpers.py` | Staging, commit message construction, push, dry-run support. |
| `summary_utils.py` | Webhook body formatting for run summaries. |
| `automate-scoop.py` | **CLI entry point** for manifest generation, validation, and auditing. |
| `manifest-generator.py`, `manifest_doctor.py` | Manifest scaffolding and deep lint. |
| `generate-site.py`, `generate-dashboard.py` | GitHub Pages site and health dashboard. |
| `providers.json` | Maps each updater to a provider bucket (`github`/`microsoft`/`google`/`other`) for rate throttling. |
| `manifest_schema.json` | JSON Schema that every `bucket/*.json` must satisfy. |
| `update-*.py` | One updater per package. All are discovered automatically — no registration needed. |
| `requirements-automation.txt` | All Python dependencies (there is no `requirements.txt` at root). |

### Updater contract

An updater script is the extension point. `update-all.py` discovers any `scripts/update-*.py`
(excluding `update-all.py` and `update-script-generator.py`) and runs it as a subprocess.
Each child must:

1. Exit `0` on success, non-zero on failure.
2. Print a **single-line JSON object containing an `updated` key** on stdout. The
   orchestrator parses this as the authoritative result — do not rely on human-readable
   text parsing. `ManifestUpdater.emit_result()` does this for you.
3. Write the updated manifest to `bucket/<name>.json` as a side effect.

The reference implementation is `scripts/update-ripgrep-all.py`. Copy its structure
when adding a package.

## Key Commands

All commands are run from the repository root. The local venv is at `.venv`
(Windows: `.venv\Scripts\python.exe`; POSIX: `.venv/bin/python`).

> The existing `.venv` has `pytest` and the runtime deps installed, but **not**
> `ruff`, `black`, or `flake8`. The lint commands below require
> `pip install -r scripts/requirements-automation.txt` first (or run them via
> `pre-commit run --all-files`). `pytest` and `automate-scoop.py validate` work
> as-is.

```bash
# Dependencies
pip install -r scripts/requirements-automation.txt
pre-commit install

# Tests — 178 tests, ~4s
python -m pytest tests/ -q
python -m pytest tests/test_version_detector.py -v   # single file
python -m pytest -m "not slow"                        # deselect slow

# Lint (CI runs these against `scripts/`, not `tests/`)
python -m ruff check scripts
python -m black --check scripts
python -m flake8 scripts
python -m mypy --ignore-missing-imports --no-strict-optional scripts/

# Manifest validation (required before any commit that touches bucket/)
python scripts/automate-scoop.py validate
python scripts/automate-scoop.py doctor        # deep lint; needs p7zip-full on Linux CI

# Run the orchestrator
python scripts/update-all.py --workers 6
python scripts/update-all.py --sequential              # debug single runs
python scripts/update-all.py --scripts corecycler esptool
python scripts/update-all.py --only-providers github
python scripts/update-all.py --force                  # rewrite unchanged manifests

# Other automate-scoop.py subcommands
python scripts/automate-scoop.py wizard
python scripts/automate-scoop.py audit-providers
python scripts/automate-scoop.py generate-scripts
```

Useful orchestrator flags: `--retry N`, `--json-summary <path>`, `--md-summary <path>`,
`--skip-scripts`, `--skip-providers`, `--resume <summary.json>`, `--skip-git`,
`--git-dry-run`, `--structured-output`, `--install-browsers`, `--fail-fast`.

### Windows: encoding is a real trap

Scripts print emoji (🔍, ✅, ❌). On a default Windows console (cp1252) this **crashes
with `UnicodeEncodeError`** rather than degrading:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f50d' in position 0
```

Verified: `python scripts/automate-scoop.py validate` fails this way out of the box.

**Always prefix Python invocations on Windows with `PYTHONIOENCODING=utf-8`:**

```cmd
set PYTHONIOENCODING=utf-8 && python scripts\automate-scoop.py validate
```

`update-all.py` already self-heals via `ensure_utf8_console()` and sets
`PYTHONIOENCODING` for its children. Other entry points do not. If you add a new
entry point, port that guard. Do not "fix" a reported encoding error by stripping
emoji from the source.

## Development Conventions

- **Line length 100**, 4-space indent, spaces only. `.editorconfig` sets `end_of_line = crlf`
  and `insert_final_newline = true` for all files; 2-space indent for `*.yml`/`*.yaml`.
- **Naming:** module files are `kebab-case.py` (`update-foo.py`) but core shared modules use
  `snake_case.py` (`version_detector.py`, `git_helpers.py`, `summary_utils.py`). Follow the
  local convention of the file you are editing.
  Classes `PascalCase`, functions/variables `snake_case`, constants `UPPER_SNAKE_CASE`.
- **Commits:** Conventional Commits — `feat(bucket): add <pkg>`,
  `fix(scripts): resolve hash computation`. **All documentation, comments, and commit
  messages must be in English**, regardless of the language used in conversation.
- **Type hints** on public functions; docstrings on public functions and classes.
- **Comments** explain *why* (e.g. the `extract_dir` rewrite, the veracrypt top-level
  `url`/`hash` drop). Do not narrate what the code does.
- **Optional dependencies are imported defensively** — `requests`, `bs4`, `packaging`,
  `rich`, `playwright`, `requests-cache` all have `try/except ImportError` guards with
  graceful degradation. Preserve that pattern; the suite must not hard-fail when an
  optional package is absent.
- **Environment-driven config:** `SCOOP_UPDATE_WORKERS`, `SCOOP_UPDATE_TIMEOUT`,
  `SCOOP_RETRY_ATTEMPTS`, `MAX_GITHUB_WORKERS`, `MAX_GOOGLE_WORKERS`,
  `MAX_MICROSOFT_WORKERS`, `RELEASE_CACHE_TTL`, `AUTOMATION_LIB_SILENT`,
  `LOG_LEVEL`, `SCOOP_GIT_DRY_RUN`.

### Testing

`tests/conftest.py` provides shared fixtures (`repo_root`, `bucket_dir`, `temp_bucket_dir`,
`sample_manifest`, `sample_manifest_with_architecture`, `mock_github_release_response`,
`mock_http_response`, …) and registers the markers `slow`, `network`, `windows`, `linux`.
It also inserts `scripts/` into `sys.path` so tests import modules directly.

Test files use both `unittest.TestCase` and plain pytest style — match the file you edit.
Name tests `test_<function>_<scenario>_<expected>`. **Never make a test hit the network.**
The release cache auto-disables under pytest (`_running_under_test()` in
`version_detector.py`), so mocked sessions are always consulted.

## Writing Manifests

- Every `bucket/*.json` must validate against `scripts/manifest_schema.json`.
- `hash` is `sha256:<hex>` and must be recomputed, never copied from an old manifest.
- When an `architecture` block carries the real `url`/`hash`, the top-level `url`/`hash`
  must be **removed** (`ManifestUpdater.apply_download_metadata` enforces this — a stale
  top-level pair silently breaks installs).
- `extract_dir` often embeds the version; the updater rewrites it on version change.
  Verify this path still holds if you touch `manifest_manager.py`.
- `check-json` in pre-commit only lints `bucket/`, so malformed JSON elsewhere is not
  caught automatically.

## CI/CD Topology

Understand who writes to `master` before making automation changes — this is the most
common source of conflicting-PR confusion.

| Actor | Trigger | Writes to `master`? |
| :--- | :--- | :--- |
| **Docker scheduler** (`scoop-alts-scheduler`) | Hourly cron | **Yes — primary automatic writer** |
| `scheduled-updates.yml` | Daily schedule | No — opens PRs |
| `excavator.yml` | Manual only | Yes, via PR |
| `python-ci.yml` / `ci.yml` | Push + PR | No — lint, test, validate, doctor |
| `pages.yml` | Push | No — deploys GitHub Pages |
| `scoop-smoke.yml` | Daily schedule | No — Windows install smoke test |

Because the container cron pushes directly to `master`, a daily `scheduled-updates` PR may
**need a rebase** when the container touched the same manifests. This is expected, not a bug.

`ci.yml` also has a `test-windows` job on `windows-latest`; Windows-only behavior must not
be broken by Linux-only changes.

## Docker Scheduler

`docker-compose.yml` builds the image from `Dockerfile` and runs the orchestrator on a cron
schedule. Notable details:

- `SCHEDULE_UPDATE_ALL=0 * * * *` (hourly), `HEARTBEAT_SCHEDULE=*/5 * * * *`.
- `ORCHESTRATOR_FLAGS=--fast --retry 1` is how flags reach the container.
- `./scripts` is mounted **read-only** (`:ro`); `./bucket` is writable — the container's
  write path for manifest changes.
- `GITHUB_TOKEN` is forwarded into the container (recently pinned in compose and crontab).
- Healthcheck: `docker/bin/healthcheck.sh`; entrypoint: `docker/bin/entrypoint.sh`.
- Full guide: `docs/DOCKER-SETUP.md`.

## Working Practices

- **Never hand-edit a manifest version and hash.** Change the updater, then run it.
- **Adding a package:** create `bucket/<pkg>.json` + `scripts/update-<pkg>.py`, add the
  entry to `scripts/providers.json`, then `validate`. `update-all.py` discovers updaters
  automatically — there is no registry to update beyond `providers.json`.
- **Before committing:** run `pytest`, the three linters, and
  `automate-scoop.py validate`. CI runs all of them.
- **Check `git status` before staging.** Automation may have committed manifests locally
  since your last action; those are machine-owned changes, not yours to revert.
- **Line endings:** `.gitattributes` forces CRLF for all text files
  (`* text=auto eol=crlf`) because Scoop is Windows-only — but `docker/bin/*.sh` and
  `Dockerfile` are pinned to LF, since their `#!/bin/sh` shebangs break under CRLF.
  Do not normalize line endings by hand.

## Reference Docs

| Document | Use for |
| :--- | :--- |
| `README.md` | Bucket overview, package catalog, user-facing install instructions |
| `CONTRIBUTING.md` | Contribution workflow, PR process, code style |
| `SECURITY.md` | Vulnerability disclosure, manifest integrity verification |
| `docs/AUTOMATION-GUIDE.md` | Getting started with bucket automation |
| `docs/AUTOMATION-SCRIPTS-DOCUMENTATION.md` | Module-by-module technical reference |
| `docs/AUTOMATION-ADVANCED.md` | Regex patterns, multi-arch assets, throttling, circuit breakers |
| `docs/DOCKER-SETUP.md` | Container scheduler deployment (Unraid/Docker) |
| `docs/ungoogled-chromium.md` | Widevine DRM, profile persistence, clean uninstall |
| `docs/index.md` | Master documentation index |
