#!/usr/bin/env python3
"""
Manifest Manager Module
Encapsulates logic for updating Scoop manifests.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from version_detector import SoftwareVersionConfig, get_version_info

class ManifestUpdater:
    """
    Handles the update process for a Scoop manifest.
    """
    def __init__(self, 
                 config: SoftwareVersionConfig, 
                 bucket_dir: Path, 
                 manifest_filename: Optional[str] = None):
        self.config = config
        self.bucket_dir = bucket_dir
        self.manifest_filename = manifest_filename or f"{config.name}.json"
        self.manifest_path = self.bucket_dir / self.manifest_filename
        self.structured_only = os.environ.get('STRUCTURED_ONLY') == '1'

    def log(self, message: str):
        if not self.structured_only:
            print(message)

    def update(self) -> bool:
        """
        Execute the update process.
        Returns True if successful (updated or already up-to-date), False on error.
        """
        self.log(f"🔄 Updating {self.config.name}...")

        # Get version information
        version_info = get_version_info(self.config)
        if not version_info:
            if not self.structured_only:
                print(f"❌ Failed to get version info for {self.config.name}")
            print(json.dumps({"updated": False, "name": self.config.name, "error": "version_info_unavailable"}))
            return False

        version = version_info['version']
        download_url = version_info['download_url']
        hash_value = version_info['hash']

        # Load existing manifest
        if not self.manifest_path.exists():
            print(f"❌ Manifest file not found: {self.manifest_path}")
            return False

        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in manifest: {e}")
            return False

        # Check if update is needed
        current_version = manifest.get('version', '')
        if current_version == version:
            self.log(f"✅ {self.config.name} is already up to date (v{version})")
            print(json.dumps({"updated": False, "name": self.config.name, "version": version}))
            return True

        # Update manifest
        if not self._update_manifest_content(manifest, version, download_url, hash_value):
            return False

        # Save updated manifest
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False) # Scoop uses 4 spaces usually, but existing scripts used 2? Let's check.
                # Checking existing files... 
                # scripts/update-ripgrep-all.py uses indent=2.
            
            self.log(f"✅ Updated {self.config.name}: {current_version} → {version}")
            print(json.dumps({"updated": True, "name": self.config.name, "version": version}))
            return True

        except Exception as e:
            self.log(f"❌ Failed to save manifest: {e}")
            print(json.dumps({"updated": False, "name": self.config.name, "version": version, "error": "save_failed"}))
            return False

    def _update_manifest_content(self, manifest: Dict[str, Any], version: str, url: str, hash_val: str) -> bool:
        """Updates the manifest dictionary in-place."""
        try:
            manifest['version'] = version
            
            # Prefer architecture-specific update when manifest uses architecture blocks
            arch = manifest.get('architecture')
            if isinstance(arch, dict) and arch:
                # Choose preferred architecture key
                # Logic copied from existing scripts
                arch_key = '64bit' if '64bit' in arch else ('arm64' if 'arm64' in arch else ('32bit' if '32bit' in arch else next(iter(arch.keys()))))
                
                if isinstance(arch.get(arch_key), dict):
                    arch_entry = arch[arch_key]
                    arch_entry['url'] = url
                    arch_entry['hash'] = f"sha256:{hash_val}"
                    manifest['architecture'][arch_key] = arch_entry
                else:
                    # Fallback to top-level if architecture entry is not a dict (unlikely but safe)
                    manifest['url'] = url
                    manifest['hash'] = f"sha256:{hash_val}"
            else:
                manifest['url'] = url
                manifest['hash'] = f"sha256:{hash_val}"
            
            return True
        except Exception as e:
            self.log(f"❌ Error updating manifest content: {e}")
            return False
