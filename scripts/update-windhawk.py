#!/usr/bin/env python3
"""
Windhawk Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "windhawk"
# Use GitHub Releases API for reliable version detection
HOMEPAGE_URL = "https://api.github.com/repos/ramensoftware/windhawk/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/ramensoftware/windhawk/releases/download/v$version/windhawk_setup.exe#/setup.exe"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "windhawk.json"

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    print(f"🔄 Updating {SOFTWARE_NAME}...")
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        # Extract semantic version from GitHub API response (tag_name)
        version_patterns=[r'tag_name"\s*:\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="The customization marketplace for Windows programs",
        license="GPL-3.0-or-later"
    )
    
    # Get version information using shared detector
    version_info = get_version_info(config)
    if not version_info:
        print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
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
        return True
    
    # Update manifest
    manifest['version'] = version
    manifest['url'] = download_url
    # Persist raw SHA256 hex string to match bucket style
    manifest['hash'] = hash_value
    
    # Save updated manifest
    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to save manifest: {e}")
        return False

def main():
    """Main update function"""
    success = update_manifest()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()