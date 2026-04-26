#!/usr/bin/env python3
"""
Atomic update script.

Automatically checks for new Atomic releases on GitHub and updates the Scoop
manifest using the shared version detector and manifest manager.
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

SOFTWARE_NAME = "atomic"
HOMEPAGE_URL = "https://api.github.com/repos/kenforthewin/atomic/releases/latest"
DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/kenforthewin/atomic/releases/download/"
    "v$version/Atomic_$version_x64-setup.exe#/setup.exe"
)
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """
    Update the Atomic Scoop manifest.

    Returns:
        True when the manifest is already current or was updated successfully.
    """
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r'"tag_name":\s*"v?([\d.]+)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description=(
            "AI-augmented personal knowledge base built from semantically "
            "connected markdown notes."
        ),
        license="MIT",
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
