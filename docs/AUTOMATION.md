# Automation Reference

How the manifest pipeline works, and how to extend it. Contributor workflow and
agent rules live in [`AGENTS.md`](../AGENTS.md); this document is the engine
reference.

## Architecture

```text
upstream releases → version_detector.py → updater → manifest_manager.py
                                                              ↓
                                                      bucket/<pkg>.json
                                                              ↓
                                            git_helpers.py → commit → push main
```

## Core modules

| Module | Role |
| :--- | :--- |
| `version_detector.py` | Upstream version discovery, asset selection, SHA-256 hashing, release caching |
| `manifest_manager.py` | `ManifestUpdater` (schema-aware mutation), `is_forced()`, structured result emission |
| `update-all.py` | Orchestrator: resolves packages, runs them in subprocesses, throttles by provider, summarizes, commits |
| `update-package.py` | Generic runner for registry-driven packages |
| `git_helpers.py` | Staging, commit messages, push, dry-run support, `maybe_auto_commit()` |
| `summary_utils.py` | Webhook bodies and markdown/JSON summary formatting |
| `manifest_doctor.py` | Deep lint: zip layout, hash format, version consistency, scheme, architecture shadowing |
| `automate-scoop.py` | CLI: `validate`, `health`, `doctor`, `wizard`, `audit-providers`, `generate-scripts` |
| `manifest-generator.py` | Scaffolding: manifest templates from `software-configs.json` |
| `generate-site.py`, `generate-dashboard.py` | GitHub Pages site and health dashboard |

## Packages and updaters

Every package resolves to the logical name `update-<package>.py`, but runs in one of
two ways:

| Kind | Count | How it runs | Use when |
| :--- | ---: | :--- | :--- |
| Registry-driven | 19 | `update-package.py <package>`, config from `packages.json` | The package is fully described by `SoftwareVersionConfig` |
| Bespoke | 6 | Its own `update-<package>.py` | Multi-asset url arrays, custom version detection, redirect following, or bespoke hashing |

`update-all.py` discovers both: it globs `update-*.py` on disk and unions the keys of
`packages.json`. The logical name is what provider filtering, `--scripts`, `--skip-scripts`,
resume and the summaries key off, so both kinds behave identically from the outside.

### Registry format

`scripts/packages.json` maps package name to `SoftwareVersionConfig` keyword arguments:

```json
{
  "corecycler": {
    "homepage": "https://api.github.com/repos/sp00n/corecycler/tags",
    "version_patterns": ["v([\\d.]+)"],
    "download_url_template": "https://github.com/sp00n/CoreCycler/releases/download/v$version/CoreCycler-v$version.7z",
    "description": "CoreCycler - CPU stress testing tool for stability testing",
    "license": "MIT",
    "require_release_asset": true
  }
}
```

The manifest filename defaults to `<package>.json` in `bucket/`.

### When a bespoke updater is required

`ManifestUpdater.apply_download_metadata` assigns `url` and `hash` as **single strings**.
If upstream ships more than one asset per architecture, the base updater silently drops the
extra one. Subclass and override the mutation instead — `scripts/update-kuna.py` is the
reference:

```python
class KunaManifestUpdater(ManifestUpdater):
    def _stored_manifest_hash(self, manifest):
        # The base implementation stringifies the whole hash list, so an
        # array-shaped manifest never matches the upstream digest and every run
        # looks like a re-release.
        ...

    def apply_download_metadata(self, manifest, *, version, download_url,
                                hash_value, previous_version=None):
        # Write url/hash as arrays, then drop any stale top-level pair.
        ...
```

Two traps this subclass already handles, both of which bite silently:

- `_stored_manifest_hash` must return the **first** element, or the drift check fires on
  every run and re-downloads both assets forever.
- The assets are **positional**. Scoop pairs `extract_dir` with archives by index
  (`lib/decompress.ps1` in Scoop itself), so the archive owning the versioned folder must
  stay first.

Also bypass the framework when you need to control version detection — `update-widevinecdm.py`
fetches the version itself to capture regex match groups and passes `version_info=` to
`updater.update()`.

### Auto-commit

Never copy the auto-commit block. `git_helpers.maybe_auto_commit(name, manifest_path, argv)`
reads `--auto-commit` / `AUTO_COMMIT=1` / `SCOOP_AUTO_COMMIT=1`, commits the manifest and
pushes, and warns without failing the run.

## Running updates

```bash
python scripts/update-all.py --workers 6            # parallel (default)
python scripts/update-all.py --sequential           # one at a time, for debugging
python scripts/update-all.py --scripts corecycler   # only these packages
python scripts/update-all.py --skip-scripts kuna    # everything except
python scripts/update-all.py --only-providers github
python scripts/update-all.py --retry 2
python scripts/update-all.py --force                # rewrite unchanged manifests
python scripts/update-all.py --resume .temp/update-summary.json
python scripts/update-all.py --skip-git             # never commit or push
python scripts/update-all.py --dry-run              # list what would run
```

Orchestrator flags worth knowing: `--fast`, `--json-summary <path>`, `--md-summary <path>`,
`--structured-output`, `--fail-fast`, `--git-dry-run`.

### Provider throttling

`scripts/providers.json` maps each package to `github` / `google` / `microsoft` / `other`.
Each bucket gets its own semaphore, so a slow provider cannot starve the rest. Keep the map
complete — `automate-scoop.py audit-providers` re-derives it, and `--write-map` rewrites it.

### HTTP cache

`--http-cache --http-cache-ttl 1800` keeps GitHub responses for 30 minutes. The cache
auto-disables under pytest so mocked sessions are always consulted, and empty payloads are
never cached — a 200 with `[]` once poisoned a whole run window.

## Git integration

Unless `--skip-git`, the orchestrator stages changed manifests under `bucket/`, commits once
per package with a Conventional Commit subject, and pushes. Use `--git-dry-run` to see the
commands without running them.

## Summaries

- `--json-summary <path>` — machine-readable run report; `--resume` reads it back
- `--md-summary <path>` — markdown dashboard (generated; not committed)
- Webhook delivery is handled by `summary_utils.format_webhook_body`

## Environment variables

| Variable | Purpose |
| :--- | :--- |
| `SCOOP_UPDATE_WORKERS`, `SCOOP_UPDATE_TIMEOUT`, `SCOOP_RETRY_ATTEMPTS` | Parallelism, per-script timeout, retries |
| `MAX_GITHUB_WORKERS`, `MAX_GOOGLE_WORKERS`, `MAX_MICROSOFT_WORKERS` | Per-provider concurrency caps |
| `RELEASE_CACHE_TTL` | Release cache lifetime |
| `FORCE=1`, `SCOOP_FORCE=1` | Force mode for a single updater |
| `GITHUB_TOKEN` | Raises the GitHub API rate limit |
| `AUTOMATION_LIB_SILENT=1` | Silence `git_helpers` prints |
| `LOG_LEVEL`, `SCOOP_GIT_DRY_RUN` | Logging level, dry-run git |

## Adding a package

1. `bucket/<pkg>.json` — validate against `scripts/manifest_schema.json`
2. A `packages.json` entry, or a bespoke `update-<pkg>.py` if the shape is unusual
3. A `providers.json` entry
4. `python scripts/automate-scoop.py health` and `doctor`

`automate-scoop.py wizard` performs steps 1–2: it generates the manifest, then
`update-package.py --register <pkg>` derives the registry entry from that manifest's `checkver`
and `autoupdate` blocks. The derived entry scrapes the vendor page where a hand-written entry
often prefers a releases API, so treat it as a first draft. Registration refuses to touch a
package that already owns a bespoke updater — one manifest gets exactly one definition.

`software-configs.json` is only a seed for the `wizard` scaffolding flow — the queue of packages
still to be manifested. It is not the runtime source of truth and no updater reads it.

## The local gate

`automate-scoop.py health` runs schema validation plus `doctor --offline` in one command; it is
what the pre-commit hooks run on any `bucket/*.json` change. The `--offline` flag exists because
the zip-layout check downloads release archives, which a commit hook must never do. Run the full
`doctor` by hand, or in CI, when you want that check.

To regenerate the local health dashboard, run the updaters for real and render the summary:

```cmd
python scripts\update-all.py --skip-git --json-summary .temp\update-summary.json
python scripts\generate-dashboard.py .temp\update-summary.json docs\update-health.md
```

Do not add `--dry-run` here. The summary is written from live updater results *after* the
run, so a dry run returns before the writer is reached and leaves no file behind; `update-all.py`
now prints a warning if you combine the two flags.

## Troubleshooting

**No version found.** Check `version_patterns` against the real upstream page. For GitHub,
`require_release_asset: true` additionally requires the release to ship the asset the download
template expands to, which correctly rejects releases that publish no Windows binary.

**Succeeds but never detects an update.** Usually a `checkver` regex that stopped matching, or
an `extract_dir` still embedding the old version. `doctor` flags both.

**Doctor reports a bin as missing.** It verifies the *containing folder*, and resolves
`extract_dir` through the same `arch_specific` lookup Scoop uses — so an architecture-scoped
`extract_dir` is checked against that architecture's archive. A stale top-level `url`/`hash`
alongside a real architecture block is rejected outright as `architecture-shadow`.

**Git push should not happen.** Use `--skip-git` or `SCOOP_GIT_DRY_RUN=1`.

## Testing changes

```bash
python -m pytest tests/ -q
python -m pytest tests/test_version_detector.py -v
```

Tests must never hit the network. `conftest.py` provides shared fixtures and registers the
`slow`, `network`, `windows` and `linux` markers.

Note that `pre-commit run --all-files` skips untracked files — a green run before you commit a
new script says nothing about that script. Re-run it after `git add`.
