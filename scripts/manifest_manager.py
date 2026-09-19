#!/usr/bin/env python3
"""Shared helpers for updating Scoop manifests from version metadata."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from version_detector import SoftwareVersionConfig, VersionDetector, get_version_info


def is_forced() -> bool:
    """Return True when a forced update was requested.

    Honored triggers: ``--force`` / ``-f`` on the command line, ``FORCE=1`` or
    ``SCOOP_FORCE=1`` in the environment (``update-all.py --force`` exports the
    latter so child updater scripts honor it), and the legacy ``forcedly``
    spellings kept for backward compatibility.
    """
    return (
        os.environ.get("FORCE") == "1"
        or os.environ.get("SCOOP_FORCE") == "1"
        or "--force" in sys.argv
        or "-f" in sys.argv
        or "--forcedly" in sys.argv
        or "forcedly" in sys.argv
    )


class ManifestUpdater:
    """Update a Scoop manifest using ``version_detector`` results."""

    def __init__(
        self,
        config: SoftwareVersionConfig,
        bucket_dir: Path,
        manifest_filename: Optional[str] = None,
        force: bool = False,
    ) -> None:
        self.config = config
        self.bucket_dir = bucket_dir
        self.manifest_filename = manifest_filename or f"{config.name}.json"
        self.manifest_path = bucket_dir / self.manifest_filename
        self.structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
        self.force = force or is_forced()
        self.detector = VersionDetector()

    def log(self, message: str) -> None:
        """Print human-readable status messages when structured output is disabled."""
        if not self.structured_only:
            print(message)

    def emit_result(
        self,
        *,
        updated: bool,
        version: Optional[str] = None,
        error: Optional[str] = None,
        forced: bool = False,
        revision: bool = False,
    ) -> None:
        """Emit the single-line JSON object consumed by the orchestrator."""
        payload: Dict[str, Any] = {"updated": updated, "name": self.config.name}
        if version:
            payload["version"] = version
        if error:
            payload["error"] = error
        if revision:
            payload["revision"] = True
        if forced:
            payload["forced"] = True
        print(json.dumps(payload, ensure_ascii=False))

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        """Load the manifest file or report a structured error."""
        if not self.manifest_path.exists():
            self.log(f"❌ Manifest file not found: {self.manifest_path}")
            self.emit_result(updated=False, error="manifest_not_found")
            return None

        try:
            with self.manifest_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as error:
            self.log(f"❌ Invalid JSON in manifest: {error}")
            self.emit_result(updated=False, error="invalid_manifest_json")
            return None
        except Exception as error:
            self.log(f"❌ Failed to load manifest: {error}")
            self.emit_result(updated=False, error="manifest_read_failed")
            return None

    def save_manifest(
        self,
        manifest: Dict[str, Any],
        version: str,
        previous_version: str,
        revision: bool = False,
    ) -> bool:
        """Write the updated manifest back to disk."""
        try:
            with self.manifest_path.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as error:
            self.log(f"❌ Failed to save manifest: {error}")
            self.emit_result(updated=False, version=version, error="save_failed")
            return False

        if revision:
            self.log(f"✅ Refreshed {self.config.name} build: {version}")
        elif previous_version == version:
            self.log(f"✅ Force-updated {self.config.name}: {version}")
        else:
            self.log(f"✅ Updated {self.config.name}: {previous_version} → {version}")
        self.emit_result(updated=True, version=version, forced=self.force, revision=revision)
        return True

    def select_architecture_key(self, manifest: Dict[str, Any]) -> Optional[str]:
        """Choose the most appropriate architecture block to update."""
        architecture = manifest.get("architecture")
        if not isinstance(architecture, dict) or not architecture:
            return None

        for candidate in ("64bit", "arm64", "32bit"):
            if candidate in architecture:
                return candidate
        return next(iter(architecture), None)

    def apply_download_metadata(
        self,
        manifest: Dict[str, Any],
        *,
        version: str,
        download_url: str,
        hash_value: str,
        previous_version: Optional[str] = None,
    ) -> None:
        """Update version, url, and hash fields in-place."""
        manifest["version"] = version
        self._refresh_extract_dir(manifest, version=version, previous_version=previous_version)
        architecture_key = self.select_architecture_key(manifest)

        if architecture_key:
            architecture_entry = manifest["architecture"].get(architecture_key)
            if isinstance(architecture_entry, dict):
                architecture_entry["url"] = download_url
                architecture_entry["hash"] = f"sha256:{hash_value}"
                # Top-level url/hash go stale when an architecture block carries
                # the real metadata (see the veracrypt incident) - drop them.
                manifest.pop("url", None)
                manifest.pop("hash", None)
                return

        manifest["url"] = download_url
        manifest["hash"] = f"sha256:{hash_value}"

    @staticmethod
    def _refresh_extract_dir(
        manifest: Dict[str, Any], *, version: str, previous_version: Optional[str]
    ) -> None:
        """Keep a versioned extract_dir in sync across updates (ripgrep-all class).

        Upstream archives often unpack into a folder named after the release;
        when the version changes, rewrite the embedded version so installs do
        not break (the corecycler/ungoogled-chromium incident class).
        """
        if not previous_version or previous_version == version:
            return
        extract_dir = manifest.get("extract_dir")
        if not isinstance(extract_dir, str) or not extract_dir:
            return
        if previous_version in extract_dir:
            manifest["extract_dir"] = extract_dir.replace(previous_version, version)

    def apply_architecture_templates(
        self, manifest: Dict[str, Any], *, version: str, version_info: Dict[str, Any]
    ) -> bool:
        """Build per-architecture url/hash entries from architecture_templates.

        Every architecture URL is hashed individually (the GitHub digest
        shortcut in VersionDetector applies). On success the whole
        ``architecture`` block is replaced and stale top-level ``url``/``hash``
        fields are removed — they would otherwise keep pointing at the old
        single-architecture artifact. Returns False (without touching the
        manifest) when any arch hash cannot be computed.
        """
        templates = self.config.architecture_templates or {}
        match_groups = version_info.get("match_groups") or {}
        architecture: Dict[str, Any] = {}
        for arch, template in templates.items():
            download_url = self.detector.construct_download_url(template, version, match_groups)
            hash_value = self.detector.calculate_hash(download_url)
            if not hash_value:
                self.log(f"❌ Failed to hash {self.config.name} {arch} asset: {download_url}")
                self.emit_result(updated=False, version=version, error="arch_hash_failed")
                return False
            architecture[arch] = {"url": download_url, "hash": f"sha256:{hash_value}"}
        manifest["architecture"] = architecture
        manifest.pop("url", None)
        manifest.pop("hash", None)
        manifest["version"] = version
        return True

    def _stored_manifest_hash(self, manifest: Dict[str, Any]) -> Optional[str]:
        """Return the hash recorded in the manifest (arch block or top level)."""
        architecture_key = self.select_architecture_key(manifest)
        if architecture_key:
            entry = manifest["architecture"].get(architecture_key)
            if isinstance(entry, dict) and entry.get("hash"):
                return str(entry["hash"])
        top_level = manifest.get("hash")
        if top_level:
            return str(top_level)
        return None

    def _upstream_hash_drift(
        self, manifest: Dict[str, Any], version_info: Dict[str, Any]
    ) -> Optional[str]:
        """Detect an upstream re-release: same version, different sha256.

        Cheap by design: only the GitHub release-digest shortcut is consulted
        (no download happens). Returns the current upstream hex digest when it
        differs from the manifest's stored hash, None otherwise — including
        for non-GitHub URLs, API failures, or a missing stored hash. Opt out
        via SKIP_HASH_DRIFT=1.
        """
        if os.environ.get("SKIP_HASH_DRIFT") == "1":
            return None
        download_url = str(version_info.get("download_url") or "")
        clean_url = download_url.split("#", 1)[0].split("?", 1)[0]
        upstream = self.detector._try_github_release_digest(clean_url)
        if not upstream:
            return None
        stored = self._stored_manifest_hash(manifest)
        if not stored:
            return None
        stored_hex = re.sub(r"^sha256:", "", stored.strip(), flags=re.IGNORECASE).lower()
        if upstream.lower() == stored_hex:
            return None
        return upstream

    def update(self, version_info: Optional[Dict[str, Any]] = None) -> bool:
        """Fetch version metadata and update the manifest when required."""
        self.log(f"🔄 Updating {self.config.name}...")

        manifest = self.load_manifest()
        if manifest is None:
            return False
        current_version = str(manifest.get("version", ""))

        if version_info is None:
            # Pass the manifest version so an unchanged release skips the
            # download/hash entirely; forced updates still recompute everything.
            version_info = get_version_info(
                self.config, current_version=None if self.force else current_version
            )

        if not version_info:
            self.log(f"❌ Failed to get version info for {self.config.name}")
            self.emit_result(updated=False, error="version_info_unavailable")
            return False

        # Multi-architecture manifests without per-architecture templates need
        # per-arch URLs/hashes, which a single download template cannot produce
        # — updating only the preferred arch key would leave the other entries
        # stale (see bucket/widevinecdm.json history). When architecture_templates
        # is set, ManifestUpdater rewrites every entry itself, so >1 entries are
        # the supported case. Refuse rather than silently corrupt the manifest.
        architecture = manifest.get("architecture")
        if (
            isinstance(architecture, dict)
            and len(architecture) > 1
            and self.config.architecture_templates is None
        ):
            self.log(
                f"❌ {self.config.name} has multiple architecture entries; "
                "ManifestUpdater supports a single entry — use a package-specific updater"
            )
            self.emit_result(updated=False, error="multi_arch_requires_custom_updater")
            return False

        version = version_info["version"]
        revision = False
        upstream_hash: Optional[str] = None
        if current_version == version and not self.force:
            upstream_hash = self._upstream_hash_drift(manifest, version_info)
            if upstream_hash is None:
                self.log(f"✅ {self.config.name} is already up to date (v{version})")
                self.emit_result(updated=False, version=version)
                return True
            revision = True
            self.log(
                f"🔄 Upstream re-released {self.config.name} v{version} "
                "with a new build - refreshing"
            )

        if current_version == version and self.force:
            self.log(f"🔄 Forcing update of {self.config.name} (v{version})...")

        try:
            if self.config.architecture_templates:
                if not self.apply_architecture_templates(
                    manifest, version=version, version_info=version_info
                ):
                    return False
            else:
                hash_value = version_info["hash"]
                if hash_value is None:
                    # Same-version build refresh: the upstream digest shortcut
                    # already told us the current hash, so reuse it instead of
                    # downloading the artifact again.
                    hash_value = upstream_hash
                self.apply_download_metadata(
                    manifest,
                    version=version,
                    download_url=version_info["download_url"],
                    hash_value=hash_value,
                    previous_version=current_version,
                )
        except Exception as error:
            self.log(f"❌ Error updating manifest content: {error}")
            self.emit_result(updated=False, version=version, error="manifest_update_failed")
            return False

        return self.save_manifest(manifest, version, current_version, revision=revision)
