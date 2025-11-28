#!/usr/bin/env python3
"""
Update Script Generator
Automatically generates Python update scripts for Scoop manifests.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse
import textwrap

class UpdateScriptGenerator:
    """Generates Python update scripts for Scoop manifests"""
    
    def __init__(self, bucket_dir: Path = None, scripts_dir: Path = None):
        self.bucket_dir = bucket_dir or Path(__file__).parent.parent / "bucket"
        self.scripts_dir = scripts_dir or Path(__file__).parent
        
    def load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
        """Load manifest JSON file"""
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def extract_patterns_from_manifest(self, manifest: Dict[str, Any]) -> Dict[str, str]:
        """Extract version and URL patterns from manifest"""
        patterns = {}
        
        # Get checkver info
        checkver = manifest.get('checkver', {})
        if isinstance(checkver, dict):
            patterns['homepage_url'] = checkver.get('url', manifest.get('homepage', ''))
            patterns['version_regex'] = checkver.get('regex', r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
        else:
            patterns['homepage_url'] = manifest.get('homepage', '')
            patterns['version_regex'] = r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)'
        
        # Get autoupdate info
        autoupdate = manifest.get('autoupdate', {})
        if isinstance(autoupdate, dict):
            patterns['download_url_template'] = autoupdate.get('url', '')
        else:
            patterns['download_url_template'] = ''
        
        return patterns
    
    def generate_update_script(self, manifest_name: str, manifest: Dict[str, Any]) -> str:
        """Generate Python update script content using shared version detector"""
        patterns = self.extract_patterns_from_manifest(manifest)
        
        # Extract package name (remove .json extension)
        package_name = manifest_name.replace('.json', '').replace('-', ' ').title()
        software_name = manifest_name.replace('.json', '')
        
        # Build version patterns list
        version_patterns = [patterns['version_regex']]
        if patterns['version_regex'] != r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)':
            version_patterns.append(r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
        
        # Generate script content using shared version detector
        script_content = f'''#!/usr/bin/env python3
"""
{package_name} Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

# Configuration
SOFTWARE_NAME = "{software_name}"
HOMEPAGE_URL = "{patterns['homepage_url']}"
DOWNLOAD_URL_TEMPLATE = "{patterns['download_url_template']}"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "{manifest_name}"

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {{SOFTWARE_NAME}}...")
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns={version_patterns},
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="{manifest.get('description', package_name)}",
        license="{manifest.get('license', 'Unknown')}"
    )
    
    # Get version information using shared detector
    version_info = get_version_info(config)
    if not version_info:
        if not structured_only:
            print(f"❌ Failed to get version info for {{SOFTWARE_NAME}}")
        print(json.dumps({{"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}}))
        return False
    
    version = version_info['version']
    download_url = version_info['download_url']
    hash_value = version_info['hash']
    
    # Load existing manifest
    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"❌ Manifest file not found: {{BUCKET_FILE}}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in manifest: {{e}}")
        return False
    
    # Check if update is needed
    current_version = manifest.get('version', '')
    if current_version == version:
        if not structured_only:
            print(f"✅ {{SOFTWARE_NAME}} is already up to date (v{{version}})")
        print(json.dumps({{"updated": False, "name": SOFTWARE_NAME, "version": version}}))
        return True
    
    # Update manifest
    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = f"sha256:{{hash_value}}"
    
    # Save updated manifest
    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        if not structured_only:
            print(f"✅ Updated {{SOFTWARE_NAME}}: {{current_version}} → {{version}}")
        print(json.dumps({{"updated": True, "name": SOFTWARE_NAME, "version": version}}))
        return True
        
    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to save manifest: {{e}}")
        print(json.dumps({{"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}}))
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
    main()'''
        
        return script_content
    
    def _to_class_name(self, manifest_name: str) -> str:
        """Convert manifest name to class name"""
        # Remove .json extension and convert to PascalCase
        name = manifest_name.replace('.json', '')
        # Split on hyphens and underscores, capitalize each part
        parts = re.split(r'[-_]', name)
        return ''.join(word.capitalize() for word in parts)
    
    def generate_script_for_manifest(self, manifest_path: Path) -> Path:
        """Generate update script for a specific manifest"""
        manifest_name = manifest_path.name
        manifest = self.load_manifest(manifest_path)
        
        script_content = self.generate_update_script(manifest_name, manifest)
        
        # Generate script filename
        script_name = f"update-{manifest_name.replace('.json', '.py')}"
        script_path = self.scripts_dir / script_name
        
        # Write script file
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        print(f"✅ Generated update script: {script_path}")
        return script_path
    
    def generate_all_scripts(self) -> List[Path]:
        """Generate update scripts for all manifests in bucket"""
        generated_scripts = []
        
        for manifest_path in self.bucket_dir.glob('*.json'):
            try:
                script_path = self.generate_script_for_manifest(manifest_path)
                generated_scripts.append(script_path)
            except Exception as e:
                print(f"❌ Failed to generate script for {manifest_path.name}: {e}")
        
        return generated_scripts

def main():
    """Main function"""
    generator = UpdateScriptGenerator()
    
    print("🚀 Generating update scripts for all manifests...")
    scripts = generator.generate_all_scripts()
    
    print(f"\\n✅ Generated {len(scripts)} update scripts:")
    for script in scripts:
        print(f"   • {script.name}")

if __name__ == "__main__":
    main()
