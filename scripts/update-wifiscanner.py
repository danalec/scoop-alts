#!/usr/bin/env python3
"""
Wifiscanner Update Script
Automatically checks for updates and updates the Scoop manifest.
"""

import json
import re
import requests
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

# Configuration
HOMEPAGE_URL = "https://lizardsystems.com/wi-fi-scanner/"
DOWNLOAD_URL_TEMPLATE = ""
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "wifiscanner.json"

class WifiscannerUpdater:
    """Handles Wifiscanner updates"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'identity',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def fetch_latest_version(self) -> Optional[str]:
        """Fetch the latest version from the homepage"""
        try:
            print(f"🔍 Scraping version from: {HOMEPAGE_URL}")
            response = self.session.get(HOMEPAGE_URL, timeout=30)
            response.raise_for_status()
            
            content = response.text
            
            # Version patterns for Wifiscanner
            version_patterns = [
                r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
                r'Version:?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)',
                r'v\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)',
                r'([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)\s*(?:version|release)',
            ]
            
            for pattern in version_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    # Get the latest version (assuming semantic versioning)
                    versions = [match if isinstance(match, str) else match[0] for match in matches]
                    latest_version = max(versions, key=lambda v: [int(x) for x in v.split('.')])
                    print(f"✅ Found Wifiscanner version: {latest_version}")
                    return latest_version
            
            print("❌ No version found on the page")
            return None
            
        except Exception as e:
            print(f"❌ Error fetching version: {e}")
            return None

    def get_download_url(self, version: str) -> str:
        """Generate download URL for the given version"""
        if DOWNLOAD_URL_TEMPLATE:
            return DOWNLOAD_URL_TEMPLATE.replace("$version", version)
        else:
            # Fallback: try to construct URL from current manifest
            with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
                current_manifest = json.load(f)
            current_url = current_manifest.get('url', '')
            current_version = current_manifest.get('version', '')
            
            if current_version and current_version in current_url:
                return current_url.replace(current_version, version)
            else:
                raise ValueError("Cannot determine download URL pattern")

    def calculate_hash(self, url: str) -> str:
        """Calculate SHA256 hash of the downloaded file"""
        try:
            print(f"🔍 Calculating hash for: {url}")
            response = self.session.get(url, timeout=60, stream=True)
            response.raise_for_status()
            
            sha256_hash = hashlib.sha256()
            for chunk in response.iter_content(chunk_size=8192):
                sha256_hash.update(chunk)
            
            hash_value = sha256_hash.hexdigest()
            print(f"✅ Hash calculated: {hash_value}")
            return hash_value
            
        except Exception as e:
            print(f"❌ Error calculating hash: {e}")
            raise

    def update_manifest(self, new_version: str, new_url: str, new_hash: str) -> bool:
        """Update the manifest file with new version info"""
        try:
            with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            # Update version, URL, and hash
            manifest['version'] = new_version
            manifest['url'] = new_url
            manifest['hash'] = f"sha256:{new_hash}"
            
            # Update bin name if it contains version
            if 'bin' in manifest and isinstance(manifest['bin'], str):
                old_version = manifest['version'] if 'version' in manifest else ''
                if old_version and old_version in manifest['bin']:
                    manifest['bin'] = manifest['bin'].replace(old_version, new_version)
            
            # Update shortcuts if they contain version
            if 'shortcuts' in manifest:
                for shortcut in manifest['shortcuts']:
                    if isinstance(shortcut, list) and len(shortcut) > 0:
                        if old_version and old_version in shortcut[0]:
                            shortcut[0] = shortcut[0].replace(old_version, new_version)
            
            # Save updated manifest
            with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=4, ensure_ascii=False)
            
            print(f"✅ Updated manifest: {BUCKET_FILE}")
            return True
            
        except Exception as e:
            print(f"❌ Error updating manifest: {e}")
            return False

    def commit_and_push(self, version: str) -> bool:
        """Commit and push changes to git repository"""
        try:
            # Add the updated manifest
            subprocess.run(['git', 'add', str(BUCKET_FILE)], check=True, cwd=BUCKET_FILE.parent.parent)
            
            # Commit with descriptive message
            commit_message = f"Update wifiscanner to version {version}"
            subprocess.run(['git', 'commit', '-m', commit_message], check=True, cwd=BUCKET_FILE.parent.parent)
            
            # Push to remote
            subprocess.run(['git', 'push'], check=True, cwd=BUCKET_FILE.parent.parent)
            
            print(f"✅ Committed and pushed changes")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Git operation failed: {e}")
            return False

    def run_update(self) -> bool:
        """Main update process"""
        print(f"🚀 Starting Wifiscanner update check...")
        
        # Get current version
        try:
            with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
                current_manifest = json.load(f)
            current_version = current_manifest.get('version', 'unknown')
        except Exception:
            current_version = 'unknown'
        
        # Fetch latest version
        latest_version = self.fetch_latest_version()
        if not latest_version:
            print("❌ Failed to fetch latest version")
            return False
        
        # Check if update is needed
        if current_version == latest_version:
            print(f"ℹ️  Current version {current_version} is up to date (latest: {latest_version})")
            print("ℹ️  No update needed")
            return True
        
        print(f"🔄 Update available: {current_version} → {latest_version}")
        
        # Get download URL and calculate hash
        try:
            download_url = self.get_download_url(latest_version)
            print(f"📦 Download URL: {download_url}")
            
            file_hash = self.calculate_hash(download_url)
            
            # Update manifest
            if self.update_manifest(latest_version, download_url, file_hash):
                print(f"✅ Successfully updated Wifiscanner to version {latest_version}")
                
                # Optionally commit and push (uncomment if desired)
                # self.commit_and_push(latest_version)
                
                return True
            else:
                print("❌ Failed to update manifest")
                return False
                
        except Exception as e:
            print(f"❌ Update failed: {e}")
            return False

def main():
    """Main function"""
    updater = WifiscannerUpdater()
    success = updater.run_update()
    
    if success:
        print(f"✨ Wifiscanner update check completed")
    else:
        print(f"💥 Wifiscanner update check failed")
        exit(1)

if __name__ == "__main__":
    main()
