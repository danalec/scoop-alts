#!/usr/bin/env python3
"""
Thorium Avx2 Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import os
import sys
from pathlib import Path
from version_detector import get_session

# Configuration
SOFTWARE_NAME = "thorium-avx2"
RELEASES_API_URL = "https://api.github.com/repos/gz83/thorium/releases"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "thorium-avx2.json"


def get_release_info():
    """Return the newest release that actually ships a Windows AVX2 ZIP asset."""
    session = get_session()
    response = session.get(RELEASES_API_URL, timeout=30)
    response.raise_for_status()

    releases = response.json()
    asset_names = [
        "Thorium_AVX2_{version}.zip",
        "thorium-browser_{version}_AVX2.zip",
    ]

    for release in releases:
        tag_name = release.get("tag_name", "")
        version = tag_name[1:] if tag_name.startswith("M") else tag_name
        assets = release.get("assets", [])

        for asset_name in asset_names:
            expected = asset_name.format(version=version)
            for asset in assets:
                if asset.get("name") == expected:
                    return {
                        "version": version,
                        "download_url": asset.get("browser_download_url", ""),
                        "hash": (asset.get("digest") or "").removeprefix("sha256:"),
                    }

    return None

def update_manifest():
    """Update the Scoop manifest from the latest asset-bearing gz83/thorium release."""
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    release_info = get_release_info()
    if not release_info:
        if not structured_only:
            print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}))
        return False

    version = release_info['version']
    download_url = release_info['download_url']
    hash_value = release_info['hash']
    
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
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True
    
    # Update manifest
    manifest['version'] = version
    # Prefer architecture-specific update when manifest uses architecture blocks
    arch = manifest.get('architecture')
    if isinstance(arch, dict) and arch:
        # Choose preferred architecture key
        arch_key = '64bit' if '64bit' in arch else ('arm64' if 'arm64' in arch else ('32bit' if '32bit' in arch else next(iter(arch.keys()))))
        if isinstance(arch.get(arch_key), dict):
            arch_entry = arch[arch_key]
            arch_entry['url'] = download_url
            arch_entry['hash'] = f"sha256:{hash_value}"
            manifest['architecture'][arch_key] = arch_entry
        else:
            # Fallback to top-level if architecture entry is not a dict
            manifest['url'] = download_url
            manifest['hash'] = f"sha256:{hash_value}"
    else:
        manifest['url'] = download_url
        manifest['hash'] = f"sha256:{hash_value}"
    
    # Save updated manifest
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
