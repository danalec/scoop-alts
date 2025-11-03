#!/usr/bin/env python3
"""
Scoop Manifest Generator
Automatically generates Scoop JSON manifests from software configuration.
"""

import json
import re
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
import hashlib
from dataclasses import dataclass, asdict
from version_detector import VersionDetector, SoftwareConfig, SoftwareVersionConfig, get_version_info

# SoftwareConfig is now imported from version_detector.py

class ManifestGenerator:
    """Generate Scoop manifests from software configurations"""
    
    def __init__(self, bucket_dir: Path = None):
        self.bucket_dir = bucket_dir or Path(__file__).parent.parent / "bucket"
        self.detector = VersionDetector()  # Use shared detector with session

    def fetch_version_info_legacy(self, config: SoftwareConfig) -> tuple[str, str]:
        """Legacy method for backward compatibility"""
        try:
            response = self.detector.session.get(config.homepage, timeout=30)
            response.raise_for_status()
            content = response.text
            
            # Extract version using regex
            version_match = re.search(config.version_regex, content, re.IGNORECASE)
            if not version_match:
                raise ValueError(f"Version not found with regex: {config.version_regex}")
            
            version = version_match.group(1)
            
            # Generate download URL
            if config.download_url_template:
                download_url = config.download_url_template.replace("$version", version)
            else:
                # Try to find download link in content
                url_match = re.search(config.url_pattern, content, re.IGNORECASE)
                if url_match:
                    download_url = url_match.group(0)
                    if not download_url.startswith('http'):
                        download_url = urljoin(config.homepage, download_url)
                else:
                    raise ValueError("Download URL not found")
            
            return version, download_url
            
        except Exception as e:
            raise Exception(f"Failed to fetch version info: {e}")

    def fetch_version_info(self, config: SoftwareConfig) -> tuple[str, str]:
        """Fetch latest version and download URL using shared version detector"""
        try:
            # Convert SoftwareConfig to SoftwareVersionConfig
            version_patterns = [config.version_regex] if config.version_regex else []
            
            version_config = SoftwareVersionConfig(
                name=config.name,
                homepage=config.homepage,
                version_patterns=version_patterns,
                download_url_template=config.download_url_template,
                description=config.description,
                license=config.license,
                bin_name=config.bin_name,
                shortcuts=config.shortcuts or []
            )
            
            # Use shared version detection
            version_info = get_version_info(version_config)
            if not version_info:
                # Fall back to legacy method if shared method fails
                print("⚠️  Shared version detection failed, falling back to legacy method")
                return self.fetch_version_info_legacy(config)
            
            return version_info['version'], version_info['download_url']
            
        except Exception as e:
            print(f"⚠️  Shared version detection error: {e}, falling back to legacy method")
            return self.fetch_version_info_legacy(config)

    # validate_url and calculate_hash methods are now available in VersionDetector

    def generate_manifest(self, config: SoftwareConfig) -> Dict[str, Any]:
        """Generate complete Scoop manifest"""
        print(f"🔍 Generating manifest for {config.name}...")
        
        # Try to use shared version detection first
        try:
            version_patterns = [config.version_regex] if config.version_regex else []
            version_config = SoftwareVersionConfig(
                name=config.name,
                homepage=config.homepage,
                version_patterns=version_patterns,
                download_url_template=config.download_url_template,
                description=config.description,
                license=config.license,
                bin_name=config.bin_name,
                shortcuts=config.shortcuts or []
            )
            
            version_info = get_version_info(version_config)
            if version_info:
                version = version_info['version']
                download_url = version_info['download_url']
                file_hash = version_info['hash']
            else:
                raise Exception("Shared version detection failed")
                
        except Exception as e:
            print(f"⚠️  Using legacy method: {e}")
            # Fall back to legacy method
            version, download_url = self.fetch_version_info(config)
            print(f"✅ Found version: {version}")
            print(f"📦 Download URL: {download_url}")
            
            # Calculate hash using shared method
            print("🔍 Calculating hash...")
            file_hash = self.detector.calculate_hash(download_url)
            print(f"✅ Hash: {file_hash}")
        
        # Build manifest
        manifest = {
            "version": version,
            "description": config.description,
            "homepage": config.homepage,
            "license": config.license,
            "url": download_url,
            "hash": f"sha256:{file_hash}"
        }
        
        # Add binary name
        if config.bin_name:
            bin_name = config.bin_name.replace("$version", version)
            manifest["bin"] = bin_name
        else:
            # Extract from URL
            filename = urlparse(download_url).path.split('/')[-1]
            manifest["bin"] = filename
        
        # Add shortcuts
        if config.shortcuts:
            shortcuts = []
            for shortcut in config.shortcuts:
                processed_shortcut = [s.replace("$version", version) for s in shortcut]
                shortcuts.append(processed_shortcut)
            manifest["shortcuts"] = shortcuts
        
        # Add installer type
        if config.installer_type:
            manifest["installer"] = {"script": config.installer_type}
        
        # Add extract directory
        if config.extract_dir:
            manifest["extract_dir"] = config.extract_dir.replace("$version", version)
        
        # Add pre/post install scripts
        if config.pre_install:
            manifest["pre_install"] = [cmd.replace("$version", version) for cmd in config.pre_install]
        
        if config.post_install:
            manifest["post_install"] = [cmd.replace("$version", version) for cmd in config.post_install]
        # Add uninstaller script if provided
        if getattr(config, "uninstaller_script", None):
            manifest["uninstaller"] = {
                "script": [cmd.replace("$version", version) for cmd in config.uninstaller_script]
            }
        
        # Add persist (string or list)
        if getattr(config, "persist", None):
            if isinstance(config.persist, list):
                manifest["persist"] = [p.replace("$version", version) if isinstance(p, str) else p for p in config.persist]
            elif isinstance(config.persist, str):
                manifest["persist"] = config.persist.replace("$version", version)
            else:
                manifest["persist"] = config.persist
        
        # Add architecture-specific configs
        if config.architecture:
            manifest["architecture"] = config.architecture
        
        # Add checkver and autoupdate
        manifest["checkver"] = {
            "url": config.homepage,
            "regex": config.version_regex.replace("([\\d\\.]+)", "([\\d\\.]+)")
        }
        
        if config.download_url_template:
            manifest["autoupdate"] = {
                "url": config.download_url_template
            }
        
        return manifest

    def save_manifest(self, config: SoftwareConfig, manifest: Dict[str, Any]) -> Path:
        """Save manifest to JSON file"""
        filename = f"{config.name}.json"
        filepath = self.bucket_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
        
        print(f"💾 Saved manifest: {filepath}")
        return filepath

def load_software_configs(config_file: Path) -> List[SoftwareConfig]:
    """Load software configurations from JSON file"""
    with open(config_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    configs = []
    for item in data.get('software', []):
        config = SoftwareConfig(**item)
        configs.append(config)
    
    return configs

def main():
    """Main function"""
    generator = ManifestGenerator()
    
    # Example configuration for demonstration
    example_configs = [
        SoftwareConfig(
            name="example-app",
            description="Example Application - A sample app for demonstration",
            homepage="https://example.com/app",
            license="MIT",
            version_regex=r"Version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
            download_url_template="https://example.com/downloads/app-$version.exe",
            bin_name="app-$version.exe",
            shortcuts=[["app-$version.exe", "Example App"]]
        )
    ]
    
    # Check if config file exists
    config_file = Path(__file__).parent / "software-configs.json"
    if config_file.exists():
        print(f"📋 Loading configurations from {config_file}")
        configs = load_software_configs(config_file)
    else:
        print("⚠️  No config file found, using example configuration")
        configs = example_configs
    
    # Generate manifests
    for config in configs:
        try:
            manifest = generator.generate_manifest(config)
            generator.save_manifest(config, manifest)
            print(f"✅ Successfully generated manifest for {config.name}")
        except Exception as e:
            print(f"❌ Failed to generate manifest for {config.name}: {e}")
        print("-" * 50)

if __name__ == "__main__":
    main()
