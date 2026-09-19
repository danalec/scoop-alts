#!/usr/bin/env python3
"""
Depressurizer Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared framework (version_detector + manifest_manager).
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

# Configuration
SOFTWARE_NAME = "depressurizer"
HOMEPAGE_URL = "https://api.github.com/repos/julianxhokaxhiu/Depressurizer/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/julianxhokaxhiu/Depressurizer/releases/download/$version/Depressurizer-v$version.0_Release.zip"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """Update the Scoop manifest using the shared framework."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r'"tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Depressurizer - A Steam library categorizing tool",
        license="GPL-3.0",
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
