#!/usr/bin/env python3
"""
Ripgrep All Update Script
Automatically checks for updates and updates the Scoop manifest using the
shared version detector. Windows-binary availability is asset-gated via the
framework (require_release_asset): only releases that ship the expected
Windows ZIP asset are selected. Supports forced execution.
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig

# Configuration
SOFTWARE_NAME = "ripgrep-all"
HOMEPAGE_URL = "https://github.com/phiresky/ripgrep-all/releases"
DOWNLOAD_URL_TEMPLATE = "https://github.com/phiresky/ripgrep-all/releases/download/v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest(force: bool = False) -> bool:
    """Update the Scoop manifest via the standard framework flow (asset-gated)."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        # Fallback-only pattern: require_release_asset is the real gate for
        # Windows-binary availability; this pattern only matters when the
        # releases API is unreachable, where a hash fetch failure surfaces
        # loudly instead of pinning a version series.
        version_patterns=[r"releases/tag/v([\d.]+)"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Ripgrep-All - Search in PDFs, e-books, Office docs, archives, and media via ripgrep",
        license="AGPL-3.0-or-later",
        require_release_asset=True,
    )

    updater = ManifestUpdater(config, BUCKET_DIR, force=force)
    return updater.update()


def main() -> None:
    """Main update function."""
    success = update_manifest(force=is_forced())
    if not success:
        sys.exit(1)

    # Optional per-script auto-commit helper
    auto_commit = (
        "--auto-commit" in sys.argv
        or os.environ.get("AUTO_COMMIT") == "1"
        or os.environ.get("SCOOP_AUTO_COMMIT") == "1"
    )
    if auto_commit:
        try:
            from git_helpers import commit_manifest_change

            commit_manifest_change(
                SOFTWARE_NAME, str(BUCKET_DIR / f"{SOFTWARE_NAME}.json"), push=True
            )
        except Exception as e:
            print(f"⚠️  Auto-commit failed: {e}")


if __name__ == "__main__":
    main()
