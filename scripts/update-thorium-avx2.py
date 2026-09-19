#!/usr/bin/env python3
"""
Thorium Avx2 Update Script
Automatically checks for updates and updates the Scoop manifest using the
shared version detector. AVX2 ZIP asset availability is asset-gated via the
framework (require_release_asset): only releases that ship the expected
Thorium_AVX2_<version>.zip asset are selected. Supports forced execution.
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig

# Configuration
SOFTWARE_NAME = "thorium-avx2"
HOMEPAGE_URL = "https://github.com/gz83/thorium/releases"
DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/gz83/thorium/releases/download/M$version/Thorium_AVX2_$version.zip"
)
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest(force: bool = False) -> bool:
    """Update the Scoop manifest via the standard framework flow (asset-gated)."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        # Fallback-only pattern: require_release_asset is the real gate for
        # AVX2 ZIP availability; this pattern only matters when the releases
        # API is unreachable.
        version_patterns=[r"releases/tag/M([\d.]+)"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Thorium AVX2 - Chromium fork named after radioactive element No. 90. Optimized for AVX2. If your CPU does not support AVX2 DO NOT INSTALL.",
        license="BSD-3-Clause",
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
