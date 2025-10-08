#!/usr/bin/env python3
"""
Depressurizer Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "depressurizer"
HOMEPAGE_URL = "https://api.github.com/repos/julianxhokaxhiu/Depressurizer/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/julianxhokaxhiu/Depressurizer/releases/download/$version/Depressurizer-v$version.0_Release.zip"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "depressurizer.json"

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    print(f"🔄 Updating {SOFTWARE_NAME}...")
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['"tag_name":\\s*"v?([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)"', '([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Depressurizer - A Steam library categorizing tool",
        license="GPL-3.0"
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
    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = f"sha256:{hash_value}"
    
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

if __name__ == "__main__":
    main()