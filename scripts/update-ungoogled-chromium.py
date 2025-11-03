#!/usr/bin/env python3
"""
Ungoogled Chromium Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "ungoogled-chromium"
HOMEPAGE_URL = "https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/$version/ungoogled-chromium_$version_windows_x64.zip"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "ungoogled-chromium.json"

def _apply_updates_with_whitelist(manifest: dict, updates: dict, allowed_keys: list) -> None:
    """Set only allowed top-level keys in the manifest.

    This prevents accidental overwrites of fields like post_install, uninstaller, or persist.
    """
    for k in allowed_keys:
        if k in updates:
            manifest[k] = updates[k]

    # Handle autoupdate subkeys safely
    if 'autoupdate' in updates:
        if 'autoupdate' not in manifest or not isinstance(manifest['autoupdate'], dict):
            manifest['autoupdate'] = {}
        for sub_k, sub_v in updates['autoupdate'].items():
            manifest['autoupdate'][sub_k] = sub_v

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    print(f"🔄 Updating {SOFTWARE_NAME}...")
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['"tag_name":\\s*"v?([0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+(?:-[0-9.]+)?)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Ungoogled Chromium - Google Chromium without Google's integration",
        license="BSD-3-Clause"
    )
    
    # Get version information using shared detector
    version_info = get_version_info(config)
    if not version_info:
        print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}))
        return False
    
    version = version_info['version']
    download_url = version_info['download_url']
    hash_value = version_info['hash']
    
    # Load existing manifest
    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"❌ Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in manifest: {e}")
        return False
    
    # Check if update is needed
    current_version = manifest.get('version', '')
    if current_version == version:
        print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True
    
    # Update manifest
    updates = {
        'version': version,
        'url': download_url,
        'hash': f"sha256:{hash_value}",
        'extract_dir': f"ungoogled-chromium_{version}_windows_x64",
        'autoupdate': {
            'extract_dir': "ungoogled-chromium_$version_windows_x64",
            'url': DOWNLOAD_URL_TEMPLATE,
        }
    }
    _apply_updates_with_whitelist(
        manifest,
        updates,
        allowed_keys=['version', 'url', 'hash', 'extract_dir', 'autoupdate']
    )
    
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
    """Main update function"""
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
