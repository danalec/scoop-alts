# AGENTS.md

Curated Windows software manifests for [Scoop](https://scoop.sh) with enhanced packaging,
automated quality assurance, and lifecycle management. Two projects in one repo: the
`bucket/*.json` manifests (the deliverable) and the Python automation engine in `scripts/`
that keeps them fresh. Agents modify the Python side; manifests are machine-written.

## Setup commands

- Install deps: `pip install -r scripts/requirements-automation.txt` (no root `requirements.txt`)
- Install hooks: `pre-commit install`
- Test: `python -m pytest tests/ -q`
- Lint: `python -m ruff check scripts` · `python -m black --check scripts` · `python -m flake8 scripts`
- Typecheck: `python -m mypy --ignore-missing-imports --no-strict-optional scripts/`
- Validate manifests: `python scripts/automate-scoop.py validate`
- One-shot gate (schema + offline deep lint): `python scripts/automate-scoop.py health`
- Deep lint (downloads archives): `python scripts/automate-scoop.py doctor` (needs `p7zip-full` on Linux)
- Run orchestrator: `python scripts/update-all.py --workers 6`

Python 3.11+ (CI matrix: 3.11–3.14). Linters target `scripts/`, not `tests/`. The checked-in
`.venv` has `pytest` and the runtime deps but **not** ruff/black/flake8.

## Project layout

- `bucket/` — Scoop JSON manifests, one per package (the shipped artifact)
- `scripts/` — automation framework, `packages.json` registry, and bespoke updaters
- `tests/` — pytest suite with shared fixtures in `conftest.py`
- `docs/` — `AUTOMATION.md` (engine reference), `DOCKER-SETUP.md`, per-package notes
- `docker/`, `Dockerfile`, `docker-compose.yml` — containerized hourly scheduler
- `bin/` — PowerShell maintenance scripts

Core modules: `version_detector.py` (release discovery + SHA-256), `manifest_manager.py`
(`ManifestUpdater`, `is_forced()`), `git_helpers.py`, `summary_utils.py`,
`automate-scoop.py` (CLI), `manifest_doctor.py` (deep lint), `manifest_schema.json`.

## Windows: set PYTHONIOENCODING

Scripts print emoji; on a default cp1252 console this **crashes** with `UnicodeEncodeError`.
On Windows always prefix invocations:

```cmd
set PYTHONIOENCODING=utf-8 && python scripts\automate-scoop.py validate
```

`update-all.py` self-heals via `ensure_utf8_console()` and exports the var to children. Other
entry points do not — port that guard when adding one. Never "fix" an encoding error by
stripping emoji from the source.

## How packages are updated

`update-all.py` resolves each package to something runnable and executes it in its own
subprocess. Two kinds, both exposed under the same logical name `update-<package>.py`:

1. **Registry-driven** (19 packages) — config lives in `scripts/packages.json`; the
   orchestrator runs `scripts/update-package.py <package>`. Adding a package is a JSON entry.
2. **Bespoke** (6 packages) — their own `scripts/update-<package>.py`, for multi-asset url
   arrays (`kuna`), custom version detection (`widevinecdm`), redirect following
   (`usb-safely-remove*`), or bespoke hashing (`agy`, `victoria`).

Either way the child must:

1. Exit `0` on success, non-zero on failure.
2. Print a **single-line JSON object with an `updated` key** on stdout — the orchestrator
   parses this as authoritative, not human-readable text. `ManifestUpdater.emit_result()` does it.
3. Write the updated manifest to `bucket/<name>.json` as a side effect.

`ManifestUpdater` assigns `url`/`hash` as **single strings**. A package whose upstream ships
several assets must keep them as arrays itself (see `KunaManifestUpdater`), otherwise the extra
asset is silently dropped. `maybe_auto_commit()` in `git_helpers.py` handles the opt-in commit;
never copy that block into a new updater.

To add a package, `automate-scoop.py wizard` writes `bucket/<pkg>.json` and then
`update-package.py --register <pkg>`, which derives the registry entry from that manifest's
`checkver` and `autoupdate` blocks. The derived entry is a **starting point**: it scrapes the
vendor page, where a hand-written entry often prefers a releases API. Review the patterns before
relying on them. Registration refuses to run for a package that already owns a bespoke
`update-<pkg>.py` — one manifest must have exactly one definition.

Forced mode (rewrite unchanged manifests): `--force` on `update-all.py` exports `FORCE=1`;
individual updaters honor `FORCE=1`, `SCOOP_FORCE=1`, or `--force`/`-f`. Pass `force=is_forced()`.

## Code style

- Black, line length **100**; Ruff pinned to `["E4","E7","E9","F"]` in `ruff.toml` — do not widen
- flake8 `max-line-length = 100`, ignores `E501,W503,E203`. Unsplittable URL string literals run
  past 100 in most updaters; that is expected, not a violation.
- `.editorconfig` forces CRLF for all text files; `docker/bin/*.sh` and `Dockerfile` are pinned to
  LF because their `#!/bin/sh` shebangs break under CRLF. Do not normalize line endings by hand.
- Naming: updater modules are `kebab-case.py`, shared modules `snake_case.py` — match the
  file you are editing. Classes `PascalCase`, functions `snake_case`, constants `UPPER_SNAKE_CASE`
- Type hints on public functions, docstrings on public functions and classes; comments explain
  *why*, not what
- Optional deps (`requests`, `bs4`, `packaging`, `rich`, `playwright`, `requests-cache`) are
  imported defensively behind `try/except ImportError`. Preserve that graceful degradation
- Config via env vars: `SCOOP_UPDATE_WORKERS`, `SCOOP_UPDATE_TIMEOUT`, `SCOOP_RETRY_ATTEMPTS`,
  `MAX_{GITHUB,GOOGLE,MICROSOFT}_WORKERS`, `RELEASE_CACHE_TTL`, `AUTOMATION_LIB_SILENT`,
  `LOG_LEVEL`, `SCOOP_GIT_DRY_RUN`
- All docs, comments, and commit messages in **English**, regardless of conversation language

## Testing instructions

- Unit tests: `python -m pytest tests/ -q`; single file: `python -m pytest tests/test_x.py -v`;
  deselect slow: `python -m pytest -m "not slow"`
- Add tests for every new behavior — match the style of the file you edit (both
  `unittest.TestCase` and plain pytest are in use); name tests `test_<function>_<scenario>_<expected>`
- **Never let a test hit the network.** `conftest.py` registers `slow`/`network`/`windows`/
  `linux` markers and inserts `scripts/` into `sys.path`; the release cache auto-disables under
  pytest, so mocked sessions are always consulted
- The bespoke updaters are the highest-risk code in the repo (a wrong mutation corrupts a shipped
  manifest silently). `tests/test_bespoke_updaters.py` covers all six; extend it rather than
  reaching for the network. `tests/test_version_detector_properties.py` fuzzes the pure parsers
  with a seeded RNG — keep it deterministic, since a test that only fails on Tuesdays is worse
  than no test
- `pre-commit run --all-files` **skips untracked files** — a green run before committing a new
  script proves nothing about that script. Re-run after `git add`
- Local hooks are part of the gate: `validate-manifests` and `doctor-manifests` run on any
  `bucket/*.json` change, and `pytest` runs on push. The doctor hook is `--offline`, so it never
  downloads archives; run the full `doctor` by hand or in CI
- All tests, the three linters, and `automate-scoop.py validate` must pass before opening a PR

## Working practices

- **Never hand-edit a manifest version or hash.** Change the updater, then run it.
- Every `bucket/*.json` must satisfy `scripts/manifest_schema.json`; `hash` is `sha256:<hex>` and
  is recomputed, never copied. When an `architecture` block carries the real `url`/`hash`, the
  top-level pair **must be removed** — `apply_download_metadata` enforces this, and `doctor`
  rejects the combination outright (`architecture-shadow`): scoop serves the top-level pair as the
  fallback for any architecture the block does not list, so a stale duplicate silently installs
  the wrong binary. `extract_dir` often embeds the version; keep it top-level and in sync with
  its `autoupdate` template.
- `check-json` in pre-commit only lints `bucket/`, so malformed JSON elsewhere is unchecked.
- Adding a package: `bucket/<pkg>.json` + a `packages.json` entry (or a bespoke updater) + a
  `providers.json` entry, then validate.
- **Check `git status` before staging** — automation may have committed manifests since your last
  action; those machine-owned changes are not yours to revert.
- `docs/update-health.md` is generated output and is git-ignored; regenerate it locally with
  `--md-summary`.

## Who writes to main

The scheduler is the **only** automatic writer. `scheduled-updates.yml` used to run the
orchestrator daily and open a PR, which collided with the hourly container and made almost every
PR need a rebase; it has been deleted rather than retuned.

| Actor | Trigger | Writes to `main`? |
| :--- | :--- | :--- |
| **Docker scheduler** (`scoop-alts-scheduler`) | Hourly cron | **Yes — the only automatic writer** |
| `ci.yml` | Push + PR | No — lint, test, validate, doctor |
| `excavator.yml` | Manual only | Yes, via PR |
| `pages.yml` | Push | No — deploys GitHub Pages |
| `scoop-smoke.yml` | Daily schedule | No — Windows install smoke test |

Every push to `main` — including the container's — triggers `ci.yml`, so the gate runs without
a second scheduled workflow. The container fast-forwards to `origin/main` before each run
(`SYNC_REMOTE`/`SYNC_BRANCH` in `docker/bin/run_update_all.sh`) so its push is never rejected.
`ci.yml` also has a `test-windows` job; do not break Windows-only behavior with Linux-only changes.

## PR & commit conventions

- Branch from `main`; never push to it directly
- Conventional Commits: `feat(bucket): add <pkg>`, `fix(scripts): resolve hash computation`
  — types: feat, fix, docs, style, refactor, test, chore
- Long-form engine reference lives in [`docs/AUTOMATION.md`](docs/AUTOMATION.md); container
  deployment in [`docs/DOCKER-SETUP.md`](docs/DOCKER-SETUP.md)

## Security

- Never commit secrets; use env vars for tokens (e.g. `GITHUB_TOKEN`) — `SECURITY.md` §Contributors
- Verify manifest URLs and hashes; HTTPS everywhere; report vulnerabilities via GitHub private
  advisory reporting, never public issues
