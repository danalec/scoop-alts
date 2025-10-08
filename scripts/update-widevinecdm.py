#!/usr/bin/env python3
"""
Widevinecdm Update Script
Fetches version and architecture-specific download info from the Chrome UpdateTracker XML
and updates the Scoop manifest using XML-provided URLs and SHA256 values (no downloads).
"""

import json
import re
import sys
from pathlib import Path
import requests

# Configuration
SOFTWARE_NAME = "widevinecdm"
XML_URL = "https://scoopinstaller.github.io/UpdateTracker/googlechrome/chrome.min.xml"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "widevinecdm.json"

TOKEN_REGEX = re.compile(
    r"(?s)<stable32>.*?<version>([\d.]+)</version>.*?release2/chrome/([A-Za-z0-9_-]+)_.*?</stable32>.*?"
    r"<stable64>.*?release2/chrome/([A-Za-z0-9_-]+)_.*?</stable64>"
)
SHA32_REGEX = re.compile(r"(?s)<stable32>.*?<sha256>([a-f0-9]{64})</sha256>.*?</stable32>")
SHA64_REGEX = re.compile(r"(?s)<stable64>.*?<sha256>([a-f0-9]{64})</sha256>.*?</stable64>")

def fetch_update_xml() -> str:
    """Download the UpdateTracker XML content."""
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
    })
    resp = s.get(XML_URL, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_version_and_tokens(xml: str):
    """Extract version, 32-bit token, 64-bit token and SHA256 hashes from XML."""
    m = TOKEN_REGEX.search(xml)
    if not m:
        return None
    version, token32, token64 = m.groups()
    m32 = SHA32_REGEX.search(xml)
    m64 = SHA64_REGEX.search(xml)
    sha32 = m32.group(1) if m32 else None
    sha64 = m64.group(1) if m64 else None
    return {
        'version': version,
        'token32': token32,
        'token64': token64,
        'sha32': sha32,
        'sha64': sha64,
    }

def build_urls(version: str, token32: str, token64: str, variant: str = "uncompressed"):
    """Construct architecture-specific download URLs using tokens and version.
    Variant can be 'uncompressed' (preferred) or 'compressed'.
    Rename to chrome.7z to match installer script expectations.
    """
    if variant == "uncompressed":
        suffix = "_chrome_installer_uncompressed.exe"
    else:
        suffix = "_chrome_installer.exe"
    url64 = f"https://dl.google.com/release2/chrome/{token64}_{version}/{version}{suffix}#/chrome.7z"
    url32 = f"https://dl.google.com/release2/chrome/{token32}_{version}/{version}{suffix}#/chrome.7z"
    return url32, url64

def validate_url(url: str) -> bool:
    """Check if the URL is accessible via HEAD, fall back to GET with Range."""
    try:
        s = requests.Session()
        r = s.head(url.split('#', 1)[0], timeout=20, allow_redirects=True)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        s = requests.Session()
        r = s.get(url.split('#', 1)[0], headers={'Range': 'bytes=0-0'}, timeout=20)
        return r.status_code in (200, 206)
    except Exception:
        return False

def update_manifest():
    """Update the Scoop manifest by parsing XML for version, tokens, and hashes."""
    print(f"Updating {SOFTWARE_NAME}...")

    # Fetch and parse XML
    try:
        xml = fetch_update_xml()
    except Exception as e:
        print(f"Error: Failed to fetch XML: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "xml_fetch_failed"}))
        return False

    info = parse_version_and_tokens(xml)
    if not info:
        print("Error: Failed to parse version/tokens from XML")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "xml_parse_failed"}))
        return False

    version = info['version']
    token32 = info['token32']
    token64 = info['token64']
    sha32 = info['sha32']
    sha64 = info['sha64']

    # Prefer uncompressed installer variant; fall back to compressed if needed
    chosen_variant = "uncompressed"
    url32, url64 = build_urls(version, token32, token64, variant=chosen_variant)

    # Validate URLs; if invalid, try to refetch XML once to get fresh tokens
    if not (validate_url(url32) and validate_url(url64)):
        # Try compressed variant as fallback
        chosen_variant = "compressed"
        url32, url64 = build_urls(version, token32, token64, variant=chosen_variant)

    # Validate URLs; if invalid, try to refetch XML once to get fresh tokens
    if not (validate_url(url32) and validate_url(url64)):
        try:
            xml = fetch_update_xml()
            info2 = parse_version_and_tokens(xml)
            if info2:
                version = info2['version']
                token32 = info2['token32']
                token64 = info2['token64']
                sha32 = info2['sha32']
                sha64 = info2['sha64']
                # Try uncompressed first on fresh tokens
                chosen_variant = "uncompressed"
                url32, url64 = build_urls(version, token32, token64, variant=chosen_variant)
                if not (validate_url(url32) and validate_url(url64)):
                    # Fallback to compressed
                    chosen_variant = "compressed"
                    url32, url64 = build_urls(version, token32, token64, variant=chosen_variant)
        except Exception:
            pass

    if not (validate_url(url32) and validate_url(url64)):
        print("Error: Generated Widevine URLs are not accessible (404). Skipping manifest update to avoid broken links.")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "urls_inaccessible"}))
        return False

    # Load existing manifest
    try:
        with open(BUCKET_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"Error: Manifest file not found: {BUCKET_FILE}")
        return False
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in manifest: {e}")
        return False

    # Check if update is needed
    current_version = manifest.get('version', '')
    if current_version == version and manifest.get('architecture', {}).get('64bit', {}).get('url', '') == url64:
        print(f"{SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    # Update manifest fields: version and architecture-specific URLs and hashes
    manifest['version'] = version
    if 'architecture' not in manifest:
        manifest['architecture'] = {}
    manifest['architecture']['64bit'] = manifest.get('architecture', {}).get('64bit', {})
    manifest['architecture']['32bit'] = manifest.get('architecture', {}).get('32bit', {})

    manifest['architecture']['64bit']['url'] = url64
    if sha64:
        manifest['architecture']['64bit']['hash'] = sha64

    manifest['architecture']['32bit']['url'] = url32
    if sha32:
        manifest['architecture']['32bit']['hash'] = sha32

    # Keep autoupdate URL templates in sync with rename fragment expected by installer
    try:
        if 'autoupdate' in manifest and 'architecture' in manifest['autoupdate']:
            if '64bit' in manifest['autoupdate']['architecture']:
                manifest['autoupdate']['architecture']['64bit']['url'] = (
                    "https://dl.google.com/release2/chrome/$match64_$version/" +
                    ("$version_chrome_installer_uncompressed.exe" if chosen_variant == "uncompressed" else "$version_chrome_installer.exe") +
                    "#/chrome.7z"
                )
            if '32bit' in manifest['autoupdate']['architecture']:
                manifest['autoupdate']['architecture']['32bit']['url'] = (
                    "https://dl.google.com/release2/chrome/$match32_$version/" +
                    ("$version_chrome_installer_uncompressed.exe" if chosen_variant == "uncompressed" else "$version_chrome_installer.exe") +
                    "#/chrome.7z"
                )
    except Exception:
        # If autoupdate structure is missing or different, skip template sync
        pass

    # Save updated manifest
    try:
        with open(BUCKET_FILE, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"Updated {SOFTWARE_NAME}: {current_version} -> {version}")
        print(f"   64-bit URL: {url64}")
        print(f"   32-bit URL: {url32}")
        print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
        return True

    except Exception as e:
        print(f"Error: Failed to save manifest: {e}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version, "error": "save_failed"}))
        return False

def main():
    """Main update function"""
    success = update_manifest()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
