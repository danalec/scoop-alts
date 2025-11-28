#!/usr/bin/env python3
"""
Ntoptimizer Update Script
Uses a static download URL and extracts version from executable metadata. Keeps 'sha256:' hash style.
"""

import json
import sys
import os
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
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    detector = VersionDetector()

    # Determine download URL (static)
    download_url = STATIC_DOWNLOAD_URL

    # Try to derive version from executable metadata
    version = detector.get_version_from_executable(download_url) or ""
    if not version:
        if not structured_only:
            print("⚠️ Could not extract version from executable; will keep current manifest version.")

    # Calculate hash
    hash_value = detector.calculate_hash(download_url)
    if not hash_value:
        if not structured_only:
            print(f"❌ Failed to calculate hash for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "hash_failed"}))
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
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
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
        if not structured_only:
            print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version or manifest.get('version', '')}))
        return True

    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version or manifest.get('version', ''), "error": "save_failed"}))
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
