#!/usr/bin/env python3
"""CoreCycler Scoop Bucket Updater

Crawls CoreCycler releases and updates the Scoop bucket JSON with latest versions,
hashes, and extract directories for Windows builds.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.parse import urljoin

# Constants
GITHUB_API_BASE = "https://api.github.com/repos/sp00n/CoreCycler"
GITHUB_RELEASE_BASE = "https://github.com/sp00n/CoreCycler/releases/download/"
BUCKET_PATH = Path(__file__).parent.parent / "bucket" / "corecycler.json"
VERSION_PATTERN = re.compile(r'v?(\d+\.\d+\.\d+\.\d+(?:alpha\d+)?)')

def fetch_latest_version() -> Optional[str]:
    """Fetch the latest CoreCycler version from GitHub releases, preferring pre-releases."""
    try:
        # Get all releases to find the most recent one (including pre-releases)
        api_url = f"{GITHUB_API_BASE}/releases"
        with urlopen(api_url) as response:
            releases = json.loads(response.read().decode('utf-8'))
        
        if not releases:
            print("No releases found")
            return None
            
        # Get the most recent release (first in the list) - this includes pre-releases
        latest_release = releases[0]
        tag_name = latest_release.get('tag_name', '')
        version_match = VERSION_PATTERN.match(tag_name)
        if version_match:
            version = version_match.group(1)
            is_prerelease = latest_release.get('prerelease', False)
            release_type = "pre-release" if is_prerelease else "stable"
            print(f"Found latest {release_type} version: {version}")
            return version
            
        return None
    except Exception as e:
        print(f"Error fetching latest version: {e}")
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

def fetch_hash(version: str) -> Optional[str]:
    """Fetch SHA256 hash for the given version."""
    try:
        # Construct the download URL
        download_url = f"{GITHUB_RELEASE_BASE}v{version}/CoreCycler-v{version}.7z"
        return calculate_hash_from_url(download_url)
    except Exception as e:
        print(f"Error fetching hash: {e}")
        return None

def git_commit_and_push(version: str) -> bool:
    """Commit and push changes to git repository."""
    try:
        repo_path = BUCKET_PATH.parent.parent

        # Git add all changes
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)

        # Git commit with version message
        commit_msg = f"update: corecycler v{version}"
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

def update_bucket_json(version: str, hash_val: str) -> bool:
    """Update the Scoop bucket JSON file with new version information and hash."""
    try:
        with open(BUCKET_PATH, 'r', encoding='utf-8') as f:
            bucket_data = json.load(f)

        current_version = bucket_data.get("version")
        
        if current_version == version:
            print(f"Version unchanged: {version}")
            # Still update hash in case it changed
            bucket_data["hash"] = f"sha256:{hash_val}"
        else:
            print(f"Updating version from {current_version} to {version}")
            
            # Update version
            bucket_data["version"] = version
            
            # Update URL
            bucket_data["url"] = f"https://github.com/sp00n/CoreCycler/releases/download/v{version}/CoreCycler-v{version}.7z"
            
            # Update hash
            bucket_data["hash"] = f"sha256:{hash_val}"
            
            # Update extract_dir
            bucket_data["extract_dir"] = f"CoreCycler-v{version}"

        # Write updated JSON with proper formatting
        with open(BUCKET_PATH, 'w', encoding='utf-8') as f:
            json.dump(bucket_data, f, indent=4, ensure_ascii=False)

        print(f"Successfully updated bucket JSON")
        return True

    except Exception as e:
        print(f"Error updating bucket JSON: {e}")
        return False

def get_current_version() -> Optional[str]:
    """Get the current version from the bucket JSON file."""
    try:
        with open(BUCKET_PATH, 'r', encoding='utf-8') as f:
            bucket_data = json.load(f)
        return bucket_data.get('version')
    except Exception as e:
        print(f"Error reading current version: {e}")
        return None

def main() -> None:
    """Main execution function."""
    print("Checking for CoreCycler updates...")

    # Get current version
    current_version = get_current_version()
    print(f"Current version: {current_version}")

    # Get latest version
    latest_version = fetch_latest_version()
    if not latest_version:
        print("Cannot update: failed to fetch latest version")
        return

    print(f"Latest version: {latest_version}")

    # Check if version has changed
    if current_version == latest_version:
        print(f"No update needed: version {latest_version} is already current")
        return

    # Download and calculate hash
    print(f"Version changed from {current_version} to {latest_version}")
    hash_val = fetch_hash(latest_version)
    
    if not hash_val:
        print("Cannot update: failed to calculate hash")
        return

    print(f"✓ Version: {latest_version}")
    print(f"✓ Hash: {hash_val}")

    # Update bucket
    if update_bucket_json(latest_version, hash_val):
        # Commit and push changes if update was successful
        git_commit_and_push(latest_version)
    else:
        print("Failed to update bucket JSON")

if __name__ == "__main__":
    main()