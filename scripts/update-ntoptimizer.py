#!/usr/bin/env python3
"""
Ntoptimizer Update Script
Uses a static download URL and extracts version from executable metadata. Keeps 'sha256:' hash style.
"""

import json
import sys
from pathlib import Path
from version_detector import VersionDetector

# Configuration
SOFTWARE_NAME = "ntoptimizer"
HOMEPAGE_URL = "https://bestorderflow.com/"
# Static download URL as per manifest
STATIC_DOWNLOAD_URL = "https://www.netoptimizer.com/files/NetOptimizer.exe"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "ntoptimizer.json"

def update_manifest():
    """Update the Scoop manifest using static URL and executable metadata"""
    print(f"🔄 Updating {SOFTWARE_NAME}...")

    detector = VersionDetector()

    # Determine download URL (static)
    download_url = STATIC_DOWNLOAD_URL

    # Try to derive version from executable metadata
    version = detector.get_version_from_executable(download_url) or ""
    if not version:
        print("⚠️ Could not extract version from executable; will keep current manifest version.")

    # Calculate hash
    hash_value = detector.calculate_hash(download_url)
    if not hash_value:
        print(f"❌ Failed to calculate hash for {SOFTWARE_NAME}")
        return False
    
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
    if version and current_version == version:
        print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        return True
    
    # Update manifest
    if version:
        manifest['version'] = version
    manifest['url'] = download_url
    # Keep sha256: prefix to match manifest style
    manifest['hash'] = f"sha256:{hash_value}"
    
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