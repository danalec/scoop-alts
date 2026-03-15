#!/usr/bin/env python3
"""
Ripgrep All Update Script
Automatically checks for updates and updates the Scoop manifest using shared version detector.
"""

import json
import sys
import os
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info
from manifest_manager import ManifestUpdater

# Configuration
SOFTWARE_NAME = "ripgrep-all"
HOMEPAGE_URL = "https://github.com/phiresky/ripgrep-all/releases"
DOWNLOAD_URL_TEMPLATE = "https://github.com/phiresky/ripgrep-all/releases/download/v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
BUCKET_DIR = Path(__file__).parent.parent / "bucket"

def update_manifest():
    """Update the Scoop manifest using shared version detection"""
    
    # Configure software version detection
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['releases/tag/v(0\\.10\\.9)'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
        description="Ripgrep-All - Search in PDFs, e-books, Office docs, archives, and media via ripgrep",
        license="AGPL-3.0-or-later"
    )
    
    updater = ManifestUpdater(config, BUCKET_DIR)
    return updater.update()

def main():
    """Main update function"""
    success = update_manifest()
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
            commit_manifest_change(SOFTWARE_NAME, str(BUCKET_DIR / f"{SOFTWARE_NAME}.json"), push=True)
        except Exception as e:
            print(f"⚠️  Auto-commit failed: {e}")

if __name__ == "__main__":
    main()