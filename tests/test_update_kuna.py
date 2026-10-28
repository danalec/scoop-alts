"""Tests for scripts/update-kuna.py — the two-asset manifest updater.

bucket/kuna.json is the only manifest in the bucket whose ``url``/``hash`` stay
arrays: upstream ships the Windows binaries and the Ghidra processor specs as
two separate release assets, and ``env_set.KUNA_SPECS`` points at the specs tree
that the second archive extracts. The base ``ManifestUpdater`` collapses those
to single strings, which would silently drop the specs archive on every version
bump.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATER_PATH = REPO_ROOT / "scripts" / "update-kuna.py"
WINDOWS_HASH = "a" * 64
SPECS_HASH = "b" * 64


def load_updater():
    """Import ``update-kuna.py``, whose hyphenated name is not importable."""
    spec = importlib.util.spec_from_file_location("update_kuna", UPDATER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def kuna():
    return load_updater()


def make_updater(kuna, tmp_path, force=False):
    config = SoftwareVersionConfig(
        name="kuna",
        homepage=kuna.HOMEPAGE_URL,
        version_patterns=[r'"tag_name":\s*"v?([\d.]+)"'],
        download_url_template=kuna.WINDOWS_URL_TEMPLATE,
        description="d",
        license="Apache-2.0",
    )
    return kuna.KunaManifestUpdater(config, tmp_path, force=force)


def read_manifest(updater):
    return json.loads(updater.manifest_path.read_text(encoding="utf-8"))


def test_kuna_updater_subclasses_manifest_updater(kuna):
    assert issubclass(kuna.KunaManifestUpdater, ManifestUpdater)


def test_stored_manifest_hash_returns_first_list_element(kuna, tmp_path):
    # The base implementation stringifies the whole list, so an array-shaped
    # manifest would never match the upstream digest and every run would look
    # like a re-release.
    updater = make_updater(kuna, tmp_path)
    manifest = {
        "version": "1.785",
        "architecture": {"64bit": {"url": [], "hash": [f"sha256:{WINDOWS_HASH}"]}},
    }
    assert updater._stored_manifest_hash(manifest) == f"sha256:{WINDOWS_HASH}"


def test_stored_manifest_hash_returns_string_hash_unchanged(kuna, tmp_path):
    updater = make_updater(kuna, tmp_path)
    manifest = {"version": "1.0", "hash": f"sha256:{WINDOWS_HASH}"}
    assert updater._stored_manifest_hash(manifest) == f"sha256:{WINDOWS_HASH}"


def test_stored_manifest_hash_none_when_absent(kuna, tmp_path):
    updater = make_updater(kuna, tmp_path)
    assert updater._stored_manifest_hash({"version": "1.0"}) is None


def test_apply_download_metadata_writes_both_assets(kuna, tmp_path):
    updater = make_updater(kuna, tmp_path)
    updater.detector.calculate_hash = lambda url: SPECS_HASH

    manifest = {"version": "1.784", "architecture": {"64bit": {}}}
    updater.apply_download_metadata(
        manifest,
        version="1.785",
        download_url=kuna.WINDOWS_URL_TEMPLATE.replace("$version", "1.785"),
        hash_value=WINDOWS_HASH,
        previous_version="1.784",
    )

    entry = manifest["architecture"]["64bit"]
    assert manifest["version"] == "1.785"
    assert entry["url"] == [
        "https://github.com/Noelo-Lab/kuna/releases/download/v1.785/"
        "kuna-v1.785-windows-x86_64.zip",
        "https://github.com/Noelo-Lab/kuna/releases/download/v1.785/kuna-v1.785-specs.tar.gz",
    ]
    assert entry["hash"] == [f"sha256:{WINDOWS_HASH}", f"sha256:{SPECS_HASH}"]


def test_apply_download_metadata_drops_stale_top_level_pair(kuna, tmp_path):
    # A stale top-level url/hash silently breaks installs once an architecture
    # block carries the real metadata (the veracrypt incident).
    updater = make_updater(kuna, tmp_path)
    updater.detector.calculate_hash = lambda url: SPECS_HASH

    manifest = {
        "version": "1.784",
        "url": "https://example.com/old.zip",
        "hash": f"sha256:{WINDOWS_HASH}",
        "architecture": {"64bit": {}},
    }
    updater.apply_download_metadata(
        manifest,
        version="1.785",
        download_url="https://example.com/new.zip",
        hash_value=WINDOWS_HASH,
    )

    assert "url" not in manifest
    assert "hash" not in manifest


def test_apply_download_metadata_refreshes_versioned_extract_dir(kuna, tmp_path):
    updater = make_updater(kuna, tmp_path)
    updater.detector.calculate_hash = lambda url: SPECS_HASH

    manifest = {
        "version": "1.784",
        "extract_dir": "kuna-v1.784-windows-x86_64",
        "architecture": {"64bit": {}},
        "autoupdate": {"extract_dir": "kuna-v$version-windows-x86_64"},
    }
    updater.apply_download_metadata(
        manifest,
        version="1.785",
        download_url="https://example.com/new.zip",
        hash_value=WINDOWS_HASH,
        previous_version="1.784",
    )

    assert manifest["extract_dir"] == "kuna-v1.785-windows-x86_64"


def test_apply_download_metadata_raises_when_specs_hash_unavailable(kuna, tmp_path):
    # Guarding the second asset matters: shipping a manifest with a stale or
    # missing specs digest would break KUNA_SPECS at install time.
    updater = make_updater(kuna, tmp_path)
    updater.detector.calculate_hash = lambda url: None

    manifest = {"version": "1.785", "architecture": {"64bit": {}}}
    with pytest.raises(RuntimeError, match="could not compute sha256"):
        updater.apply_download_metadata(
            manifest,
            version="1.785",
            download_url="https://example.com/new.zip",
            hash_value=WINDOWS_HASH,
        )


def test_shipped_manifest_keeps_asset_order(kuna):
    """The committed manifest must stay in the order the updater writes.

    Scoop pairs ``extract_dir`` with archives by index, so the Windows archive
    has to stay first or extract_dir would bind to the specs tarball. The
    version is read from the manifest instead of being pinned: the order is
    the invariant, and a hardcoded version would break the test on every
    legitimate release.
    """
    manifest = json.loads((REPO_ROOT / "bucket" / "kuna.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    urls = manifest["architecture"]["64bit"]["url"]
    hashes = manifest["architecture"]["64bit"]["hash"]
    assert len(urls) == len(hashes) == 2
    assert urls[0].endswith(f"kuna-v{version}-windows-x86_64.zip")
    assert urls[1].endswith(f"kuna-v{version}-specs.tar.gz")
    assert manifest["extract_dir"] == f"kuna-v{version}-windows-x86_64"
    assert manifest["env_set"]["KUNA_SPECS"] == "$dir\\specs"
