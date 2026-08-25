#!/usr/bin/env python3
"""Shared helpers for updating Scoop manifests from version metadata."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from version_detector import SoftwareVersionConfig, get_version_info


class ManifestUpdater:
    """Update a Scoop manifest using ``version_detector`` results."""

    def __init__(
        self,
        config: SoftwareVersionConfig,
        bucket_dir: Path,
        manifest_filename: Optional[str] = None,
    ) -> None:
        self.config = config
        self.bucket_dir = bucket_dir
        self.manifest_filename = manifest_filename or f"{config.name}.json"
        self.manifest_path = bucket_dir / self.manifest_filename
        self.structured_only = os.environ.get("STRUCTURED_ONLY") == "1"

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
    ) -> None:
        """Emit the single-line JSON object consumed by the orchestrator."""
        payload: Dict[str, Any] = {"updated": updated, "name": self.config.name}
        if version:
            payload["version"] = version
        if error:
            payload["error"] = error
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

    def save_manifest(self, manifest: Dict[str, Any], version: str, previous_version: str) -> bool:
        """Write the updated manifest back to disk."""
        try:
            with self.manifest_path.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as error:
            self.log(f"❌ Failed to save manifest: {error}")
            self.emit_result(updated=False, version=version, error="save_failed")
            return False

        self.log(f"✅ Updated {self.config.name}: {previous_version} → {version}")
        self.emit_result(updated=True, version=version)
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
    ) -> None:
        """Update version, url, and hash fields in-place."""
        manifest["version"] = version
        architecture_key = self.select_architecture_key(manifest)

        if architecture_key:
            architecture_entry = manifest["architecture"].get(architecture_key)
            if isinstance(architecture_entry, dict):
                architecture_entry["url"] = download_url
                architecture_entry["hash"] = f"sha256:{hash_value}"
                return

        manifest["url"] = download_url
        manifest["hash"] = f"sha256:{hash_value}"

    def update(self) -> bool:
        """Fetch version metadata and update the manifest when required."""
        self.log(f"🔄 Updating {self.config.name}...")

        version_info = get_version_info(self.config)
        if not version_info:
            self.log(f"❌ Failed to get version info for {self.config.name}")
            self.emit_result(updated=False, error="version_info_unavailable")
            return False

        manifest = self.load_manifest()
        if manifest is None:
            return False

        version = version_info["version"]
        current_version = str(manifest.get("version", ""))
        if current_version == version:
            self.log(f"✅ {self.config.name} is already up to date (v{version})")
            self.emit_result(updated=False, version=version)
            return True

        try:
            self.apply_download_metadata(
                manifest,
                version=version,
                download_url=version_info["download_url"],
                hash_value=version_info["hash"],
            )
        except Exception as error:
            self.log(f"❌ Error updating manifest content: {error}")
            self.emit_result(updated=False, version=version, error="manifest_update_failed")
            return False

        return self.save_manifest(manifest, version, current_version)
