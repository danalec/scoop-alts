#!/usr/bin/env python3
"""
GhydraMCP Update Script

Keeps bucket/ghydramcp.json in sync with danalec/GhydraMCP releases. Upstream
publishes one extension bundle per Ghidra version line plus the stdio bridge as
a separate asset, so the manifest keeps top-level ``url``/``hash``/``extract_to``
arrays:

* ``url[0]`` is the ghidra11.4.3 zip, ``url[1]`` the ghidra12.2 zip, and
  ``url[2]`` the bridge script;
* ``extract_to`` has exactly two entries because Scoop pairs it with the
  *archives* by archive index (lib/decompress.ps1), so the bridge is not an
  extraction target.

Assets are selected by name, never by position: a release also ships
``Ghydra-Complete-...`` bundles and a checksum file, and the API's asset order
is not part of the contract. The release API's ``digest`` field supplies each
sha256 without a download; a missing digest falls back to the shared hash
helper. Upstream asset names are timestamped, so the manifest has no
``autoupdate`` block - ``checkver`` stays the only automation hint.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from git_helpers import maybe_auto_commit
from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig, VersionDetector

# Configuration
SOFTWARE_NAME = "ghydramcp"
RELEASES_API_URL = "https://api.github.com/repos/danalec/GhydraMCP/releases/latest"
BRIDGE_ASSET_NAME = "bridge_mcp_hydra.py"
BRIDGE_ASSET_KEY = "bridge"
# Order is part of the manifest contract: it fixes which position each archive
# and hash occupies, and the positions must stay aligned.
GHIDRA_VARIANTS = ("ghidra11.4.3", "ghidra12.2")
BUCKET_DIR = Path(__file__).parent.parent / "bucket"

_TAG_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")
# The plain bundle starts with "Ghydra-v"; the Complete variant starts with
# "Ghydra-Complete-v" and can therefore never match.
_PLAIN_GHIDRA_ASSET_RE = re.compile(
    r"^Ghydra-v(?P<version>[^-]+)-\d{8}-\d{6}-(?P<variant>ghidra[0-9.]+)\.zip$"
)
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_release_version(release: Dict[str, Any]) -> Optional[str]:
    """Return the dotted version carried by a release tag, or None when unparseable."""
    match = _TAG_VERSION_RE.match(str(release.get("tag_name") or "").strip())
    return match.group(1) if match else None


def select_release_assets(release: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Map every required asset to its release entry, selected by name.

    The keys are the two Ghidra variants plus ``"bridge"``. Selecting by name
    keeps the result independent of the API's asset order and skips the
    ``Complete`` bundles, which the manifest does not ship. When a name appears
    twice the first entry wins, so the result stays deterministic.
    """
    selected: Dict[str, Dict[str, Any]] = {}
    assets = release.get("assets")
    if not isinstance(assets, list):
        return selected
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not name or not url:
            continue
        if name == BRIDGE_ASSET_NAME:
            selected.setdefault(BRIDGE_ASSET_KEY, asset)
            continue
        match = _PLAIN_GHIDRA_ASSET_RE.match(name)
        if match and match.group("variant") in GHIDRA_VARIANTS:
            selected.setdefault(match.group("variant"), asset)
    return selected


def asset_sha256(asset: Dict[str, Any], detector: VersionDetector) -> Optional[str]:
    """Return the asset's sha256 hex digest, preferring the release API digest.

    GitHub publishes ``digest: "sha256:..."`` for release assets, so the file
    never has to be downloaded. The shared hash helper is the fallback for a
    release whose digest field is absent or malformed.
    """
    digest = str(asset.get("digest") or "").strip()
    if digest.lower().startswith("sha256:"):
        candidate = digest.split(":", 1)[1].strip().lower()
        if _SHA256_HEX_RE.match(candidate):
            return candidate
    url = str(asset.get("browser_download_url") or "")
    if not url:
        return None
    return detector.calculate_hash(url)


class GhydraMcpManifestUpdater(ManifestUpdater):
    """Updater that keeps both Ghidra bundles and the bridge script.

    The base implementation assigns a single ``url``/``hash`` string, which
    would drop two of the three assets on every bump; the arrays are written
    together so a hash can never end up paired with the wrong download.
    """

    def _fetch_release(self) -> Optional[Dict[str, Any]]:
        """Return the latest release metadata, or None when the API is unavailable.

        ``_cached_api_get`` is the framework's release cache and token-aware
        session, so this reuses the same retry/caching behavior as the rest of
        the automation instead of opening a second HTTP path.
        """
        release = self.detector._cached_api_get(RELEASES_API_URL)
        return release if isinstance(release, dict) else None

    def _release_hashes(self, selection: Dict[str, Dict[str, Any]]) -> Optional[List[str]]:
        """Return the three sha256 hex digests, or None when one cannot be resolved."""
        hashes: List[str] = []
        for key in (*GHIDRA_VARIANTS, BRIDGE_ASSET_KEY):
            digest = asset_sha256(selection[key], self.detector)
            if not digest:
                self.log(
                    f"❌ Could not resolve the sha256 for asset {selection[key].get('name')!r}"
                )
                return None
            hashes.append(digest)
        return hashes

    @staticmethod
    def _manifest_hashes(manifest: Dict[str, Any]) -> Optional[List[str]]:
        """Return the manifest's sha256 array as bare hex digests, or None when absent."""
        stored = manifest.get("hash")
        if not isinstance(stored, list) or len(stored) != len(GHIDRA_VARIANTS) + 1:
            return None
        hashes = [
            re.sub(r"^sha256:", "", str(item).strip(), flags=re.IGNORECASE).lower()
            for item in stored
        ]
        if not all(_SHA256_HEX_RE.match(value) for value in hashes):
            return None
        return hashes

    def update(self, version_info: Optional[Dict[str, Any]] = None) -> bool:
        """Fetch the latest release and write all three assets when they changed.

        ``version_info`` is accepted for interface compatibility with
        ``ManifestUpdater``; the release payload is the authority here because
        the hashes of every asset are required, not just the first one.
        """
        self.log(f"🔄 Updating {self.config.name}...")

        manifest = self.load_manifest()
        if manifest is None:
            return False
        current_version = str(manifest.get("version", ""))

        release = self._fetch_release()
        if release is None:
            self.log("❌ Failed to read the GhydraMCP release metadata")
            self.emit_result(updated=False, error="release_metadata_unavailable")
            return False

        version = parse_release_version(release)
        if not version:
            self.log(f"❌ Unparseable release tag: {release.get('tag_name')!r}")
            self.emit_result(updated=False, error="release_tag_unparseable")
            return False

        selection = select_release_assets(release)
        missing = [variant for variant in GHIDRA_VARIANTS if variant not in selection]
        if BRIDGE_ASSET_KEY not in selection:
            missing.append(BRIDGE_ASSET_NAME)
        if missing:
            self.log(f"❌ Release v{version} is missing asset(s): {', '.join(missing)}")
            self.emit_result(updated=False, version=version, error="release_asset_missing")
            return False

        hashes = self._release_hashes(selection)
        if hashes is None:
            self.emit_result(updated=False, version=version, error="hash_unavailable")
            return False

        revision = False
        if current_version == version and not self.force:
            if self._manifest_hashes(manifest) == hashes:
                self.log(f"✅ {self.config.name} is already up to date (v{version})")
                self.emit_result(updated=False, version=version)
                return True
            revision = True
            self.log(
                f"🔄 Upstream re-released {self.config.name} v{version} "
                "with new assets - refreshing"
            )
        elif current_version == version:
            self.log(f"🔄 Forcing update of {self.config.name} (v{version})...")

        urls: List[str] = [
            f"{selection[variant]['browser_download_url']}#/{variant}.zip"
            for variant in GHIDRA_VARIANTS
        ]
        urls.append(str(selection[BRIDGE_ASSET_KEY]["browser_download_url"]))

        manifest["version"] = version
        manifest["url"] = urls
        manifest["hash"] = [f"sha256:{digest}" for digest in hashes]
        return self.save_manifest(manifest, version, current_version, revision=revision)


def build_config() -> SoftwareVersionConfig:
    """Return the package configuration the framework needs for the manifest."""
    return SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=RELEASES_API_URL,
        version_patterns=[r'"tag_name":\s*"v?([\d.]+)"'],
        description=(
            "Ghidra extension and stdio MCP bridge that serve live Ghidra analysis "
            "(plus x64dbg debugging) to AI agent harnesses."
        ),
        license="Apache-2.0",
    )


def update_manifest(force: bool = False) -> bool:
    """Update the ghydramcp manifest, keeping both Ghidra bundles and the bridge."""
    updater = GhydraMcpManifestUpdater(build_config(), BUCKET_DIR, force=force)
    return updater.update()


def main() -> None:
    """Run the updater and exit non-zero when it fails."""
    if not update_manifest(force=is_forced()):
        sys.exit(1)

    maybe_auto_commit(SOFTWARE_NAME, BUCKET_DIR / f"{SOFTWARE_NAME}.json", sys.argv[1:])


if __name__ == "__main__":
    main()
