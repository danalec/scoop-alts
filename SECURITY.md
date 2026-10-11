# Security Policy

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting:
[Security Advisories → Report a vulnerability](https://github.com/danalec/scoop-alts/security/advisories).

Include the description, steps to reproduce, impact, a suggested fix if you have one, and a
contact address. Initial response within 48 hours, status update within 7 days, critical fixes
within 30 days. We follow [responsible disclosure](https://en.wikipedia.org/wiki/Responsible_disclosure)
and will credit you in the advisory unless you prefer otherwise.

## Contributors

- **Never commit secrets.** Use environment variables (`GITHUB_TOKEN`, and so on).
- **Verify manifest URLs and hashes.** Every `hash` is `sha256:<hex>`, recomputed by the
  updater from the upstream artifact — never copied from an existing manifest.
- **HTTPS everywhere.** `automate-scoop.py doctor` fails manifests that download over plain
  HTTP.
- **Validate external input.** Upstream pages and JSON responses are untrusted.

## Users

- Review manifests before installing, especially for packages sourced outside GitHub.
- `scoop update` re-verifies hashes on every install.
- Some manifests change registry state — `ungoogled-chromium` can register itself as the
  default browser. That is opt-in (`SCOOP_SET_DEFAULT_BROWSER=1`), documented in the manifest,
  and reverted on uninstall.

## Coverage

Actively maintained; security fixes are applied to the current state of `main`.

Dependabot and the pre-commit hooks cover dependency and manifest linting.
