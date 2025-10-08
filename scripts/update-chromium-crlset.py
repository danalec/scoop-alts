#!/usr/bin/env python3
"""
Chromium Crlset Update Script
Fetches latest CRLSet info from Google's CRX update service and updates the Scoop manifest.
This avoids the complex $match replacements in Scoop and uses the direct codebase URL + hash.
"""

import json
import re
import sys
import requests
from pathlib import Path
from version_detector import VersionDetector

# Configuration
SOFTWARE_NAME = "chromium-crlset"
# Google's CRX update endpoint for CRLSet component
CRX_UPDATE_URL = (
    "https://clients2.google.com/service/update2/crx?x="
    "id%3Dhfnkpimlhhgieaddgfemjhofmfblmnib%26v%3D%26uc%26acceptformat%3Dcrx3"
)
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "chromium-crlset.json"

def update_manifest():
    """Update the Scoop manifest using Google's CRX update service"""
    print(f"🔄 Updating {SOFTWARE_NAME}...")

    session = requests.Session()
    session.headers.update({'Accept-Encoding': 'gzip'})

    try:
        resp = session.get(CRX_UPDATE_URL, timeout=30)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        print(f"❌ Failed to query CRX update service: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "query_failed"}))
        return False

    # Extract version, codebase (download URL), and sha256 hash from the response
    version_match = re.search(r'version=\"(\d+)\"', content)
    url_match = re.search(r'codebase=\"(https?://[^\"]+\.crx3)\"', content)
    hash_match = re.search(r'hash_sha256=\"([a-fA-F0-9]{64})\"', content)

    if not (version_match and url_match and hash_match):
        print("❌ Failed to parse CRX update response for version/url/hash")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "parse_failed"}))
        return False

    version = version_match.group(1)
    download_url = url_match.group(1)
    hash_value = hash_match.group(1).lower()
    
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
    # CRLSet manifest expects 'sha256:' prefix
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