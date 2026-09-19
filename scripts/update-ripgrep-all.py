#!/usr/bin/env python3
"""
Ripgrep All Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
Ensures only releases that ship Windows binaries are targeted, and supports forced execution.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig, VersionDetector, get_session

# Optional semantic version parsing
try:
    from packaging.version import parse as parse_version
except ImportError:
    parse_version = None

# Configuration
SOFTWARE_NAME = "ripgrep-all"
HOMEPAGE_URL = "https://github.com/phiresky/ripgrep-all/releases"
RELEASES_API_URL = "https://api.github.com/repos/phiresky/ripgrep-all/releases"
DOWNLOAD_URL_TEMPLATE = "https://github.com/phiresky/ripgrep-all/releases/download/v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


def get_latest_windows_release() -> Optional[str]:
    """Find the newest non-prerelease release that actually ships a Windows binary."""
    # 1. Try GitHub API
    try:
        session = get_session()
        resp = session.get(RELEASES_API_URL, timeout=15)
        if resp.status_code == 200:
            releases = resp.json()
            for rel in releases:
                if rel.get("draft") or rel.get("prerelease"):
                    continue
                tag = rel.get("tag_name", "").lstrip("v")
                expected = f"ripgrep_all-v{tag}-x86_64-pc-windows-msvc.zip"
                if any(a.get("name") == expected for a in rel.get("assets", [])):
                    return tag
    except Exception:
        pass

    # 2. Fallback to HTML releases page with URL validation
    try:
        resp = requests.get(HOMEPAGE_URL, timeout=15)
        if resp.status_code == 200:
            tags = set(re.findall(r"releases/tag/v([0-9.]+)(?:/|\"|\'|\s|>)", resp.text))
            if parse_version:
                sorted_tags = sorted(tags, key=parse_version, reverse=True)
            else:
                sorted_tags = sorted(
                    tags, key=lambda v: [int(p) for p in v.split(".") if p.isdigit()], reverse=True
                )
            for tag in sorted_tags:
                url = f"https://github.com/phiresky/ripgrep-all/releases/download/v{tag}/ripgrep_all-v{tag}-x86_64-pc-windows-msvc.zip"
                head_resp = requests.head(url, allow_redirects=True, timeout=5)
                if head_resp.status_code == 200:
                    return tag
    except Exception:
        pass

    return None


def update_manifest(force: bool = False) -> bool:
    """Update the Scoop manifest using shared version detection and Windows binary verification."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=[r"releases/tag/v(0\.10\.[0-9]+)"],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Ripgrep-All - Search in PDFs, e-books, Office docs, archives, and media via ripgrep",
        license="AGPL-3.0-or-later",
    )

    version = get_latest_windows_release()
    version_info: Optional[Dict[str, Any]] = None
    if version:
        download_url = DOWNLOAD_URL_TEMPLATE.replace("$version", version)
        detector = VersionDetector()
        hash_value = detector.calculate_hash(download_url)
        if hash_value:
            version_info = {
                "version": version,
                "download_url": download_url,
                "hash": hash_value,
            }

    updater = ManifestUpdater(config, BUCKET_DIR, force=force)
    return updater.update(version_info)


def main() -> None:
    """Main update function."""
    force = (
        "--force" in sys.argv
        or "-f" in sys.argv
        or "--forcedly" in sys.argv
        or "forcedly" in sys.argv
        or os.environ.get("FORCE") == "1"
        or os.environ.get("SCOOP_FORCE") == "1"
    )

    success = update_manifest(force=force)
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

            commit_manifest_change(
                SOFTWARE_NAME, str(BUCKET_DIR / f"{SOFTWARE_NAME}.json"), push=True
            )
        except Exception as e:
            print(f"⚠️  Auto-commit failed: {e}")


if __name__ == "__main__":
    main()
