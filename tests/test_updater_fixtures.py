"""Recorded-response tests for the GitHub-dependent updater framework paths.

These tests replay real (public) GitHub API responses captured under
tests/fixtures/github/ through the actual framework code used by
scripts/update-ripgrep-all.py and scripts/update-thorium-avx2.py, so the
asset gate and digest parsing stay testable without network access.
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add scripts to path
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.append(str(scripts_dir))

from version_detector import SoftwareVersionConfig, VersionDetector, get_version_info

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "github"

RIPGREP_ALL_RELEASES = "releases-phiresky-ripgrep-all.json"
RIPGREP_ALL_V0109 = "release-phiresky-ripgrep-all-v0.10.9.json"
THORIUM_RELEASES = "releases-gz83-thorium.json"
THORIUM_M152 = "release-gz83-thorium-M152.0.7977.55.json"

RIPGREP_ALL_API = "https://api.github.com/repos/phiresky/ripgrep-all/releases"
RIPGREP_ALL_TAG_API = "https://api.github.com/repos/phiresky/ripgrep-all/releases/tags/v0.10.9"
THORIUM_API = "https://api.github.com/repos/gz83/thorium/releases"
THORIUM_TAG_API = "https://api.github.com/repos/gz83/thorium/releases/tags/M152.0.7977.55"

RIPGREP_ALL_DOWNLOAD = (
    "https://github.com/phiresky/ripgrep-all/releases/download/"
    "v0.10.9/ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"
)
THORIUM_DOWNLOAD = (
    "https://github.com/gz83/thorium/releases/download/"
    "M152.0.7977.55/Thorium_AVX2_152.0.7977.55.zip"
)
THORIUM_EXPECTED_SHA256 = "d1311e8b980082e93b1cc574cc88d518fef4cc9f1adb67d49e669402c06f8364"

# Mirrors scripts/update-ripgrep-all.py
RIPGREP_ALL_CONFIG = SoftwareVersionConfig(
    name="ripgrep-all",
    homepage="https://github.com/phiresky/ripgrep-all/releases",
    version_patterns=[r"releases/tag/v([\d.]+)"],
    download_url_template=(
        "https://github.com/phiresky/ripgrep-all/releases/download/"
        "v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
    ),
    description="Ripgrep-All - Search in PDFs, e-books, Office docs, archives, and media",
    license="AGPL-3.0-or-later",
    require_release_asset=True,
)

# Mirrors scripts/update-thorium-avx2.py
THORIUM_CONFIG = SoftwareVersionConfig(
    name="thorium-avx2",
    homepage="https://github.com/gz83/thorium/releases",
    version_patterns=[r"releases/tag/M([\d.]+)"],
    download_url_template=(
        "https://github.com/gz83/thorium/releases/download/M$version/Thorium_AVX2_$version.zip"
    ),
    description="Thorium AVX2 - Chromium fork",
    license="BSD-3-Clause",
    require_release_asset=True,
)


def _load_fixture(name):
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class _FixtureResponse:
    """Minimal stand-in for a requests.Response backed by fixture data."""

    def __init__(self, data=None, content=b""):
        self._data = data
        self._content = content
        self.status_code = 200
        self.headers = {"Content-Length": str(len(content))}

    def raise_for_status(self):
        return None

    def json(self):
        return self._data

    def iter_content(self, chunk_size=8192):
        yield self._content


class _FixtureSession:
    """Serves recorded API fixtures; download URLs get deterministic fake bytes."""

    def __init__(self, routes, file_bytes=b""):
        self.routes = routes
        self.file_bytes = file_bytes
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(url)
        if url in self.routes:
            return _FixtureResponse(data=_load_fixture(self.routes[url]))
        return _FixtureResponse(content=self.file_bytes)


class TestRipgrepAllFixtures(unittest.TestCase):
    """Replay the recorded phiresky/ripgrep-all responses through the asset gate."""

    def setUp(self):
        self.releases = _load_fixture(RIPGREP_ALL_RELEASES)
        newest = self.releases[0]
        self.assertEqual(newest["tag_name"], "v0.10.10")
        # The real v0.10.10 release ships no Windows ZIP: the gate must skip it.
        windows_zip = "ripgrep_all-v0.10.10-x86_64-pc-windows-msvc.zip"
        self.assertNotIn(windows_zip, [a["name"] for a in newest["assets"]])

    def _session(self, file_bytes=b""):
        return _FixtureSession(
            routes={RIPGREP_ALL_API: RIPGREP_ALL_RELEASES, RIPGREP_ALL_TAG_API: RIPGREP_ALL_V0109},
            file_bytes=file_bytes,
        )

    def test_asset_gate_skips_assetless_newer_release(self):
        file_bytes = b"fake ripgrep-all zip bytes"
        session = self._session(file_bytes=file_bytes)
        with patch("version_detector.get_session", return_value=session), patch.object(
            VersionDetector, "validate_url", return_value=True
        ):
            info = get_version_info(RIPGREP_ALL_CONFIG, current_version="0.10.8")

        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.10.9")
        self.assertEqual(info["download_url"], RIPGREP_ALL_DOWNLOAD)
        # v0.10.10's asset list has no sha256 digest, so the framework falls
        # back to hashing the downloaded bytes.
        self.assertEqual(info["hash"], hashlib.sha256(file_bytes).hexdigest())
        self.assertEqual(session.requests[0], RIPGREP_ALL_API)

    def test_digest_absent_in_recorded_release(self):
        # The recorded v0.10.9 release metadata carries no digest for the
        # Windows asset, so the GitHub digest shortcut must return None.
        session = self._session()
        with patch("version_detector.get_session", return_value=session):
            detector = VersionDetector()
        self.assertIsNone(detector._try_github_release_digest(RIPGREP_ALL_DOWNLOAD))
        self.assertIn(RIPGREP_ALL_TAG_API, session.requests)


class TestThoriumFixtures(unittest.TestCase):
    """Replay the recorded gz83/thorium responses through the asset gate."""

    def setUp(self):
        self.releases = _load_fixture(THORIUM_RELEASES)
        self.assertEqual(self.releases[0]["tag_name"], "M152.0.7977.55")
        self.assertTrue(any(r["prerelease"] for r in self.releases))

    def _session(self, file_bytes=b""):
        return _FixtureSession(
            routes={THORIUM_API: THORIUM_RELEASES, THORIUM_TAG_API: THORIUM_M152},
            file_bytes=file_bytes,
        )

    def test_asset_gate_selects_current_manifest_version_with_digest(self):
        session = self._session()
        with patch("version_detector.get_session", return_value=session), patch.object(
            VersionDetector, "validate_url", return_value=True
        ) as mock_validate:
            info = get_version_info(THORIUM_CONFIG, current_version="152.0.7977.54")

        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "152.0.7977.55")
        self.assertEqual(info["download_url"], THORIUM_DOWNLOAD)
        # The recorded release publishes the asset digest; it must be used
        # directly instead of downloading the ZIP.
        self.assertEqual(info["hash"], THORIUM_EXPECTED_SHA256)
        mock_validate.assert_not_called()
        self.assertIn(THORIUM_TAG_API, session.requests)

    def test_unchanged_manifest_version_skips_hash(self):
        session = self._session()
        with patch("version_detector.get_session", return_value=session), patch.object(
            VersionDetector, "calculate_hash", side_effect=AssertionError("must not hash")
        ):
            info = get_version_info(THORIUM_CONFIG, current_version="152.0.7977.55")

        self.assertEqual(
            info,
            {
                "version": "152.0.7977.55",
                "download_url": THORIUM_DOWNLOAD,
                "hash": None,
            },
        )

    def test_tag_fixture_asset_carries_expected_sha256(self):
        release = _load_fixture(THORIUM_M152)
        asset = next(a for a in release["assets"] if a["name"] == "Thorium_AVX2_152.0.7977.55.zip")
        self.assertEqual(asset["digest"], "sha256:" + THORIUM_EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
