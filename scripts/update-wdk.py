#!/usr/bin/env python3
"""
Windows Driver Kit (WDK) Update Script
Automatically checks for updates and updates the Scoop manifest using the shared version detector.
This script supports a fallback mechanism to extract the version directly from the WDK setup executable
when the release notes page doesn't expose explicit version strings.
"""

import json
import sys
import os
from pathlib import Path
from typing import Optional
from version_detector import SoftwareVersionConfig, VersionDetector

# Configuration
SOFTWARE_NAME = "wdk"
HOMEPAGE_URL = "https://learn.microsoft.com/en-us/windows-hardware/drivers/wdk-release-notes"
DOWNLOAD_URL_TEMPLATE = "https://go.microsoft.com/fwlink/?linkid=2335869#/wdksetup.exe"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / f"{SOFTWARE_NAME}.json"

# Prefer explicit version strings if present on the page; otherwise, fall back to exe metadata
VERSION_PATTERNS = [
    r"Version\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)",
    r"WDK\s+Version\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)",
]


def update_manifest() -> bool:
    """Update the WDK Scoop manifest using shared version detector with fallbacks."""
    print(f"🔄 Updating {SOFTWARE_NAME}...")

    detector = VersionDetector()

    # Try to scrape version from release notes
    print("🔍 Attempting to parse version from release notes...")
    version: Optional[str] = detector.fetch_latest_version(HOMEPAGE_URL, VERSION_PATTERNS)

    # Fallback: infer/extract version from setup executable if scraping fails
    if not version:
        print("ℹ️  Version not found on release notes; falling back to executable metadata...")
        version = detector.get_version_from_executable(DOWNLOAD_URL_TEMPLATE.split('#', 1)[0])

    if not version:
        print(f"❌ Failed to determine version for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_unavailable"}))
        return False

    # Compute hash of the setup executable
    print("🔍 Calculating installer hash...")
    hash_value = detector.calculate_hash(DOWNLOAD_URL_TEMPLATE)
    if not hash_value:
        print(f"❌ Failed to calculate hash for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "hash_unavailable", "version": version}))
        return False

    created_new_manifest = False
    # Load existing manifest
    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"⚠️  Manifest file not found: {BUCKET_FILE}. Creating a new one.")
        manifest = {
            "version": version,
            "description": "Windows Driver Kit (WDK) - tools, headers, and libraries to develop Windows drivers",
            "homepage": "https://learn.microsoft.com/en-us/windows-hardware/drivers/download-the-wdk",
            "license": "Proprietary",
            "url": DOWNLOAD_URL_TEMPLATE,
            "hash": hash_value,
            "notes": [
                "Requires Visual Studio 2022 and a matching Windows SDK version for the target build.",
                "The installer is a bootstrapper that will download required components.",
                "For a self-contained environment, consider EWDK (Enterprise WDK)."
            ],
            "installer": {
                "script": "Start-Process -Wait \"$dir\\wdksetup.exe\" -ArgumentList '/quiet /norestart' -Verb RunAs"
            },
            "checkver": {
                "url": HOMEPAGE_URL,
                "regex": "Version\\s+([0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+)"
            },
            "autoupdate": {
                "url": DOWNLOAD_URL_TEMPLATE
            }
        }
        created_new_manifest = True
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in manifest: {e}")
        return False

    # If new manifest was created, save it immediately
    if created_new_manifest:
        try:
            with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            print(f"✅ Created new manifest for {SOFTWARE_NAME} (v{version})")
            print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
            return True
        except Exception as e:
            print(f"❌ Failed to save new manifest: {e}")
            print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "create_save_failed"}))
            return False

    # Check if update is needed
    current_version = manifest.get('version', '')
    if current_version == version and manifest.get('hash') == hash_value:
        print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    # Update manifest fields
    manifest['version'] = version
    manifest['url'] = DOWNLOAD_URL_TEMPLATE
    manifest['hash'] = hash_value

    # Save updated manifest
    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True
    except Exception as e:
        print(f"❌ Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False


def main():
    success = update_manifest()
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
            commit_manifest_change(SOFTWARE_NAME, str(BUCKET_FILE), push=True)
        except Exception as e:
            print(f"⚠️  Auto-commit failed: {e}")


if __name__ == "__main__":
    main()