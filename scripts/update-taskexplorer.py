#!/usr/bin/env python3
"""
TaskExplorer Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import os
import sys
from pathlib import Path

from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "taskexplorer"
HOMEPAGE_URL = "https://api.github.com/repos/DavidXanatos/TaskExplorer/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/DavidXanatos/TaskExplorer/releases/download/v$version/TaskExplorer-v$version.exe#/setup.exe"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "taskexplorer.json"


def update_manifest():
    """Update the Scoop manifest using shared version detection."""
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['"tag_name":\\s*"v?([\\d.]+)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Advanced task manager with deep process and system inspection panels",
        license="Freeware",
    )

    version_info = get_version_info(config)
    if not version_info:
        if not structured_only:
            print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}))
        return False

    version = version_info["version"]
    download_url = version_info["download_url"]
    hash_value = version_info["hash"]

    try:
        with open(BUCKET_FILE, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError:
        print(f"❌ Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as exc:
        print(f"❌ Invalid JSON in manifest: {exc}")
        return False

    current_version = manifest.get("version", "")
    if current_version == version:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    manifest["version"] = version
    manifest["url"] = download_url
    manifest["hash"] = f"sha256:{hash_value}"

    try:
        with open(BUCKET_FILE, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)

        if not structured_only:
            print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True
    except Exception as exc:
        if not structured_only:
            print(f"❌ Failed to save manifest: {exc}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False


def main():
    """Main update function."""
    success = update_manifest()
    if not success:
        sys.exit(1)

    auto_commit = (
        "--auto-commit" in sys.argv
        or os.environ.get("AUTO_COMMIT") == "1"
        or os.environ.get("SCOOP_AUTO_COMMIT") == "1"
    )
    if auto_commit:
        try:
            from git_helpers import commit_manifest_change

            commit_manifest_change(SOFTWARE_NAME, str(BUCKET_FILE), push=True)
        except Exception as exc:
            print(f"⚠️  Auto-commit failed: {exc}")


if __name__ == "__main__":
    main()
