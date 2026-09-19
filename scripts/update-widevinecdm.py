#!/usr/bin/env python3
"""
Widevinecdm Update Script

Automatically checks for updates and updates the Scoop manifest using the
shared manifest updater framework (manifest_manager + version_detector).
The per-architecture Google release2 URLs are built from named regex match
groups via SoftwareVersionConfig(architecture_templates=...).
"""

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig, VersionDetector

SOFTWARE_NAME = "widevinecdm"
HOMEPAGE_URL = "https://scoopinstaller.github.io/UpdateTracker/googlechrome/chrome.min.xml"
DOWNLOAD_URL_TEMPLATE = "https://dl.google.com/release2/chrome/$matcharch64_$version/$version_chrome_installer_uncompressed.exe#/chrome.7z"
VERSION_PATTERNS = [
    "(?sm)<stable32><version>(?P<version>[\\d.]+)</version>.+release2/chrome/(?P<arch32>[\\w-]+)_.+<stable64>.+release2/chrome/(?P<arch64>[\\w-]+)_.+</stable64>"
]
ARCHITECTURE_TEMPLATES = {
    "64bit": DOWNLOAD_URL_TEMPLATE,
    "32bit": "https://dl.google.com/release2/chrome/$matcharch32_$version/$version_chrome_installer_uncompressed.exe#/chrome.7z",
}
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def update_manifest() -> bool:
    """
    Update the Widevine CDM Scoop manifest.

    Returns:
        True when the manifest is already current or was updated successfully.
    """
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=VERSION_PATTERNS,
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="A browser plugin designed for the viewing of premium video content",
        license="Proprietary",
        architecture_templates=ARCHITECTURE_TEMPLATES,
    )
    updater = ManifestUpdater(config, BUCKET_DIR)

    # Fetch the version here so detection runs before any download and the
    # per-architecture hashes are computed exactly once per entry by
    # ManifestUpdater.apply_architecture_templates.
    result = VersionDetector().fetch_latest_version(HOMEPAGE_URL, VERSION_PATTERNS)
    if not result:
        updater.log(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        updater.emit_result(updated=False, error="version_info_unavailable")
        return False

    version_info = {
        "version": result.version,
        "download_url": "",
        "hash": None,
        "match_groups": result.match_groups,
    }
    return updater.update(version_info=version_info)


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
