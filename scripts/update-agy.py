#!/usr/bin/env python3
"""
Antigravity CLI (agy) Update Script
Automatically checks for updates and updates the Scoop manifest.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

SOFTWARE_NAME = "agy"
MANIFEST_AMD64_URL = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/windows_amd64.json"
MANIFEST_ARM64_URL = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/windows_arm64.json"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "agy.json"


def calculate_sha256(url: str) -> str:
    """Download binary in chunks and compute sha256."""
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    hasher = hashlib.sha256()
    for chunk in resp.iter_content(chunk_size=65536):
        hasher.update(chunk)
    return hasher.hexdigest()


def update_manifest() -> bool:
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    if requests is None:
        if not structured_only:
            print("❌ requests module not installed")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "requests_not_installed"}))
        return False

    try:
        r_amd64 = requests.get(MANIFEST_AMD64_URL, timeout=15)
        r_amd64.raise_for_status()
        data_amd64 = r_amd64.json()

        r_arm64 = requests.get(MANIFEST_ARM64_URL, timeout=15)
        r_arm64.raise_for_status()
        data_arm64 = r_arm64.json()
    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to fetch upstream manifests: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": str(e)}))
        return False

    version = data_amd64.get("version")
    url_64 = data_amd64.get("url")
    url_arm = data_arm64.get("url")

    if not version or not url_64 or not url_arm:
        if not structured_only:
            print("❌ Invalid manifest data from updater service")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "invalid_manifest"}))
        return False

    try:
        with open(BUCKET_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"❌ Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in manifest: {e}")
        return False

    current_version = manifest.get("version", "")
    if current_version == version:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    if not structured_only:
        print(f"📥 New version found: {current_version} -> {version}. Calculating SHA256 hashes...")

    try:
        hash_64 = calculate_sha256(url_64)
        hash_arm = calculate_sha256(url_arm)
    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to download and hash binary: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": f"hash_failed: {e}"}))
        return False

    url_64_shimmed = f"{url_64}#/agy.exe"
    url_arm_shimmed = f"{url_arm}#/agy.exe"

    manifest["version"] = version
    manifest["architecture"] = {
        "64bit": {
            "url": url_64_shimmed,
            "hash": f"sha256:{hash_64}"
        },
        "arm64": {
            "url": url_arm_shimmed,
            "hash": f"sha256:{hash_arm}"
        }
    }
    manifest["url"] = url_64_shimmed
    manifest["hash"] = f"sha256:{hash_64}"

    try:
        with open(BUCKET_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")

        if not structured_only:
            print(f"✅ Updated {SOFTWARE_NAME}: {current_version} → {version}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True
    except Exception as e:
        if not structured_only:
            print(f"❌ Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False


def main() -> None:
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
