#!/usr/bin/env python3
"""Ungoogled Chromium Scoop Bucket Updater

Crawls ungoogled-chromium releases and updates the Scoop bucket JSON with latest versions,
hashes, and extract directories for both 64-bit and 32-bit Windows builds.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.request import urlopen
from urllib.parse import urljoin

# Constants
BASE_URL = "https://ungoogled-software.github.io/ungoogled-chromium-binaries/releases/windows/"
ARCH_URLS = {
    "64bit": f"{BASE_URL}64bit/",
    "32bit": f"{BASE_URL}32bit/"
}
GITHUB_RELEASE_BASE = "https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/"
BUCKET_PATH = Path(__file__).parent.parent / "bucket" / "ungoogled-chromium.json"
VERSION_PATTERN = re.compile(r'(\d+\.\d+\.\d+\.\d+-\d+(?:\.\d+)?)')

def fetch_latest_version(arch: str) -> Optional[str]:
    """Fetch the latest ungoogled-chromium version from GitHub releases."""
    try:
        api_url = "https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases/latest"
        with urlopen(api_url) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        tag_name = data.get('tag_name', '')
        # Extract version from tag like "139.0.7258.154-1.1" -> "139.0.7258.154-1.1"
        version_match = re.match(r'(\d+\.\d+\.\d+\.\d+-\d+(?:\.\d+)?)', tag_name)
        if version_match:
            version = version_match.group(1)
            print(f"Found latest version: {version}")
            return version
        
        return None
    except Exception as e:
        print(f"Error fetching latest version: {e}")
        return None

def fetch_hash_from_github(version: str, arch: str) -> Optional[str]:
    """Fetch SHA256 hash from GitHub release assets."""
    try:
        api_url = f"https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases/tags/{version}"
        with urlopen(api_url) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        arch_suffix = "x64" if arch == "64bit" else "x86"
        filename = f"ungoogled-chromium_{version}_windows_{arch_suffix}.zip"
        
        # Look for the asset and its SHA256 in the release
        for asset in data.get('assets', []):
            if asset.get('name') == filename:
                # GitHub doesn't provide SHA256 in API, so we'll download and calculate
                return calculate_hash_from_url(asset.get('browser_download_url'))
        
        # Fallback: construct URL manually
        download_url = f"{GITHUB_RELEASE_BASE}{version}/{filename}"
        return calculate_hash_from_url(download_url)
    except Exception as e:
        print(f"Error fetching hash from GitHub: {e}")
        return None

def calculate_hash_from_url(url: str) -> Optional[str]:
    """Download file and calculate SHA256 hash."""
    try:
        print(f"Downloading file to calculate hash: {url}")
        with urlopen(url) as response:
            sha256_hash = hashlib.sha256()
            for chunk in iter(lambda: response.read(4096), b""):
                sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
    except Exception as e:
        print(f"Error calculating hash from URL: {e}")
        return None

def fetch_hash(version: str, arch: str) -> Optional[str]:
    """Fetch SHA256 hash for the given version and architecture."""
    return fetch_hash_from_github(version, arch)

def get_version_info() -> Dict[str, Tuple[str, Optional[str]]]:
    """Get latest version and hashes for both architectures."""
    version = fetch_latest_version("windows")
    if not version:
        return {}
    
    return {
        "64bit": (version, fetch_hash(version, "64bit")),
        "32bit": (version, fetch_hash(version, "32bit"))
    }

def git_commit_and_push(version: str) -> bool:
    """Commit and push changes to git repository."""
    try:
        repo_path = BUCKET_PATH.parent.parent

        # Git add all changes
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)

        # Git commit with version message
        commit_msg = f"update: ungoogled-chromium v.{version}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True, capture_output=True)

        # Git push
        subprocess.run(["git", "push"], cwd=repo_path, check=True, capture_output=True)

        print(f"Successfully committed and pushed changes: {commit_msg}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
        return False
    except Exception as e:
        print(f"Error during git operations: {e}")
        return False

def update_bucket_json(version_info: Dict[str, Tuple[str, Optional[str]]], force_update: bool = False) -> Optional[str]:
    """Update the Scoop bucket JSON file with new version information and hashes.

    Returns the new version if updated, None if no update needed or failed.
    """
    try:
        with open(BUCKET_PATH, 'r', encoding='utf-8') as f:
            bucket_data = json.load(f)

        # Get the latest version (assuming both archs have same version)
        latest_version = next((v for v, _ in version_info.values() if v), None)
        if not latest_version:
            print("No valid version found")
            return None

        # Always update hashes even if version is the same
        if bucket_data.get("version") == latest_version and not force_update:
            print(f"Version unchanged, updating hashes only: {latest_version}")
        elif bucket_data.get("version") != latest_version:
            print(f"Updating version from {bucket_data.get('version')} to {latest_version}")
            bucket_data["version"] = latest_version

        # Update architecture-specific data
        for arch, (version, hash_val) in version_info.items():
            if not version or not hash_val:
                print(f"Missing data for {arch}: version={version}, hash={hash_val}")
                continue

            arch_suffix = "x64" if arch == "64bit" else "x86"
            arch_data = bucket_data["architecture"][arch]

            # Update URL, hash, and extract_dir
            arch_data.update({
                "url": f"https://github.com/ungoogled-software/ungoogled-chromium-windows/releases/download/{version}/ungoogled-chromium_{version}_windows_{arch_suffix}.zip",
                "hash": hash_val,
                "extract_dir": f"ungoogled-chromium_{version}_windows_{arch_suffix}"
            })

        # Write updated JSON
        with open(BUCKET_PATH, 'w', encoding='utf-8') as f:
            json.dump(bucket_data, f, indent=4, ensure_ascii=False)

        print(f"Successfully updated bucket JSON")
        return latest_version

    except Exception as e:
        print(f"Error updating bucket JSON: {e}")
        return None

def main() -> None:
    """Main execution function."""
    print("Checking for ungoogled-chromium updates...")

    version_info = get_version_info()

    # Display found versions
    for arch, (version, hash_val) in version_info.items():
        status = "✓" if version and hash_val else "✗"
        print(f"{status} {arch}: {version or 'Not found'} (hash: {'found' if hash_val else 'missing'})")

    # Update bucket if we have valid data
    if all(v and h for v, h in version_info.values()):
        if updated_version := update_bucket_json(version_info):
            # Commit and push changes if update was successful
            git_commit_and_push(updated_version)
    else:
        print("Cannot update: missing version or hash data")

if __name__ == "__main__":
    main()
