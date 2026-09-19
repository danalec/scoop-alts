#!/usr/bin/env python3
"""
Ntoptimizer Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared framework (version_detector + manifest_manager).
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

# Configuration
# NTOptimizer is a NinjaTrader optimizer tool distributed by bestorderflow.com.
# Do NOT substitute netoptimizer.com here - that is an unrelated network-tuning
# product whose executable happened to pattern-match the name (see commit f33e861
# which introduced the mix-up; the original manifest at 80c1b2d used the zip below).
SOFTWARE_NAME = "ntoptimizer"
HOMEPAGE_URL = "https://bestorderflow.com/"
# Static vendor zip; contains NTOptimizer.exe + .ico at the archive root. No
# $version placeholder, so version detection falls back to executable metadata.
DOWNLOAD_URL_TEMPLATE = "https://bestorderflow.com/images/free/NTOptimizer.zip"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """Update the Scoop manifest using the shared framework."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r"Version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)+(?:\.[0-9]+)?)"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Optimizer tool for NinjaTrader",
        license="Proprietary",
    )
    return ManifestUpdater(config, BUCKET_DIR).update()


def main() -> None:
    """Run the update workflow and optionally auto-commit the manifest."""
    if not update_manifest():
        sys.exit(1)

    auto_commit = (
        "--auto-commit" in sys.argv
        or os.environ.get("AUTO_COMMIT") == "1"
        or os.environ.get("SCOOP_AUTO_COMMIT") == "1"
    )
    if auto_commit:
        try:
            from git_helpers import commit_manifest_change

            commit_manifest_change(
                SOFTWARE_NAME,
                str(BUCKET_DIR / f"{SOFTWARE_NAME}.json"),
                push=True,
            )
        except Exception as exc:
            print(f"⚠️  Auto-commit failed: {exc}")


if __name__ == "__main__":
    main()
