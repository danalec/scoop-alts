#!/usr/bin/env python3
"""
Veracrypt Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared manifest updater framework (manifest_manager + version_detector).
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

SOFTWARE_NAME = "veracrypt"
HOMEPAGE_URL = "https://api.github.com/repos/veracrypt/VeraCrypt/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/veracrypt/VeraCrypt/releases/download/VeraCrypt_$version/VeraCrypt_Setup_x64_$version.msi"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """
    Update the VeraCrypt Scoop manifest.

    Returns:
        True when the manifest is already current or was updated successfully.
    """
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=["VeraCrypt_([\\d.]+\\d)"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="VeraCrypt - Disk encryption with strong security based on TrueCrypt",
        license="Apache-2.0",
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
