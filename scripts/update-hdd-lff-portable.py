#!/usr/bin/env python3
"""
Hdd Lff Portable Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared framework (version_detector + manifest_manager).
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

# Configuration
SOFTWARE_NAME = "hdd-lff-portable"
HOMEPAGE_URL = "https://hddguru.com/software/HDD-LLF-Low-Level-Format-Tool/"
DOWNLOAD_URL_TEMPLATE = (
    "https://hddguru.com/software/HDD-LLF-Low-Level-Format-Tool/HDDLLF.$version.exe"
)
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """Update the Scoop manifest using the shared framework."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r"HDDLLF\.([\d\.]+)\.exe"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="HDD Low Level Format Tool (Portable) - A utility for low-level formatting of SATA, IDE, SAS, SCSI or SSD drives",
        license="Freeware",
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
