#!/usr/bin/env python3
"""
Widevinecdm Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
from pathlib import Path
from manifest_manager import is_forced
from version_detector import VersionDetector

# Configuration
SOFTWARE_NAME = "widevinecdm"
HOMEPAGE_URL = "https://scoopinstaller.github.io/UpdateTracker/googlechrome/chrome.min.xml"
DOWNLOAD_URL_TEMPLATE = "https://dl.google.com/release2/chrome/$matcharch64_$version/$version_chrome_installer_uncompressed.exe#/chrome.7z"
VERSION_PATTERNS = [
    "(?sm)<stable32><version>(?P<version>[\\d.]+)</version>.+release2/chrome/(?P<arch32>[\\w-]+)_.+<stable64>.+release2/chrome/(?P<arch64>[\\w-]+)_.+</stable64>"
]
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "widevinecdm.json"


def update_manifest(force=False):
    """Update the Scoop manifest using the shared version detector."""
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    detector = VersionDetector()
    result = detector.fetch_latest_version(HOMEPAGE_URL, VERSION_PATTERNS)
    if not result:
        if not structured_only:
            print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        print(
            json.dumps(
                {"updated": False, "name": SOFTWARE_NAME, "error": "version_info_unavailable"}
            )
        )
        return False

    version = result.version
    match_groups = result.match_groups

    # Load existing manifest
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

    # Check if update is needed (any architecture entry pointing at another version counts)
    current_version = manifest.get("version", "")
    arch = manifest.get("architecture")
    arch_urls_current = True
    if isinstance(arch, dict) and arch:
        arch_urls_current = all(
            isinstance(entry, dict) and version in entry.get("url", "") for entry in arch.values()
        )
    if current_version == version and arch_urls_current and not force:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True
    if current_version == version and arch_urls_current and force:
        if not structured_only:
            print(f"🔄 Forcing update of {SOFTWARE_NAME} (v{version})...")

    # Update every architecture entry; drop entries upstream no longer ships
    manifest["version"] = version
    if isinstance(arch, dict) and arch:
        updated_arch = {}
        for arch_key, arch_entry in arch.items():
            arch_group = f'arch{arch_key.replace("bit", "")}'
            if not isinstance(arch_entry, dict) or arch_group not in match_groups:
                continue
            arch_url = detector.construct_download_url(
                DOWNLOAD_URL_TEMPLATE.replace("$matcharch64", f"$match{arch_group}"),
                version,
                match_groups,
            )
            arch_hash = detector.calculate_hash(arch_url)
            if not arch_hash:
                if not structured_only:
                    print(f"❌ Failed to calculate hash for {arch_key}")
                print(
                    json.dumps(
                        {
                            "updated": False,
                            "name": SOFTWARE_NAME,
                            "version": version,
                            "error": "hash_unavailable",
                        }
                    )
                )
                return False
            arch_entry["url"] = arch_url
            arch_entry["hash"] = f"sha256:{arch_hash}"
            updated_arch[arch_key] = arch_entry
        if not updated_arch:
            if not structured_only:
                print(f"❌ No architecture data available for {SOFTWARE_NAME}")
            print(
                json.dumps(
                    {
                        "updated": False,
                        "name": SOFTWARE_NAME,
                        "version": version,
                        "error": "version_info_unavailable",
                    }
                )
            )
            return False
        manifest["architecture"] = updated_arch
        # Top-level url/hash would go stale; keep this manifest architecture-only
        manifest.pop("url", None)
        manifest.pop("hash", None)
    else:
        download_url = detector.construct_download_url(DOWNLOAD_URL_TEMPLATE, version, match_groups)
        hash_value = detector.calculate_hash(download_url)
        if not hash_value:
            if not structured_only:
                print(f"❌ Failed to calculate hash for {SOFTWARE_NAME}")
            print(
                json.dumps(
                    {
                        "updated": False,
                        "name": SOFTWARE_NAME,
                        "version": version,
                        "error": "hash_unavailable",
                    }
                )
            )
            return False
        manifest["url"] = download_url
        manifest["hash"] = f"sha256:{hash_value}"

    # Save updated manifest
    try:
        with open(BUCKET_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

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


def main():
    """Main update function"""
    success = update_manifest(force=is_forced())
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
