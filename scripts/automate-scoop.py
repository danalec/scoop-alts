#!/usr/bin/env python3
"""
Scoop Automation Suite
Complete automation for Scoop manifest and update script generation.
"""

import argparse
import sys
from pathlib import Path
import subprocess
import json
import importlib.util
import re
import requests
import tempfile
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from version_detector import SoftwareConfig

# Add current directory to path for imports
scripts_dir = Path(__file__).parent
sys.path.append(str(scripts_dir))

try:
    # Load manifest_generator module
    manifest_spec = importlib.util.spec_from_file_location(
        "manifest_generator",
        scripts_dir / "manifest-generator.py"
    )
    manifest_module = importlib.util.module_from_spec(manifest_spec)
    manifest_spec.loader.exec_module(manifest_module)
    ManifestGenerator = manifest_module.ManifestGenerator
    load_software_configs = manifest_module.load_software_configs

    # Load update_script_generator module
    update_spec = importlib.util.spec_from_file_location(
        "update_script_generator",
        scripts_dir / "update-script-generator.py"
    )
    update_module = importlib.util.module_from_spec(update_spec)
    update_spec.loader.exec_module(update_module)
    UpdateScriptGenerator = update_module.UpdateScriptGenerator

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure all required modules are in the same directory")
    sys.exit(1)


# SoftwareConfig and VersionDetector are now imported from version_detector.py


class ConfigWizard:
    """Interactive configuration wizard for software packages."""

    def __init__(self, keep_json: bool = False):
        self.config_file = Path(__file__).parent / "software-configs.json"
        self.keep_json = keep_json

    def run(self) -> None:
        """Run the interactive configuration wizard."""
        print("🧙‍♂️ Welcome to the Scoop Automation Configuration Wizard!")
        print("=" * 60)
        print("This wizard will help you create a software configuration")
        print("by asking simple questions. No JSON editing required!\n")

        try:
            config = self._collect_basic_info()
            config = self._collect_advanced_options(config)

            # Test the configuration
            if self._test_configuration(config):
                self._save_configuration(config)
                self._generate_files(config)

                print(f"\n🎉 Success! Configuration for '{config.name}' has been created!")
                print(f"📁 Generated files:")
                print(f"   ✅ Manifest: bucket/{config.name}.json")
                print(f"   ✅ Update script: scripts/update-{config.name}.py")

                if not self.keep_json:
                    self._cleanup_json()
                    print(f"   🧹 Cleaned up: {self.config_file.name} (no longer needed)")
                else:
                    print(f"   📄 Kept: {self.config_file.name} (as requested)")
            else:
                print("\n❌ Configuration test failed. Please check your inputs and try again.")

        except KeyboardInterrupt:
            print("\n\n👋 Wizard cancelled. No changes were made.")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            sys.exit(1)

    def _collect_basic_info(self) -> SoftwareConfig:
        """Collect basic software information."""
        print("📝 Basic Information")
        print("-" * 20)

        # Package name
        while True:
            name = input("📦 Package name (e.g., 'my-awesome-app'): ").strip().lower()
            if re.match(r'^[a-z0-9-]+$', name):
                break
            print("❌ Name must contain only lowercase letters, numbers, and hyphens")

        # Description
        description = input(f"📄 Description (e.g., '{name.title()} - Brief description'): ").strip()
        if not description:
            description = f"{name.title()} - Software package"

        # Homepage
        while True:
            homepage = input("🌐 Homepage URL (where to check for versions): ").strip()
            if homepage.startswith(('http://', 'https://')):
                break
            print("❌ Please enter a valid URL starting with http:// or https://")

        # License
        print("\n📋 Common licenses: MIT, Apache-2.0, GPL-3.0, BSD-3-Clause, Freeware, Commercial")
        license_type = input("⚖️  License: ").strip()
        if not license_type:
            license_type = "Unknown"

        return SoftwareConfig(
            name=name,
            description=description,
            homepage=homepage,
            license=license_type,
            version_regex="",  # Will be filled later
            download_url_template=""  # Will be filled later
        )

    def _collect_advanced_options(self, config: SoftwareConfig) -> SoftwareConfig:
        """Collect advanced configuration options."""
        print(f"\n🔍 Version Detection for '{config.name}'")
        print("-" * 40)

        # Test homepage and suggest patterns
        print(f"🌐 Checking {config.homepage}...")
        try:
            response = requests.get(config.homepage, timeout=10)
            content = response.text[:2000]  # First 2KB for analysis

            # Suggest common patterns
            patterns = self._suggest_version_patterns(content)
            if patterns:
                print("🎯 Found potential version patterns:")
                for i, (pattern, example) in enumerate(patterns, 1):
                    print(f"   {i}. {pattern} (found: {example})")

                choice = input(f"\nSelect pattern (1-{len(patterns)}) or enter custom: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(patterns):
                    config.version_regex = patterns[int(choice) - 1][0]
                else:
                    config.version_regex = input("🔍 Custom version regex pattern: ").strip()
            else:
                print("❓ No obvious version patterns found.")
                config.version_regex = input("🔍 Version regex pattern: ").strip()

        except Exception as e:
            print(f"⚠️  Could not fetch homepage: {e}")
            config.version_regex = input("🔍 Version regex pattern: ").strip()

        # Download URL template
        print(f"\n📥 Download Configuration")
        print("-" * 25)
        print("💡 Use $version as placeholder (e.g., 'https://example.com/app-$version.exe')")
        config.download_url_template = input("📥 Download URL template: ").strip()

        # Binary name
        print(f"\n⚙️  Installation Options")
        print("-" * 22)
        bin_name = input("🔧 Main executable name (optional, e.g., 'app.exe'): ").strip()
        if bin_name:
            config.bin_name = bin_name

        # Shortcuts
        if input("🖥️  Create desktop shortcut? (y/N): ").strip().lower() == 'y':
            exe_name = config.bin_name or f"{config.name}.exe"
            shortcut_name = input(f"📌 Shortcut name (default: '{config.name.title()}'): ").strip()
            if not shortcut_name:
                shortcut_name = config.name.title()
            config.shortcuts = [[exe_name, shortcut_name]]

        # Installer type
        installer_types = ["inno", "nsis", "msi", "zip", "7zip"]
        print(f"\n📦 Installer type (optional): {', '.join(installer_types)}")
        installer_type = input("📦 Installer type: ").strip().lower()
        if installer_type in installer_types:
            config.installer_type = installer_type

        return config

    def _suggest_version_patterns(self, content: str) -> List[tuple]:
        """Suggest version regex patterns based on content analysis."""
        patterns = []

        # Common version patterns
        test_patterns = [
            (r'Version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Version X.Y.Z'),
            (r'v([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'vX.Y.Z'),
            (r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', 'GitHub releases API'),
            (r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)/', 'Version in URL path'),
            (r'Release\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Release X.Y.Z'),
            (r'Download\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Download X.Y.Z'),
        ]

        for pattern, description in test_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                patterns.append((pattern, f"{description} → {matches[0]}"))

        return patterns[:5]  # Return top 5 suggestions

    def _test_configuration(self, config: SoftwareConfig) -> bool:
        """Test the configuration by attempting version detection."""
        print(f"\n🧪 Testing configuration for '{config.name}'...")

        try:
            # Test web-based version detection first
            response = requests.get(config.homepage, timeout=10)
            matches = re.findall(config.version_regex, response.text)

            version = None
            if matches:
                version = matches[0]
                print(f"✅ Web-based version detection successful: {version}")
            else:
                print("❌ No version found with the provided regex pattern")
                print("🔄 Trying executable metadata detection as fallback...")

                # Fallback: Try executable metadata detection
                detector = VersionDetector()

                # Try with a sample version (1.0.0) to test the URL pattern
                sample_url = config.download_url_template.replace('$version', '1.0.0')

                if sample_url.endswith('.msi'):
                    version = detector.get_msi_version(sample_url)
                elif sample_url.endswith(('.exe', '.zip', '.7z')):
                    # For archives, we can't extract metadata, but we can test URL accessibility
                    if sample_url.endswith('.exe'):
                        version = detector.get_version_from_executable(sample_url)
                    else:
                        print("⚠️  Archive files don't contain version metadata")
                        version = None

                if version:
                    print(f"✅ Executable metadata detection successful: {version}")
                else:
                    print("❌ Both web and executable metadata detection failed")
                    return input("Continue anyway? (y/N): ").strip().lower() == 'y'

            if version:
                # Test download URL with detected version
                download_url = config.download_url_template.replace('$version', version)
                print(f"🔗 Testing download URL: {download_url}")

                head_response = requests.head(download_url, timeout=10, allow_redirects=True)
                if head_response.status_code == 200:
                    print("✅ Download URL is accessible")
                    return True
                else:
                    print(f"⚠️  Download URL returned status {head_response.status_code}")
                    return input("Continue anyway? (y/N): ").strip().lower() == 'y'

            return False

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return input("Continue anyway? (y/N): ").strip().lower() == 'y'

    def _save_configuration(self, config: SoftwareConfig) -> None:
        """Save the configuration to the JSON file."""
        # Load existing configurations
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}

        if 'software' not in data:
            data['software'] = []

        # Convert config to dict and clean up None values
        config_dict = asdict(config)
        config_dict = {k: v for k, v in config_dict.items() if v is not None}

        # Check if software already exists
        existing_index = None
        for i, software in enumerate(data['software']):
            if software.get('name') == config.name:
                existing_index = i
                break

        if existing_index is not None:
            if input(f"⚠️  '{config.name}' already exists. Overwrite? (y/N): ").strip().lower() == 'y':
                data['software'][existing_index] = config_dict
            else:
                print("❌ Configuration not saved.")
                return
        else:
            data['software'].append(config_dict)

        # Save to file
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"✅ Configuration saved to {self.config_file}")

    def _generate_files(self, config: SoftwareConfig) -> None:
        """Generate manifest and update script files using the integrated automation."""
        try:
            # Use the integrated automation instead of subprocess
            automation = ScoopAutomation()
            manifests = automation.generate_manifests([config.name])
            scripts = automation.generate_update_scripts([config.name])
            automation.update_orchestrator()

            if manifests and scripts:
                print("✅ Files generated successfully")
            else:
                print("⚠️  Some files may not have been generated")

        except Exception as e:
            print(f"⚠️  Could not auto-generate files: {e}")
            print(f"💡 Run manually: python automate-scoop.py generate-all --software {config.name}")

    def _cleanup_json(self) -> None:
        """Remove the JSON configuration file to keep scripts directory clean."""
        try:
            if self.config_file.exists():
                self.config_file.unlink()
                print(f"🧹 Removed {self.config_file.name} (temporary configuration file)")
        except Exception as e:
            print(f"⚠️  Could not remove JSON file: {e}")
            print(f"💡 You can manually delete: {self.config_file}")

class ScoopAutomation:
    """Main automation class for Scoop manifest and script generation"""

    def __init__(self, bucket_dir: Path = None, scripts_dir: Path = None):
        self.bucket_dir = bucket_dir or Path(__file__).parent.parent / "bucket"
        self.scripts_dir = scripts_dir or Path(__file__).parent
        self.config_file = self.scripts_dir / "software-configs.json"

        self.manifest_generator = ManifestGenerator(self.bucket_dir)
        self.script_generator = UpdateScriptGenerator(self.bucket_dir, self.scripts_dir)

    def generate_manifests(self, software_names: list = None) -> list:
        """Generate manifests for specified software or all configured software"""
        if not self.config_file.exists():
            print(f"❌ Configuration file not found: {self.config_file}")
            print("Please create software-configs.json with your software definitions")
            return []

        print(f"📋 Loading configurations from {self.config_file}")
        configs = load_software_configs(self.config_file)

        if software_names:
            # Filter configs to only include specified software
            configs = [c for c in configs if c.name in software_names]
            if not configs:
                print(f"❌ No configurations found for: {', '.join(software_names)}")
                return []

        generated_manifests = []

        for config in configs:
            try:
                print(f"\\n🚀 Generating manifest for {config.name}...")
                manifest = self.manifest_generator.generate_manifest(config)
                manifest_path = self.manifest_generator.save_manifest(config, manifest)
                generated_manifests.append(manifest_path)
                print(f"✅ Successfully generated manifest for {config.name}")
            except Exception as e:
                print(f"❌ Failed to generate manifest for {config.name}: {e}")
            print("-" * 50)

        return generated_manifests

    def generate_update_scripts(self, manifest_names: list = None) -> list:
        """Generate update scripts for specified manifests or all manifests"""
        if manifest_names:
            # Generate scripts for specific manifests
            generated_scripts = []
            for name in manifest_names:
                manifest_path = self.bucket_dir / f"{name}.json"
                if not manifest_path.exists():
                    print(f"❌ Manifest not found: {manifest_path}")
                    continue

                try:
                    script_path = self.script_generator.generate_script_for_manifest(manifest_path)
                    generated_scripts.append(script_path)
                except Exception as e:
                    print(f"❌ Failed to generate script for {name}: {e}")

            return generated_scripts
        else:
            # Generate scripts for all manifests
            print("🚀 Generating update scripts for all manifests...")
            return self.script_generator.generate_all_scripts()

    def update_orchestrator(self) -> bool:
        """Check that the orchestrator can auto-detect update scripts"""
        try:
            # Get all update scripts
            update_scripts = list(self.scripts_dir.glob("update-*.py"))
            script_names = [script.stem for script in update_scripts if script.name not in ["update-all.py", "update-script-generator.py"]]

            # Check orchestrator exists
            orchestrator_path = self.scripts_dir / "update-all.py"
            if not orchestrator_path.exists():
                print(f"❌ Orchestrator not found: {orchestrator_path}")
                return False

            # Since update-all.py now auto-detects scripts, just verify it has the discover function
            with open(orchestrator_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if 'discover_update_scripts' in content:
                print(f"✅ Orchestrator ready - will auto-detect {len(script_names)} scripts")
                print(f"📋 Available scripts: {', '.join(sorted(script_names))}")
                return True
            else:
                print("⚠️  Orchestrator missing auto-detection functionality")
                return False

        except Exception as e:
            print(f"❌ Failed to check orchestrator: {e}")
            return False

    def validate_manifests(self, manifest_paths: list = None) -> bool:
        """Validate generated manifests"""
        if manifest_paths is None:
            manifest_paths = list(self.bucket_dir.glob("*.json"))

        all_valid = True

        schema = None
        try:
            from jsonschema import Draft202012Validator  # type: ignore
            schema_path = self.scripts_dir / "manifest_schema.json"
            if schema_path.exists():
                import json as _json
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema = _json.load(f)
                validator = Draft202012Validator(schema)
            else:
                validator = None
        except Exception:
            validator = None

        for manifest_path in manifest_paths:
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                if validator:
                    errors = list(validator.iter_errors(manifest))
                    if errors:
                        all_valid = False
                        print(f"❌ {manifest_path.name}: Schema validation failed")
                        for e in errors[:5]:
                            print(f"   - {e.message}")
                    else:
                        print(f"✅ {manifest_path.name}: Valid")
                else:
                    # Basic validation without schema: accept either top-level url/hash
                    # or architecture-specific url/hash entries
                    base_required = ['version', 'description', 'homepage']
                    base_missing = [f for f in base_required if f not in manifest]

                    has_top_level = ('url' in manifest) and ('hash' in manifest)
                    has_arch = False
                    if not has_top_level and isinstance(manifest.get('architecture'), dict):
                        arch = manifest['architecture']
                        # Consider valid if any architecture entry has both url and hash
                        for k, v in arch.items():
                            if isinstance(v, dict) and ('url' in v) and ('hash' in v):
                                has_arch = True
                                break

                    if base_missing:
                        print(f"❌ {manifest_path.name}: Missing fields: {', '.join(base_missing)}")
                        all_valid = False
                    elif not (has_top_level or has_arch):
                        print(f"❌ {manifest_path.name}: Missing fields: url, hash (top-level or per-architecture)")
                        all_valid = False
                    else:
                        print(f"✅ {manifest_path.name}: Valid")

            except json.JSONDecodeError as e:
                print(f"❌ {manifest_path.name}: Invalid JSON: {e}")
                all_valid = False
            except Exception as e:
                print(f"❌ {manifest_path.name}: Validation error: {e}")
                all_valid = False

        return all_valid

    def auto_discover_software(self, sources: List[str] = None) -> List[Dict[str, str]]:
        """Auto-discover popular software from various sources"""
        if sources is None:
            sources = ["github-trending", "chocolatey-popular"]

        discovered = []

        for source in sources:
            try:
                if source == "github-trending":
                    discovered.extend(self._discover_github_trending())
                elif source == "chocolatey-popular":
                    discovered.extend(self._discover_chocolatey_popular())

            except Exception as e:
                print(f"⚠️  Failed to discover from {source}: {e}")

        return discovered[:10]  # Limit to top 10

    def _discover_github_trending(self) -> List[Dict[str, str]]:
        """Discover trending GitHub repositories with releases"""
        try:
            # Search for trending repositories with recent releases
            url = "https://api.github.com/search/repositories"
            params = {
                "q": "stars:>1000 pushed:>2024-01-01 language:C language:C++ language:Go language:Rust",
                "sort": "stars",
                "order": "desc",
                "per_page": 20
            }

            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return []

            repos = response.json().get("items", [])
            discovered = []

            for repo in repos:
                # Check if repo has releases
                releases_url = f"https://api.github.com/repos/{repo['full_name']}/releases"
                releases_response = requests.get(releases_url, timeout=5)

                if releases_response.status_code == 200:
                    releases = releases_response.json()
                    if releases:  # Has releases
                        discovered.append({
                            "name": repo["name"].lower().replace("_", "-"),
                            "description": repo["description"] or f"{repo['name']} - GitHub project",
                            "homepage": f"https://api.github.com/repos/{repo['full_name']}/releases",
                            "license": repo.get("license", {}).get("spdx_id", "Unknown"),
                            "suggested_regex": r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
                            "suggested_url_template": f"https://github.com/{repo['full_name']}/releases/download/v$version/{repo['name']}-$version.exe"
                        })

            return discovered

        except Exception as e:
            print(f"GitHub discovery error: {e}")
            return []

    def _discover_chocolatey_popular(self) -> List[Dict[str, str]]:
        """Discover popular Chocolatey packages that might have direct downloads"""
        # This would require Chocolatey API access or web scraping
        # For now, return a curated list of commonly requested software
        popular_software = [
            {
                "name": "notepad-plus-plus",
                "description": "Free source code editor",
                "homepage": "https://api.github.com/repos/notepad-plus-plus/notepad-plus-plus/releases",
                "license": "GPL-3.0",
                "suggested_regex": r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
                "suggested_url_template": "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v$version/npp.$version.Installer.x64.exe"
            },
            {
                "name": "vlc",
                "description": "VLC media player",
                "homepage": "https://www.videolan.org/vlc/download-windows.html",
                "license": "GPL-2.0",
                "suggested_regex": r'VLC\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
                "suggested_url_template": "https://download.videolan.org/pub/videolan/vlc/$version/win64/vlc-$version-win64.exe"
            }
        ]

        return popular_software

    def suggest_version_patterns(self, url: str) -> List[tuple]:
        """Enhanced version pattern detection with more sophisticated patterns"""
        try:
            response = requests.get(url, timeout=10)
            content = response.text

            patterns = []

            # Enhanced pattern detection
            test_patterns = [
                # GitHub API patterns
                (r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[a-zA-Z0-9]+)?)"', 'GitHub API with pre-release'),
                (r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', 'GitHub API stable'),

                # Version in text patterns
                (r'Version\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Version prefix'),
                (r'Release\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Release prefix'),
                (r'Download\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'Download prefix'),

                # URL path patterns
                (r'/v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)/[^/]*\.(?:exe|msi|zip|7z)', 'Version in download URL'),
                (r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)\.(?:exe|msi|zip|7z)', 'Version in filename'),

                # HTML patterns
                (r'<h[1-6][^>]*>.*?v?([0-9]+\.[0-9]+(?:\.[0-9]+)?).*?</h[1-6]>', 'Version in heading'),
                (r'data-version="v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"', 'Version in data attribute'),

                # Semantic versioning with build metadata
                (r'v?([0-9]+\.[0-9]+\.[0-9]+(?:\+[a-zA-Z0-9.-]+)?)', 'Semantic versioning with build'),
                (r'v?([0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?)', 'Semantic versioning with pre-release'),
            ]

            for pattern, description in test_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    # Get the most recent/highest version
                    version = max(matches, key=lambda v: [int(x) for x in v.split('.') if x.isdigit()])
                    patterns.append((pattern, f"{description} → {version}"))

            return patterns[:8]  # Return top 8 suggestions

        except Exception as e:
            print(f"Pattern suggestion error: {e}")
            return []

    def run_tests(self) -> bool:
        """Run comprehensive tests on the automation system"""
        print("🧪 Running Automation Tests...")
        print("=" * 40)

        all_passed = True

        # Test 1: Configuration file exists and is valid
        config_file = self.scripts_dir / "software-configs.json"
        if config_file.exists():
            try:
                configs = load_software_configs(config_file)
                print(f"✅ Configuration file valid ({len(configs)} software entries)")
            except Exception as e:
                print(f"❌ Configuration file invalid: {e}")
                all_passed = False
        else:
            print("⚠️  No configuration file found (run wizard to create one)")

        # Test 2: Validate existing manifests
        manifests = list(self.bucket_dir.glob("*.json"))
        if manifests:
            print(f"\n📦 Validating {len(manifests)} manifests...")
            if not self.validate_manifests(manifests):
                all_passed = False
        else:
            print("⚠️  No manifests found in bucket directory")

        # Test 3: Check update scripts
        update_scripts = list(self.scripts_dir.glob("update-*.py"))
        if update_scripts:
            print(f"\n🔄 Found {len(update_scripts)} update scripts")
        else:
            print("⚠️  No update scripts found")

        print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed'}")
        return all_passed

    def detect_version_enhanced(self, config: SoftwareConfig) -> Optional[str]:
        """Enhanced version detection with executable metadata fallback"""
        try:
            # Primary: Web-based regex detection
            response = requests.get(config.homepage, timeout=10)
            response.raise_for_status()

            match = re.search(config.version_regex, response.text, re.IGNORECASE)
            if match:
                version = match.group(1)
                print(f"✅ Version detected via web regex: {version}")
                return version

            print("⚠️  Web regex detection failed, trying executable metadata...")

           # Fallback: Executable metadata detection
            detector = VersionDetector()

            # Try to construct download URL with a placeholder version
            test_version = "1.0.0"  # Placeholder for URL construction
            download_url = config.download_url_template.replace("${version}", test_version)

            # Check if it's an MSI file
            if download_url.lower().endswith('.msi'):
                version = detector.get_msi_version(download_url)
                if version:
                    print(f"✅ Version detected from MSI metadata: {version}")
                    return version

            # Check if it's an executable
            elif download_url.lower().endswith('.exe'):
                version = detector.get_version_from_executable(download_url)
                if version:
                    print(f"✅ Version detected from executable metadata: {version}")
                    return version

            else:
                print("ℹ️  Archive files don't contain version metadata")

            print("❌ All version detection methods failed")
            return None

        except Exception as e:
            print(f"❌ Enhanced version detection error: {e}")
            return None

    def wizard(self, keep_json: bool = False) -> None:
        """Launch the configuration wizard"""
        wizard = ConfigWizard(keep_json)
        wizard.run()

def main():
    """Main function with CLI interface"""
    parser = argparse.ArgumentParser(description="Scoop Automation Suite")
    parser.add_argument("command", choices=[
        "generate-manifests", "generate-scripts", "generate-all",
        "validate", "test", "update-orchestrator", "wizard",
        "auto-discover", "suggest-patterns", "test-version", "audit-providers"
    ], help="Command to execute")
    parser.add_argument("--software", nargs="+", help="Specific software names to process")
    parser.add_argument("--bucket-dir", type=Path, help="Bucket directory path")
    parser.add_argument("--scripts-dir", type=Path, help="Scripts directory path")
    parser.add_argument("--keep-json", action="store_true", help="Keep the JSON configuration file after generation (wizard only)")
    parser.add_argument("--sources", nargs="+", choices=["github", "chocolatey"],
                       help="Sources for auto-discovery (auto-discover command)")
    parser.add_argument("--url", type=str, help="URL to analyze for version patterns (suggest-patterns command)")
    parser.add_argument("--write-map", action="store_true", help="Write inferred provider map to scripts/providers.json (audit-providers)")

    args = parser.parse_args()

    # Initialize automation
    automation = ScoopAutomation(args.bucket_dir, args.scripts_dir)

    if args.command == "generate-manifests":
        print("🚀 Generating manifests...")
        manifests = automation.generate_manifests(args.software)
        print(f"\\n✅ Generated {len(manifests)} manifests")

    elif args.command == "generate-scripts":
        print("🚀 Generating update scripts...")
        scripts = automation.generate_update_scripts(args.software)
        print(f"\\n✅ Generated {len(scripts)} update scripts")

    elif args.command == "generate-all":
        print("🚀 Generating manifests and update scripts...")
        manifests = automation.generate_manifests(args.software)
        scripts = automation.generate_update_scripts(args.software)
        automation.update_orchestrator()
        print(f"\\n✅ Generated {len(manifests)} manifests and {len(scripts)} scripts")

    elif args.command == "validate":
        print("🔍 Validating manifests...")
        valid = automation.validate_manifests()
        if valid:
            print("✅ All manifests are valid")
        else:
            print("❌ Some manifests have validation errors")
            sys.exit(1)

    elif args.command == "test":
        print("🧪 Testing update scripts...")
        success = automation.run_tests()
        if not success:
            sys.exit(1)

    elif args.command == "update-orchestrator":
        print("🔄 Updating orchestrator...")
        success = automation.update_orchestrator()
        if not success:
            sys.exit(1)

    elif args.command == "wizard":
        print("🧙‍♂️ Starting Configuration Wizard...")
        automation.wizard(keep_json=args.keep_json)

    elif args.command == "auto-discover":
        print("🔍 Auto-discovering software...")
        sources = args.sources or ["github", "chocolatey"]
        discovered = automation.auto_discover_software(sources)
        if discovered:
            print(f"\\n✅ Discovered {len(discovered)} software packages:")
            for software in discovered[:10]:  # Show first 10
                print(f"  • {software['name']}: {software['description']}")
            if len(discovered) > 10:
                print(f"  ... and {len(discovered) - 10} more")
        else:
            print("❌ No software discovered")

    elif args.command == "suggest-patterns":
        if not args.url:
            print("❌ --url argument is required for suggest-patterns command")
            sys.exit(1)
        print(f"🔍 Analyzing URL for version patterns: {args.url}")
        patterns = automation.suggest_version_patterns(args.url)
        if patterns:
            print(f"\\n✅ Found {len(patterns)} potential version patterns:")
            for pattern, confidence in patterns:
                print(f"  • {pattern} (confidence: {confidence:.1%})")
        else:
            print("❌ No version patterns found")

    elif args.command == "test-version":
        print("🔍 Testing enhanced version detection...")
        config_file = automation.scripts_dir / "software-configs.json"
        if not config_file.exists():
            print("❌ No software-configs.json found. Run 'wizard' command first.")
            sys.exit(1)
        
        try:
            configs = load_software_configs(config_file)
            if args.software:
                # Test specific software
                configs = [c for c in configs if c.name in args.software]
                if not configs:
                    print(f"❌ No configurations found for: {', '.join(args.software)}")
                    sys.exit(1)
            
            for config in configs:
                print(f"\\n🔍 Testing {config.name}...")
                version = automation.detect_version_enhanced(config)
                if version:
                    print(f"✅ Successfully detected version: {version}")
                else:
                    print(f"❌ Failed to detect version for {config.name}")
                    
        except Exception as e:
            print(f"❌ Error testing version detection: {e}")
            sys.exit(1)

    elif args.command == "audit-providers":
        print("🔎 Auditing provider classification for update scripts...")
        providers_path = automation.scripts_dir / "providers.json"
        try:
            existing = {}
            if providers_path.exists():
                import json as _json
                existing = _json.loads(providers_path.read_text("utf-8"))
        except Exception:
            existing = {}

        def classify(p: Path) -> str:
            name = p.name
            pkg = name.replace("update-", "").replace(".py", "")
            mapped = existing.get(name) or existing.get(pkg)
            if isinstance(mapped, str) and mapped:
                return mapped
            try:
                content = p.read_text("utf-8", errors="ignore")[:4000]
                if ("github.com" in content) or ("api.github.com" in content):
                    return "github"
                if ("learn.microsoft.com" in content) or ("go.microsoft.com" in content) or ("download.microsoft.com" in content) or ("visualstudio.microsoft.com" in content):
                    return "microsoft"
                if ("googleapis.com" in content) or ("storage.googleapis.com" in content) or ("dl.google.com" in content) or ("cloudfront.net" in content):
                    return "google"
                return "other"
            except Exception:
                return "other"

        scripts = sorted([p for p in automation.scripts_dir.glob("update-*.py") if p.name != "update-all.py"])
        inferred = {}
        counts = {"github": 0, "microsoft": 0, "google": 0, "other": 0}
        for p in scripts:
            prov = classify(p)
            inferred[p.name] = prov
            counts[prov] += 1
            print(f"  • {p.name}: {prov}")
        print(f"\nTotals → GitHub: {counts['github']} | Microsoft: {counts['microsoft']} | Google: {counts['google']} | Other: {counts['other']}")

        if args.write_map:
            try:
                import json as _json
                merged = dict(existing)
                merged.update(inferred)
                providers_path.write_text(_json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"✅ Wrote providers map: {providers_path}")
            except Exception as e:
                print(f"⚠️  Failed to write providers map: {e}")

if __name__ == "__main__":
    main()
