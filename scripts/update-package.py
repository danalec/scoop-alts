#!/usr/bin/env python3
"""
Registry-driven update script.

Packages whose manifest update is fully described by ``SoftwareVersionConfig``
are declared in ``scripts/packages.json`` and executed through this single
runner instead of one copy-pasted script per package. Packages that need custom
mutation logic (multi-asset url arrays, bespoke hashing, redirect following)
keep their own ``update-<pkg>.py`` and are still discovered by the orchestrator.

Usage:
    python scripts/update-package.py <package-name> [--force]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS_DIR = Path(__file__).parent
sys.path.append(str(SCRIPTS_DIR))

from git_helpers import maybe_auto_commit  # noqa: E402
from manifest_manager import ManifestUpdater, is_forced  # noqa: E402
from version_detector import SoftwareVersionConfig  # noqa: E402

REGISTRY_PATH = SCRIPTS_DIR / "packages.json"
BUCKET_DIR = SCRIPTS_DIR.parent / "bucket"

DEFAULT_VERSION_REGEX = r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
ARCH_PREFERENCE = ("64bit", "32bit", "arm64")


def load_registry(path: Path = REGISTRY_PATH) -> Dict[str, Dict[str, Any]]:
    """Return the package registry, keyed by package name."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _autoupdate_url(manifest: Dict[str, Any]) -> str:
    """Return the download URL template declared by a manifest's autoupdate."""
    autoupdate = manifest.get("autoupdate")
    if not isinstance(autoupdate, dict):
        return ""

    url = autoupdate.get("url", "")
    if url:
        return url

    architecture = autoupdate.get("architecture")
    if isinstance(architecture, dict):
        for key in ARCH_PREFERENCE:
            entry = architecture.get(key)
            if isinstance(entry, dict) and entry.get("url"):
                return entry["url"]
    return ""


def manifest_to_entry(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Derive a registry entry from a Scoop manifest.

    This replaces the old per-package boilerplate generator: everything a
    registry entry can express already lives in the manifest's own ``checkver``
    and ``autoupdate`` blocks, so a generated ``update-<pkg>.py`` was a 125-line
    transcription of the same four values.
    """
    checkver = manifest.get("checkver")
    if isinstance(checkver, dict):
        homepage = checkver.get("url") or manifest.get("homepage", "")
        version_regex = checkver.get("regex") or DEFAULT_VERSION_REGEX
    else:
        homepage = manifest.get("homepage", "")
        version_regex = DEFAULT_VERSION_REGEX

    download_url_template = _autoupdate_url(manifest)
    entry: Dict[str, Any] = {
        "homepage": homepage,
        "version_patterns": [version_regex],
        "download_url_template": download_url_template,
        "description": manifest.get("description", ""),
        "license": manifest.get("license", "Unknown"),
    }

    # Only meaningful when a template actually points at plain http.
    if any(str(value).lower().startswith("http://") for value in (homepage, download_url_template)):
        entry["force_https"] = True

    return entry


def register_package(
    name: str,
    bucket_dir: Path = BUCKET_DIR,
    registry_path: Path = REGISTRY_PATH,
    scripts_dir: Path = SCRIPTS_DIR,
) -> bool:
    """Add or refresh one registry entry from ``bucket/<name>.json``.

    Refuses when the package already owns a bespoke ``update-<pkg>.py``: such a
    script exists precisely because a registry entry cannot express what the
    package needs (multi-asset url arrays, custom hashing, redirect following),
    so a second definition would give the orchestrator a conflict to resolve.
    """
    manifest_path = bucket_dir / f"{name}.json"
    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        return False

    bespoke = scripts_dir / f"update-{name}.py"
    if bespoke.exists() and bespoke.resolve() != Path(__file__).resolve():
        print(
            f"❌ {name} has a bespoke updater ({bespoke.name}); "
            "a registry entry would conflict with it"
        )
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest_to_entry(manifest)
    if not entry["homepage"] or not entry["download_url_template"]:
        print(f"❌ {name}: manifest has no homepage or autoupdate url to derive from")
        return False

    registry = load_registry(registry_path) if registry_path.exists() else {}
    existed = name in registry
    registry[name] = entry
    registry_path.write_text(
        json.dumps(dict(sorted(registry.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    verb = "Updated" if existed else "Registered"
    print(f"✅ {verb} '{name}' in {registry_path}")
    if not existed:
        print("   Derived from the manifest; review the patterns before relying on them.")
        print("   Run: python scripts/update-package.py " + name + " --force")
    return True


def build_config(name: str, entry: Dict[str, Any]) -> SoftwareVersionConfig:
    """Turn one registry entry into a detector config."""
    return SoftwareVersionConfig(name=name, **entry)


def update_manifest(name: str, registry: Dict[str, Dict[str, Any]], force: bool = False) -> bool:
    """Update one registry package via the standard framework flow."""
    entry = registry.get(name)
    if entry is None:
        print(f"❌ Unknown package: {name}")
        return False

    updater = ManifestUpdater(build_config(name, entry), BUCKET_DIR, force=force)
    return updater.update()


def main(argv: List[str]) -> None:
    """Entry point: ``update-package.py <package> [--force]`` or ``--register <name>``."""
    if "--register" in argv:
        names = [a for a in argv if not a.startswith("-")]
        if len(names) != 1:
            print("Usage: update-package.py --register <package-name>")
            sys.exit(2)
        if not register_package(names[0]):
            sys.exit(1)
        return

    args = [a for a in argv if not a.startswith("-")]
    flags = [a for a in argv if a.startswith("-")]

    if len(args) != 1:
        print("Usage: update-package.py <package-name> [--force]")
        sys.exit(2)

    name = args[0]
    registry = load_registry()
    force = is_forced() or bool({"--force", "-f", "--forcedly", "forcedly"} & set(flags))

    if not update_manifest(name, registry, force=force):
        sys.exit(1)

    maybe_auto_commit(name, BUCKET_DIR / f"{name}.json", sys.argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
