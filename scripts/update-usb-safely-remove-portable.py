#!/usr/bin/env python3
"""
Usb Safely Remove Portable Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "usb-safely-remove-portable"
HOMEPAGE_URL = "https://safelyremove.com/"
DOWNLOAD_URL_TEMPLATE = ""
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "usb-safely-remove-portable.json"

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['Version ([\\d.]+)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="USB Safely Remove (Portable) - Safe removal of USB devices",
        license="Proprietary"
    )
    
    # Get version information using shared detector
    version_info = get_version_info(config)
    if not version_info:
        if not structured_only:
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