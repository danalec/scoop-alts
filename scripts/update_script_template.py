#!/usr/bin/env python3
"""Template for Scoop update scripts built on the shared manifest updater."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig


def build_config() -> SoftwareVersionConfig:
    """Return the package-specific configuration used by the updater."""
    return SoftwareVersionConfig(
        name="example-software",
        homepage="https://example.com",
        version_patterns=[
            r"Version:?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
            r"v\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
        ],
        download_url_template="https://example.com/download/v$version/software.exe",
        description="Example software package",
        license="MIT",
    )


def update_manifest(config: SoftwareVersionConfig, bucket_dir: Path) -> bool:
    """Update the example manifest using the shared updater."""
    updater = ManifestUpdater(config, bucket_dir)
    return updater.update()


def maybe_auto_commit(package_name: str, bucket_dir: Path) -> None:
    """Optionally commit the updated manifest after a successful run."""
    auto_commit = (
        "--auto-commit" in sys.argv
        or os.environ.get("AUTO_COMMIT") == "1"
        or os.environ.get("SCOOP_AUTO_COMMIT") == "1"
    )
    if not auto_commit:
        return

    try:
        from git_helpers import commit_manifest_change

        commit_manifest_change(package_name, str(bucket_dir / f"{package_name}.json"), push=True)
    except Exception as error:
        print(f"⚠️  Auto-commit failed: {error}")


def main() -> None:
    """Run the template update flow."""
    config = build_config()
    bucket_dir = Path(__file__).parent.parent / "bucket"

    if not update_manifest(config, bucket_dir):
        sys.exit(1)

    maybe_auto_commit(config.name, bucket_dir)


if __name__ == "__main__":
    main()
