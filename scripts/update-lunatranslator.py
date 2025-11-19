#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

SOFTWARE_NAME = "lunatranslator"
HOMEPAGE_URL = "https://api.github.com/repos/HIllya51/LunaTranslator/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/HIllya51/LunaTranslator/releases/download/v$version/LunaTranslator_x64_win10.zip"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "lunatranslator.json"

def update_manifest():
    print(f"🔄 Updating {SOFTWARE_NAME}...")
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r'tag_name"\s*:\s*"v?([\d.]+)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Visual Novel Translator",
        license="GPL-3.0-or-later",
    )
    version_info = get_version_info(config)
    if not version_info:
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}))
        return False
    version = version_info['version']
    download_url = version_info['download_url']
    hash_value = version_info['hash']
    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception:
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "manifest_read_failed"}))
        return False
    current_version = manifest.get('version', '')
    if current_version == version:
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True
    manifest['version'] = version
    manifest['url'] = download_url
    manifest['hash'] = f"sha256:{hash_value}"
    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True
    except Exception:
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