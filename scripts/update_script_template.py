#!/usr/bin/env python3
"""
Template for Scoop Update Scripts using Shared Version Detector
This template can be used to generate update scripts that use the shared version detection logic.
"""

import json
import sys
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

def update_manifest(software_name: str, config: SoftwareVersionConfig, bucket_file: str):
    """
    Update a Scoop manifest using shared version detection
    
    Args:
        software_name: Name of the software package
        config: Software version configuration
        bucket_file: Path to the manifest file in the bucket
    """
    print(f"🔄 Updating {software_name}...")
    
    # Get version information using shared detector
    version_info = get_version_info(config)
    if not version_info:
        print(f"❌ Failed to get version info for {software_name}")
        # Emit structured output for orchestrator
        print(json.dumps({"updated": False, "name": software_name, "error": "version_info_unavailable"}))
        return False
    
    version = version_info['version']
    download_url = version_info['download_url']
    hash_value = version_info['hash']
    
    # Load existing manifest
    try:
        with open(bucket_file, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"❌ Manifest file not found: {bucket_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in manifest: {e}")
        return False
    
    # Check if update is needed
    current_version = manifest.get('version', '')
    if current_version == version:
        print(f"✅ {software_name} is already up to date (v{version})")
        # Emit structured output for orchestrator
        print(json.dumps({"updated": False, "name": software_name, "version": version}))
        return True
    
    # Update manifest
    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = f"sha256:{hash_value}"
    
    # Save updated manifest
    try:
        with open(bucket_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Updated {software_name}: {current_version} → {version}")
        # Emit structured output for orchestrator
        print(json.dumps({"updated": True, "name": software_name, "version": version}))
        return True
        
    except Exception as e:
        print(f"❌ Failed to save manifest: {e}")
        # Emit structured output for orchestrator
        print(json.dumps({"updated": False, "name": software_name, "version": version, "error": "save_failed"}))
        return False

# Example usage template - replace with actual software configuration
def main():
    """Main update function - customize this for each software package"""
    
    # Software configuration - CUSTOMIZE THIS
    config = SoftwareVersionConfig(
        name="example-software",
        homepage_url="https://example.com",
        version_patterns=[
            r'Version:?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
            r'v\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
        ],
        download_url_template="https://example.com/download/v$version/software.exe",
        description="Example software package",
        license="MIT"
    )
    
    # Bucket file path - CUSTOMIZE THIS
    bucket_file = Path(__file__).parent.parent / "bucket" / "example-software.json"
    
    # Update the manifest
    success = update_manifest("example-software", config, str(bucket_file))
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()