# Contributing

Thanks for helping. The short version: **never hand-edit a manifest version or hash** —
change the updater and run it.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -r scripts/requirements-automation.txt
pre-commit install
python -m pytest tests/ -q
```

Requires Python 3.11+ and git. Scoop is optional, for local install testing.

## Adding a package

1. Create `bucket/<package>.json`. Validate against `scripts/manifest_schema.json`.
2. Add a `scripts/packages.json` entry, or write a bespoke `scripts/update-<package>.py` if
   the shape is unusual (multi-asset `url` arrays, custom version detection, redirect
   following). See [docs/AUTOMATION.md](docs/AUTOMATION.md).
3. Add the package to `scripts/providers.json` for rate-limit throttling.
4. Run it, then validate:

```bash
python scripts/update-package.py <package>
python scripts/automate-scoop.py validate
python scripts/automate-scoop.py doctor
```

`automate-scoop.py wizard` scaffolds a package interactively. `software-configs.json` is only a
seed for that wizard, not the runtime source of truth.

Reporting bugs and proposing enhancements: open a GitHub issue. For security issues, follow
[SECURITY.md](SECURITY.md) — never a public issue.

## Before you open a PR

```bash
python -m pytest tests/ -q
python -m ruff check scripts
python -m black --check scripts
python -m flake8 scripts
python scripts/automate-scoop.py validate
python scripts/automate-scoop.py doctor   # needs p7zip-full on Linux CI
```

These are exactly what CI runs. Two things that catch people out:

- `pre-commit run --all-files` **skips untracked files**, so a green run before you commit a
  new script proves nothing about that script. Re-run it after `git add`.
- On Windows, prefix Python invocations with `PYTHONIOENCODING=utf-8` — the scripts print
  emoji and a cp1252 console raises `UnicodeEncodeError`.

## Pull requests

1. Branch from `main`: `git checkout -b feature/my-change`. Never push to `main`.
2. Make the change, add tests for new behavior.
3. Commit with Conventional Commits:

   ```text
   <type>(<scope>): <description>

   # types: feat, fix, docs, style, refactor, test, chore
   # e.g. feat(bucket): add <package>
   #      fix(scripts): resolve hash computation
   ```

4. Push and open the PR; ensure CI is green.

Note that the Docker scheduler is the only automatic writer of `main` and pushes hourly, so a
long-lived branch can fall behind. Rebase before opening a PR; that is expected.

## Conventions

**Python** — Black at line length 100, type hints on public functions, docstrings on public
functions and classes, comments that explain *why*. Optional dependencies (`requests`, `bs4`,
`packaging`, `rich`, `playwright`, `requests-cache`) are imported defensively behind
`try/except ImportError` and the suite must not hard-fail when one is absent.

**Naming** — `update-<package>.py` for updaters, `snake_case.py` for shared modules. Classes
`PascalCase`, functions `snake_case`, constants `UPPER_SNAKE_CASE`.

**Line endings** — `.editorconfig` forces CRLF for all text files, because Scoop is
Windows-only. `docker/bin/*.sh` and `Dockerfile` are pinned to LF since `#!/bin/sh` shebangs
break under CRLF. Do not normalize line endings by hand.

**Tests** — `test_<function>_<scenario>_<expected>`, placed in `tests/`. Tests must never hit
the network; mock the session. Both `unittest.TestCase` and plain pytest styles are in use —
match the file you are editing.

**Language** — all documentation, comments and commit messages in English.

Full agent-facing rules live in [AGENTS.md](AGENTS.md).

## Code of Conduct

This project follows the [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
