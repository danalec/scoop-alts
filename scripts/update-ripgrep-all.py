#!/usr/bin/env python3
"""
Ripgrep-All Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
import requests
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info, VersionDetector

# Configuration
SOFTWARE_NAME = "ripgrep-all"
HOMEPAGE_URL = "https://api.github.com/repos/phiresky/ripgrep-all/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/phiresky/ripgrep-all/releases/download/v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "ripgrep-all.json"

def find_latest_windows_version():
    """Find the latest version that has Windows assets available."""
    try:
        # Get all releases
        response = requests.get("https://api.github.com/repos/phiresky/ripgrep-all/releases", timeout=30)
        response.raise_for_status()
        releases = response.json()
        
        for release in releases:
            version = release['tag_name'].lstrip('v')
            # Check if this release has Windows assets
            windows_assets = [asset for asset in release['assets'] 
                            if 'windows' in asset['name'].lower() and asset['name'].endswith('.zip')]
            if windows_assets:
                return version, windows_assets[0]['browser_download_url']
                
        return None, None
    except Exception as e:
        print(f"❌ Failed to fetch releases: {e}")
        return None, None

def update_manifest():
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    # Find the latest version with Windows assets
    version, download_url = find_latest_windows_version()
    if not version or not download_url:
        if not structured_only:
            print(f"❌ No Windows assets found for any {SOFTWARE_NAME} release")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "no_windows_assets"}))
        return False

    if not structured_only:
        print(f"✅ Found latest Windows version: {version}")
        print(f"📦 Download URL: {download_url}")

    # Calculate hash for the download URL
    detector = VersionDetector()
    hash_value = detector.calculate_hash(download_url)
    if not hash_value:
        if not structured_only:
            print(f"❌ Failed to calculate hash for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "hash_calculation_failed"}))
        return False

    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        if not structured_only:
            print(f"❌ Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as e:
        if not structured_only:
            print(f"❌ Invalid JSON in manifest: {e}")
        return False

    current_version = manifest.get('version', '')
    if current_version == version:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = f"sha256:{hash_value}"

    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        if not structured_only:
            print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True

    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False

def main():
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
        except Exception as e:
            print(f"⚠️  Auto-commit failed: {e}")

if __name__ == "__main__":
    main()
