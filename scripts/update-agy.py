#!/usr/bin/env python3
"""
Antigravity CLI (agy) Update Script
Automatically checks for updates and updates the Scoop manifest.
Supports forced execution.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from git_helpers import maybe_auto_commit  # noqa: E402

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


def update_manifest(force: bool = False) -> bool:
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    if requests is None:
        if not structured_only:
            print("❌ requests module not installed")
        print(
            json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "requests_not_installed"})
        )
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
        if not structured_only:
            print(f"❌ Manifest file not found: {BUCKET_FILE}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "manifest_not_found"}))
        return False
    except json.JSONDecodeError as e:
        if not structured_only:
            print(f"❌ Invalid JSON in manifest: {e}")
        print(
            json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "invalid_manifest_json"})
        )
        return False

    current_version = manifest.get("version", "")
    if current_version == version and not force:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    if not structured_only:
        if current_version == version:
            print(f"🔄 Force-updating {SOFTWARE_NAME} (v{version}). Calculating SHA256 hashes...")
        else:
            print(
                f"📥 New version found: {current_version} -> {version}. Calculating SHA256 hashes..."
            )

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
        "64bit": {"url": url_64_shimmed, "hash": f"sha256:{hash_64}"},
        "arm64": {"url": url_arm_shimmed, "hash": f"sha256:{hash_arm}"},
    }
    # The architecture block carries the real download metadata. Keeping a
    # top-level pair alongside it is what ManifestUpdater.apply_download_metadata
    # refuses to do: the duplicate goes stale independently, and scoop serves it
    # as the fallback for any architecture not listed above -- which is how an
    # ARM machine silently ends up running the x64 binary.
    manifest.pop("url", None)
    manifest.pop("hash", None)

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
        print(
            json.dumps(
                {
                    "updated": False,
                    "name": SOFTWARE_NAME,
                    "version": version,
                    "error": "save_failed",
                }
            )
        )
        return False


def main() -> None:
    try:
        from manifest_manager import is_forced

        force = is_forced()
    except ImportError:
        force = False

    success = update_manifest(force=force)
    if not success:
        sys.exit(1)

    maybe_auto_commit(SOFTWARE_NAME, BUCKET_FILE, sys.argv[1:])


if __name__ == "__main__":
    main()
