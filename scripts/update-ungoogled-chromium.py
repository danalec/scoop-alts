#!/usr/bin/env python3
"""
Ungoogled Chromium Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared manifest updater framework (manifest_manager + version_detector).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig

SOFTWARE_NAME = "ungoogled-chromium"
HOMEPAGE_URL = (
    "https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases/latest"
)
DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/"
    "$version/ungoogled-chromium_$version_windows_x64.zip"
)
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest(force: bool = False) -> bool:
    """
    Update the Ungoogled Chromium Scoop manifest.

    Args:
        force: Whether to force manifest regeneration even if version matches.

    Returns:
        True when the manifest is already current or was updated successfully.
    """
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r'"tag_name":\s*"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.[0-9]+)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        extract_dir="ungoogled-chromium_$version_windows_x64",
        description="Ungoogled Chromium - Google Chromium without Google's integration",
        license="BSD-3-Clause",
    )
    updater = ManifestUpdater(config, BUCKET_DIR, force=force)
    return updater.update()


def main() -> None:
    """Run the update workflow and optionally auto-commit the manifest."""
    if not update_manifest(force=is_forced()):
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
        except Exception as error:
            print(f"⚠️  Auto-commit failed: {error}")


if __name__ == "__main__":
    main()
