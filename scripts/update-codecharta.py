#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

SOFTWARE_NAME = "codecharta"
HOMEPAGE_URL = "https://api.github.com/repos/MaibornWolff/codecharta/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/MaibornWolff/codecharta/releases/download/vis-$version/codecharta-visualization-win32-x64.zip"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "codecharta.json"

def update_manifest():
    structured_only = os.environ.get('STRUCTURED_ONLY') == '1'
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r'tag_name"\s*:\s*"vis-([0-9]+\.[0-9]+(?:\.[0-9]+)?)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="CodeCharta Visualization",
        license="BSD-3-Clause",
    )

    version_info = get_version_info(config)
    if not version_info:
        if not structured_only:
            print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}))
        return False

    version = version_info['version']
    download_url = version_info['download_url']
    hash_value = version_info['hash']

    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        if not structured_only:
            print(f"❌ Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as e:
        if not structured_only:
            print(f"❌ Invalid JSON in manifest: {e}")
        return False

    current_version = manifest.get('version', '')
    if current_version == version:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = hash_value

    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        if not structured_only:
            print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True
    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False

def main():
    success = update_manifest()
    if not success:
        sys.exit(1)

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

