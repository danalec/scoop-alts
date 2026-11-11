"""Tests for the bespoke ghydramcp updater.

The package ships three release assets (two Ghidra bundles plus the stdio
bridge) as top-level ``url``/``hash`` arrays, and Scoop pairs ``extract_to``
with the archives by archive index. A position-dependent selection would
silently pick a ``Ghydra-Complete-...`` bundle or the bridge script, so these
tests pin the name-based selection, the digest handling, the array alignment
and the idempotency contract. Everything here runs offline: the release API and
the hash helper are replaced by a fake detector.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

VERSION = "3.2.0"
VERSION_STAMPS = {"ghidra11.4.3": "20261111-183108", "ghidra12.2": "20261111-183111"}
DIGESTS = {
    "ghidra11.4.3": "1" * 64,
    "ghidra12.2": "2" * 64,
    "bridge": "3" * 64,
}


def load_updater():
    """Import the hyphenated updater, which is not importable by name."""
    spec = importlib.util.spec_from_file_location(
        "update_ghydramcp", SCRIPTS_DIR / "update-ghydramcp.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def updater_module():
    return load_updater()


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    """A clean bucket directory with forced mode disabled."""
    monkeypatch.setattr(sys, "argv", ["update-ghydramcp.py"])
    monkeypatch.delenv("FORCE", raising=False)
    monkeypatch.delenv("SCOOP_FORCE", raising=False)
    return tmp_path


def _asset_name(version, variant):
    return f"Ghydra-v{version}-{VERSION_STAMPS[variant]}-{variant}.zip"


def build_release(version=VERSION, *, reverse=False, drop=(), strip_digest=(), digests=None):
    """Return a release payload shaped like the GitHub API's.

    The default order mirrors the real API: the bridge and the two Complete
    bundles come before the plain bundles, so an implementation that selected
    assets by position would pick the wrong files.
    """
    expected = {**DIGESTS, **(digests or {})}
    base = f"https://github.com/danalec/GhydraMCP/releases/download/v{version}"
    rows = [
        ("bridge", "bridge_mcp_hydra.py"),
        (
            "complete11",
            f"Ghydra-Complete-v{version}-{VERSION_STAMPS['ghidra11.4.3']}-ghidra11.4.3.zip",
        ),
        (
            "complete12",
            f"Ghydra-Complete-v{version}-{VERSION_STAMPS['ghidra12.2']}-ghidra12.2.zip",
        ),
        ("ghidra11.4.3", _asset_name(version, "ghidra11.4.3")),
        ("ghidra12.2", _asset_name(version, "ghidra12.2")),
    ]
    assets = []
    for key, name in rows:
        if key in drop:
            continue
        asset = {"name": name, "browser_download_url": f"{base}/{name}"}
        if key in expected and key not in strip_digest:
            asset["digest"] = f"sha256:{expected[key]}"
        assets.append(asset)
    if reverse:
        assets.reverse()
    return {"tag_name": f"v{version}", "assets": assets}


def build_manifest(version=VERSION, *, digests=None):
    """Return a manifest with every key the updater must preserve."""
    expected = {**DIGESTS, **(digests or {})}
    base = f"https://github.com/danalec/GhydraMCP/releases/download/v{version}"
    return {
        "version": version,
        "description": "Ghidra extension and stdio MCP bridge.",
        "homepage": "https://github.com/danalec/GhydraMCP",
        "license": "Apache-2.0",
        "changelog": "https://github.com/danalec/GhydraMCP/releases",
        "url": [
            f"{base}/{_asset_name(version, 'ghidra11.4.3')}#/ghidra11.4.3.zip",
            f"{base}/{_asset_name(version, 'ghidra12.2')}#/ghidra12.2.zip",
            f"{base}/bridge_mcp_hydra.py",
        ],
        "hash": [
            f"sha256:{expected['ghidra11.4.3']}",
            f"sha256:{expected['ghidra12.2']}",
            f"sha256:{expected['bridge']}",
        ],
        "extract_to": ["ghidra11.4.3", "ghidra12.2"],
        "env_set": {"GHYDRAMCP_HOME": "$dir"},
        "checkver": {
            "url": "https://api.github.com/repos/danalec/GhydraMCP/releases/latest",
            "regex": '"tag_name":\\s*"v?([\\d.]+)"',
        },
        "notes": ["Ghidra loads exactly one extension build per version line."],
        "post_install": ["Write-Host 'ghydramcp'"],
    }


class FakeDetector:
    """Detector stand-in: a canned release payload and canned download hashes."""

    def __init__(self, release=None, hashes=None):
        self.release = release
        self.hashes = dict(hashes or {})
        self.requested_urls = []
        self.hash_calls = []

    def _cached_api_get(self, url, params=None, headers=None):
        self.requested_urls.append(url)
        return self.release

    def calculate_hash(self, url):
        self.hash_calls.append(url)
        return self.hashes.get(url)


def make_updater(module, bucket_dir, release=None, *, force=False, hashes=None):
    updater = module.GhydraMcpManifestUpdater(module.build_config(), bucket_dir, force=force)
    updater.detector = FakeDetector(release, hashes)
    return updater


def write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_manifest(path):
    return json.loads(path.read_text(encoding="utf-8"))


def last_json_line(output):
    lines = [line for line in output.splitlines() if line.strip()]
    return json.loads(lines[-1])


# ------------------------------------------------------------------- pure helpers


def test_parse_release_version_strips_the_v_prefix(updater_module):
    assert updater_module.parse_release_version({"tag_name": "v3.2.0"}) == "3.2.0"


def test_parse_release_version_accepts_an_unprefixed_tag(updater_module):
    assert updater_module.parse_release_version({"tag_name": "3.2.0"}) == "3.2.0"


def test_parse_release_version_rejects_an_unparseable_tag(updater_module):
    assert updater_module.parse_release_version({"tag_name": "nightly"}) is None
    assert updater_module.parse_release_version({}) is None


def test_select_release_assets_picks_the_plain_bundles_by_variant(updater_module):
    release = build_release()

    selection = updater_module.select_release_assets(release)

    assert set(selection) == {"ghidra11.4.3", "ghidra12.2", "bridge"}
    assert selection["ghidra11.4.3"]["name"] == _asset_name(VERSION, "ghidra11.4.3")
    assert selection["ghidra12.2"]["name"] == _asset_name(VERSION, "ghidra12.2")
    assert selection["bridge"]["name"] == "bridge_mcp_hydra.py"
    # The plain bundles sit at indices 3 and 4 in the API's order; a positional
    # implementation would have taken the bridge and a Complete bundle instead.
    assert release["assets"][0]["name"] == "bridge_mcp_hydra.py"
    assert "Complete" in release["assets"][1]["name"]


def test_select_release_assets_ignores_asset_order(updater_module):
    forward = updater_module.select_release_assets(build_release())
    backward = updater_module.select_release_assets(build_release(reverse=True))

    assert {key: asset["name"] for key, asset in forward.items()} == {
        key: asset["name"] for key, asset in backward.items()
    }


def test_select_release_assets_reports_a_missing_variant(updater_module):
    selection = updater_module.select_release_assets(build_release(drop={"ghidra12.2"}))

    assert "ghidra12.2" not in selection
    assert "ghidra11.4.3" in selection


def test_asset_sha256_prefers_the_release_digest(updater_module):
    asset = {
        "name": "x.zip",
        "browser_download_url": "https://example/x.zip",
        "digest": f"sha256:{'a' * 64}",
    }
    detector = FakeDetector(hashes={"https://example/x.zip": "b" * 64})

    assert updater_module.asset_sha256(asset, detector) == "a" * 64
    assert detector.hash_calls == []


def test_asset_sha256_falls_back_to_the_hash_helper(updater_module):
    asset = {"name": "x.zip", "browser_download_url": "https://example/x.zip"}
    detector = FakeDetector(hashes={"https://example/x.zip": "b" * 64})

    assert updater_module.asset_sha256(asset, detector) == "b" * 64
    assert detector.hash_calls == ["https://example/x.zip"]


def test_asset_sha256_ignores_a_malformed_digest(updater_module):
    asset = {
        "name": "x.zip",
        "browser_download_url": "https://example/x.zip",
        "digest": "sha256:not-a-digest",
    }
    detector = FakeDetector(hashes={"https://example/x.zip": "b" * 64})

    assert updater_module.asset_sha256(asset, detector) == "b" * 64


# ------------------------------------------------------------------------- update


def test_update_writes_all_three_assets_in_pairing_order(updater_module, bucket):
    write_manifest(bucket / "ghydramcp.json", build_manifest("3.1.1"))
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is True

    manifest = read_manifest(bucket / "ghydramcp.json")
    base = f"https://github.com/danalec/GhydraMCP/releases/download/v{VERSION}"
    assert manifest["version"] == VERSION
    assert manifest["url"] == [
        f"{base}/{_asset_name(VERSION, 'ghidra11.4.3')}#/ghidra11.4.3.zip",
        f"{base}/{_asset_name(VERSION, 'ghidra12.2')}#/ghidra12.2.zip",
        f"{base}/bridge_mcp_hydra.py",
    ]
    assert manifest["hash"] == [
        f"sha256:{DIGESTS['ghidra11.4.3']}",
        f"sha256:{DIGESTS['ghidra12.2']}",
        f"sha256:{DIGESTS['bridge']}",
    ]
    # The two archives are the only extraction targets; the bridge is not.
    assert manifest["extract_to"] == ["ghidra11.4.3", "ghidra12.2"]
    assert len(manifest["url"]) == 3
    assert len(manifest["extract_to"]) == 2
    assert updater.detector.requested_urls == [updater_module.RELEASES_API_URL]


def test_update_preserves_every_other_manifest_key(updater_module, bucket):
    original = build_manifest("3.1.1")
    write_manifest(bucket / "ghydramcp.json", original)
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is True

    updated = read_manifest(bucket / "ghydramcp.json")
    for key in (
        "description",
        "homepage",
        "license",
        "changelog",
        "extract_to",
        "env_set",
        "checkver",
        "notes",
        "post_install",
    ):
        assert updated[key] == original[key], f"{key} was mutated"


def test_update_is_idempotent_at_the_current_version(updater_module, bucket, capsys):
    path = write_manifest(bucket / "ghydramcp.json", build_manifest())
    before = path.read_bytes()
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is True

    assert path.read_bytes() == before
    assert updater.detector.hash_calls == []
    payload = last_json_line(capsys.readouterr().out)
    assert payload == {"updated": False, "name": "ghydramcp", "version": VERSION}


def test_update_refreshes_a_same_version_rerelease(updater_module, bucket, capsys):
    write_manifest(bucket / "ghydramcp.json", build_manifest(digests={"ghidra12.2": "9" * 64}))
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is True

    manifest = read_manifest(bucket / "ghydramcp.json")
    assert manifest["hash"][1] == f"sha256:{DIGESTS['ghidra12.2']}"
    payload = last_json_line(capsys.readouterr().out)
    assert payload["updated"] is True
    assert payload["revision"] is True


def test_update_force_rewrites_even_when_current(updater_module, bucket, capsys):
    path = write_manifest(bucket / "ghydramcp.json", build_manifest())
    before = path.read_bytes()
    updater = make_updater(updater_module, bucket, build_release(), force=True)

    assert updater.update() is True

    assert path.read_bytes() == before
    payload = last_json_line(capsys.readouterr().out)
    assert payload["updated"] is True
    assert payload["forced"] is True


def test_update_uses_the_hash_helper_when_a_digest_is_missing(updater_module, bucket):
    release = build_release(strip_digest={"bridge"})
    bridge_url = (
        f"https://github.com/danalec/GhydraMCP/releases/download/v{VERSION}/bridge_mcp_hydra.py"
    )
    write_manifest(bucket / "ghydramcp.json", build_manifest("3.1.1"))
    updater = make_updater(updater_module, bucket, release, hashes={bridge_url: DIGESTS["bridge"]})

    assert updater.update() is True

    manifest = read_manifest(bucket / "ghydramcp.json")
    assert manifest["hash"][2] == f"sha256:{DIGESTS['bridge']}"
    assert updater.detector.hash_calls == [bridge_url]


def test_update_scopes_the_bridge_download_to_its_own_hash(updater_module, bucket):
    # The zips carry API digests, so only the bridge may be downloaded; a
    # regression that falls back for every asset would show up here.
    release = build_release()
    updater = make_updater(updater_module, bucket, release)
    write_manifest(bucket / "ghydramcp.json", build_manifest("3.1.1"))

    assert updater.update() is True
    assert updater.detector.hash_calls == []


# ------------------------------------------------------------------------ failures


def test_update_fails_when_a_ghidra_variant_is_missing(updater_module, bucket, capsys):
    original = build_manifest()
    write_manifest(bucket / "ghydramcp.json", original)
    updater = make_updater(updater_module, bucket, build_release(drop={"ghidra12.2"}))

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["updated"] is False
    assert payload["error"] == "release_asset_missing"
    assert read_manifest(bucket / "ghydramcp.json") == original


def test_update_fails_when_the_bridge_asset_is_missing(updater_module, bucket, capsys):
    original = build_manifest()
    write_manifest(bucket / "ghydramcp.json", original)
    updater = make_updater(updater_module, bucket, build_release(drop={"bridge"}))

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["error"] == "release_asset_missing"
    assert read_manifest(bucket / "ghydramcp.json") == original


def test_update_fails_when_the_release_metadata_is_unavailable(updater_module, bucket, capsys):
    original = build_manifest()
    write_manifest(bucket / "ghydramcp.json", original)
    updater = make_updater(updater_module, bucket, release=None)

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["error"] == "release_metadata_unavailable"
    assert read_manifest(bucket / "ghydramcp.json") == original


def test_update_fails_when_the_release_tag_is_unparseable(updater_module, bucket, capsys):
    original = build_manifest()
    write_manifest(bucket / "ghydramcp.json", original)
    updater = make_updater(updater_module, bucket, {"tag_name": "nightly", "assets": []})

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["error"] == "release_tag_unparseable"
    assert read_manifest(bucket / "ghydramcp.json") == original


def test_update_fails_when_no_hash_can_be_resolved(updater_module, bucket, capsys):
    original = build_manifest("3.1.1")
    write_manifest(bucket / "ghydramcp.json", original)
    # The bridge digest is stripped and the fake helper has no hash for it.
    updater = make_updater(updater_module, bucket, build_release(strip_digest={"bridge"}))

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["error"] == "hash_unavailable"
    assert read_manifest(bucket / "ghydramcp.json") == original


def test_update_fails_when_the_manifest_is_missing(updater_module, bucket, capsys):
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is False

    payload = last_json_line(capsys.readouterr().out)
    assert payload["updated"] is False
    assert payload["error"] == "manifest_not_found"


# --------------------------------------------------------------- output contract


def test_update_emits_a_single_structured_line(updater_module, bucket, monkeypatch, capsys):
    monkeypatch.setenv("STRUCTURED_ONLY", "1")
    write_manifest(bucket / "ghydramcp.json", build_manifest("3.1.1"))
    updater = make_updater(updater_module, bucket, build_release())

    assert updater.update() is True

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected a single structured line, got {lines!r}"
    payload = json.loads(lines[0])
    assert payload["updated"] is True
    assert payload["name"] == "ghydramcp"
    assert payload["version"] == VERSION


def test_main_exits_non_zero_when_the_update_fails(updater_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["update-ghydramcp.py"])
    monkeypatch.setattr(updater_module, "update_manifest", lambda force=False: False)

    with pytest.raises(SystemExit) as exit_info:
        updater_module.main()

    assert exit_info.value.code == 1


def test_main_forwards_the_manifest_to_the_auto_commit_helper(updater_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["update-ghydramcp.py"])
    monkeypatch.delenv("AUTO_COMMIT", raising=False)
    monkeypatch.delenv("SCOOP_AUTO_COMMIT", raising=False)
    calls = []
    monkeypatch.setattr(updater_module, "update_manifest", lambda force=False: True)
    monkeypatch.setattr(updater_module, "maybe_auto_commit", lambda *args: calls.append(args))

    updater_module.main()

    assert len(calls) == 1
    assert calls[0][0] == "ghydramcp"


# ------------------------------------------------------------------ registration


def test_providers_registers_the_updater_as_github():
    providers = json.loads((SCRIPTS_DIR / "providers.json").read_text(encoding="utf-8"))

    assert providers["update-ghydramcp.py"] == "github"
