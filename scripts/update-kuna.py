#!/usr/bin/env python3
"""
Kuna Update Script

Keeps bucket/kuna.json in sync with Noelo-Lab/kuna releases. Upstream ships the
Windows binaries and the Ghidra processor specs as two separate release assets,
so the 64bit block keeps ``url``/``hash`` arrays and ``env_set.KUNA_SPECS``
points at the specs tree that the second archive extracts.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from git_helpers import maybe_auto_commit
from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig

# Configuration
SOFTWARE_NAME = "kuna"
HOMEPAGE_URL = "https://api.github.com/repos/Noelo-Lab/kuna/releases"
# The Windows archive is first so ``extract_dir`` binds to it positionally; the
# specs tarball must follow, because Scoop pairs extract_dir with archives by
# index (lib/decompress.ps1) and the specs tree extracts to the app root.
WINDOWS_URL_TEMPLATE = "https://github.com/Noelo-Lab/kuna/releases/download/v$version/kuna-v$version-windows-x86_64.zip"
SPECS_URL_TEMPLATE = (
    "https://github.com/Noelo-Lab/kuna/releases/download/v$version/kuna-v$version-specs.tar.gz"
)
BUCKET_DIR = Path(__file__).parent.parent / "bucket"


class KunaManifestUpdater(ManifestUpdater):
    """Updater that preserves kuna's two-asset 64bit block.

    The base implementation assigns a single ``url``/``hash`` string, which would
    drop the specs archive and leave ``env_set.KUNA_SPECS`` dangling on every
    version bump. Assets stay positional: Windows zip first, specs tarball
    second.
    """

    specs_url_template = SPECS_URL_TEMPLATE

    def _stored_manifest_hash(self, manifest: Dict[str, Any]) -> Optional[str]:
        """Return the Windows-archive digest, which is what the drift check compares.

        The base implementation stringifies the whole ``hash`` list, so an
        array-shaped manifest would never compare equal to the upstream digest
        and every run would look like a re-release.
        """
        architecture_key = self.select_architecture_key(manifest)
        if architecture_key:
            entry = manifest["architecture"].get(architecture_key)
            if isinstance(entry, dict) and entry.get("hash"):
                stored = entry["hash"]
                if isinstance(stored, list):
                    return str(stored[0]) if stored else None
                return str(stored)
        top_level = manifest.get("hash")
        if top_level:
            return (
                str(top_level[0]) if isinstance(top_level, list) and top_level else str(top_level)
            )
        return None

    def apply_download_metadata(
        self,
        manifest: Dict[str, Any],
        *,
        version: str,
        download_url: str,
        hash_value: str,
        previous_version: Optional[str] = None,
    ) -> None:
        """Write both asset urls and hashes into the 64bit block."""
        manifest["version"] = version
        self._refresh_extract_dir(manifest, version=version, previous_version=previous_version)

        specs_url = self.specs_url_template.replace("$version", version)
        specs_hash = self.detector.calculate_hash(specs_url)
        if not specs_hash:
            raise RuntimeError(f"could not compute sha256 for {specs_url}")

        architecture_key = self.select_architecture_key(manifest)
        architecture = manifest.setdefault("architecture", {})
        entry = architecture.get(architecture_key)
        if not isinstance(entry, dict):
            entry = {}
            architecture[architecture_key] = entry

        urls: List[str] = [download_url, specs_url]
        hashes: List[str] = [f"sha256:{hash_value}", f"sha256:{specs_hash}"]
        entry["url"] = urls
        entry["hash"] = hashes
        # A stale top-level pair silently breaks installs once an architecture
        # block carries the real metadata (the veracrypt incident).
        manifest.pop("url", None)
        manifest.pop("hash", None)


def update_manifest(force: bool = False) -> bool:
    """Update the kuna manifest via the framework, preserving both assets."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        # Fallback-only pattern; require_release_asset is the real gate for a
        # release that actually ships the Windows binary.
        version_patterns=[r'"tag_name":\s*"v?([\d.]+)"'],
        download_url_template=WINDOWS_URL_TEMPLATE,
        description=(
            "Agent-first decompiler designed to be refined by other agents, "
            "ported from Ghidra and written in Rust"
        ),
        license="Apache-2.0",
        require_release_asset=True,
    )

    updater = KunaManifestUpdater(config, BUCKET_DIR, force=force)
    return updater.update()


def main() -> None:
    """Main update function."""
    if not update_manifest(force=is_forced()):
        sys.exit(1)

    maybe_auto_commit(SOFTWARE_NAME, BUCKET_DIR / f"{SOFTWARE_NAME}.json", sys.argv[1:])


if __name__ == "__main__":
    main()
