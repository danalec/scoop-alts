"""Tests for the five bespoke updaters that had no direct coverage.

The registry-driven runner is exercised elsewhere; these packages kept their own
``update-<pkg>.py`` because a ``SoftwareVersionConfig`` entry cannot express what
they need. That makes them the highest-risk code in the repo: a wrong mutation
corrupts a shipped manifest silently, and a wrong classification during the
registry refactor would have dropped ``widevinecdm``'s named match groups --
caught only by an AST diff, never by a test. Everything here runs without
network access; the detector and download helpers are replaced by fakes.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def load_updater(module_name):
    """Import a hyphenated ``update-<pkg>.py``, which is not importable by name."""
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def read_manifest(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- agy


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeRequests:
    """Serves the two per-architecture upstream manifests agy consumes."""

    def __init__(self, amd64, arm64):
        self._amd64 = amd64
        self._arm64 = arm64

    def get(self, url, **kwargs):
        return _Response(self._amd64 if "amd64" in url else self._arm64)


AGY_HASHES = {"https://dl/amd64.exe": "a" * 64, "https://dl/arm64.exe": "b" * 64}


@pytest.fixture
def agy(tmp_path):
    module = load_updater("update-agy")
    module.BUCKET_FILE = tmp_path / "agy.json"
    module.calculate_sha256 = lambda url: AGY_HASHES[url]
    return module


def _wire_agy(agy, version="2.0.0"):
    agy.requests = _FakeRequests(
        {"version": version, "url": "https://dl/amd64.exe"},
        {"url": "https://dl/arm64.exe"},
    )


def test_agy_update_writes_architecture_block(agy):
    _wire_agy(agy)
    write_manifest(agy.BUCKET_FILE, {"version": "1.0.0"})

    assert agy.update_manifest() is True

    manifest = read_manifest(agy.BUCKET_FILE)
    assert manifest["version"] == "2.0.0"
    assert manifest["architecture"]["64bit"]["url"] == "https://dl/amd64.exe#/agy.exe"
    assert manifest["architecture"]["arm64"]["hash"] == f"sha256:{'b' * 64}"


def test_agy_update_leaves_no_top_level_download_pair(agy):
    # The architecture block is the real download metadata. A top-level pair
    # beside it goes stale independently and scoop serves it as the fallback for
    # any unlisted architecture, so an ARM box can end up on the x64 binary.
    _wire_agy(agy)
    write_manifest(
        agy.BUCKET_FILE,
        {"version": "1.0.0", "url": "https://old/a.exe", "hash": f"sha256:{'0' * 64}"},
    )

    assert agy.update_manifest() is True

    manifest = read_manifest(agy.BUCKET_FILE)
    assert "url" not in manifest
    assert "hash" not in manifest


def test_agy_update_is_a_noop_when_version_matches(agy):
    _wire_agy(agy, version="1.0.0")
    original = {"version": "1.0.0", "description": "keep me"}
    write_manifest(agy.BUCKET_FILE, original)

    # Already current: reports success without rewriting the manifest.
    assert agy.update_manifest() is True
    assert read_manifest(agy.BUCKET_FILE) == original


def test_agy_update_rejects_incomplete_upstream_payload(agy):
    agy.requests = _FakeRequests({"version": "2.0.0"}, {"url": "https://dl/arm64.exe"})
    write_manifest(agy.BUCKET_FILE, {"version": "1.0.0"})

    assert agy.update_manifest() is False


def test_agy_update_fails_when_manifest_missing(agy):
    _wire_agy(agy)
    assert agy.update_manifest() is False


def test_agy_calculate_sha256_is_streamed(monkeypatch):
    module = load_updater("update-agy")
    seen = {}

    class _StreamedResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            seen["chunk_size"] = chunk_size
            return [b"a", b"b"]

    monkeypatch.setattr(
        module, "requests", type("R", (), {"get": lambda self, url, **kw: _StreamedResponse()})()
    )

    digest = module.calculate_sha256("https://dl/x.exe")

    assert seen["chunk_size"] == 65536
    assert digest == __import__("hashlib").sha256(b"ab").hexdigest()


# --------------------------------------------------------------------- widevinecdm


class _VersionResult:
    def __init__(self, version, match_groups):
        self.version = version
        self.match_groups = match_groups


@pytest.fixture
def widevine(monkeypatch):
    module = load_updater("update-widevinecdm")

    captured = {}

    class _Detector:
        def fetch_latest_version(self, url, patterns):
            captured["url"] = url
            captured["patterns"] = patterns
            return _VersionResult("140.0.7339.80", {"arch32": "win32", "arch64": "win64"})

    class _Updater:
        def __init__(self, config, bucket_dir):
            captured["config"] = config

        def log(self, message):
            captured["log"] = message

        def emit_result(self, **kwargs):
            captured["emitted"] = kwargs

        def update(self, version_info=None):
            captured["version_info"] = version_info
            return True

    monkeypatch.setattr(module, "VersionDetector", _Detector)
    monkeypatch.setattr(module, "ManifestUpdater", _Updater)
    return module, captured


def test_widevinecdm_keeps_architecture_templates(widevine):
    # Losing architecture_templates is exactly what a naive registry migration
    # would have done: every architecture url is built from a named match group,
    # so without them both arches collapse onto one template.
    module, captured = widevine

    assert module.update_manifest() is True

    config = captured["config"]
    assert set(config.architecture_templates) == {"64bit", "32bit"}
    assert "$matcharch64" in config.architecture_templates["64bit"]
    assert "$matcharch32" in config.architecture_templates["32bit"]


def test_widevinecdm_forwards_match_groups_to_updater(widevine):
    module, captured = widevine

    module.update_manifest()

    version_info = captured["version_info"]
    assert version_info["version"] == "140.0.7339.80"
    assert version_info["match_groups"] == {"arch32": "win32", "arch64": "win64"}


def test_widevinecdm_fails_when_detection_returns_nothing(widevine, monkeypatch):
    module, captured = widevine

    class _EmptyDetector:
        def fetch_latest_version(self, url, patterns):
            return None

    monkeypatch.setattr(module, "VersionDetector", _EmptyDetector)

    assert module.update_manifest() is False
    assert captured["emitted"]["error"] == "version_info_unavailable"


# ------------------------------------------------------------------------ victoria


@pytest.fixture
def victoria(monkeypatch):
    module = load_updater("update-victoria")
    return module


def _fake_victoria_detector(monkeypatch, module, version):
    class _Result:
        def __init__(self, value):
            self.version = value

    class _Detector:
        def fetch_latest_version(self, url, patterns):
            return _Result(version)

        def calculate_hash(self, url):
            return "c" * 64

    monkeypatch.setattr(module, "VersionDetector", _Detector)


def test_victoria_builds_digit_only_download_url(victoria, monkeypatch):
    # The vendor names the archive with concatenated digits: 5.37 -> Victoria537.
    _fake_victoria_detector(monkeypatch, victoria, "5.37")

    resolved = victoria.get_latest_release_info(victoria.build_config())

    assert resolved["version"] == "5.37"
    assert resolved["download_url"].endswith("Victoria537.zip")
    assert "5.37" not in resolved["download_url"]


def test_victoria_returns_none_when_detection_fails(victoria, monkeypatch):
    class _Detector:
        def fetch_latest_version(self, url, patterns):
            return None

    monkeypatch.setattr(victoria, "VersionDetector", _Detector)

    assert victoria.get_latest_release_info(victoria.build_config()) is None


def test_victoria_version_patterns_cover_vendor_rewording(victoria):
    # Two independent phrasings plus a fallback: the vendor page text has
    # changed before, and a single stale pattern is a silent no-update bug.
    patterns = victoria.build_config().version_patterns

    assert len(patterns) >= 2
    assert any("Victoria" in p for p in patterns)


# ------------------------------------------------------------------ usb-safely-remove


@pytest.fixture
def usb(tmp_path, monkeypatch):
    module = load_updater("update-usb-safely-remove")
    manifest_path = tmp_path / "usb-safely-remove.json"
    module.BUCKET_FILE = manifest_path

    state = {}

    def _get_version_info(config):
        state["config"] = config
        return state.get("result")

    monkeypatch.setattr(module, "get_version_info", _get_version_info)
    return module, state, manifest_path


def test_usb_updater_writes_version_url_and_hash(usb):
    module, state, manifest_path = usb
    write_manifest(manifest_path, {"version": "1.0.0"})
    state["result"] = {
        "version": "2.4.1",
        "download_url": "https://example/startdownload.htm?v=2.4.1",
        "hash": "d" * 64,
    }

    assert module.update_manifest() is True

    manifest = read_manifest(manifest_path)
    assert manifest["version"] == "2.4.1"
    assert manifest["hash"] == f"sha256:{'d' * 64}"


def test_usb_updater_fails_when_version_info_missing(usb):
    module, state, manifest_path = usb
    write_manifest(manifest_path, {"version": "1.0.0"})
    state["result"] = None

    assert module.update_manifest() is False


def test_usb_updater_passes_release_dependent_config(usb):
    # The shared download template carries no version; the version reaches the
    # vendor only through the query string the detector builds. Assert the
    # config survives so a refactor cannot quietly drop the homepage.
    module, state, manifest_path = usb
    write_manifest(manifest_path, {"version": "1.0.0"})
    state["result"] = {"version": "2.4.1", "download_url": "https://x/y", "hash": "e" * 64}

    module.update_manifest()

    config = state["config"]
    assert config.homepage == module.HOMEPAGE_URL
    assert config.version_patterns


# --------------------------------------------------- usb-safely-remove-portable


@pytest.fixture
def usb_portable(tmp_path, monkeypatch):
    module = load_updater("update-usb-safely-remove-portable")
    manifest_path = tmp_path / "usb-safely-remove-portable.json"
    module.BUCKET_FILE = manifest_path

    class _Detector:
        def calculate_hash(self, url):
            return "f" * 64

    monkeypatch.setattr(module, "VersionDetector", _Detector)
    return module, manifest_path


def _redirect_session(location, status=302):
    # Note: the class body cannot read an enclosing-scope name of the same
    # name, hence the `status`/`status_code` split.
    class _Response:
        headers = {"Location": location} if location else {}

        def __init__(self):
            self.status_code = status

        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"http {status}")

    class _Session:
        def get(self, url, **kwargs):
            return _Response()

    return _Session()


def test_usb_portable_parses_version_from_redirect_location(usb_portable, monkeypatch):
    # This updater is bespoke precisely because the vendor serves the asset
    # through a redirect: there is no version in the page to scrape.
    module, _ = usb_portable
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: _redirect_session("https://cdn/usbsafelyremovesetup_6-4-1.zip"),
    )

    resolved = module.get_redirected_download_info()

    assert resolved == {
        "version": "6.4.1",
        "download_url": "https://cdn/usbsafelyremovesetup_6-4-1.zip",
    }


def test_usb_portable_returns_none_without_location(usb_portable, monkeypatch):
    module, _ = usb_portable
    monkeypatch.setattr(module, "get_session", lambda: _redirect_session(""))

    assert module.get_redirected_download_info() is None


def test_usb_portable_returns_none_for_unexpected_asset_name(usb_portable, monkeypatch):
    # A renamed asset must fail loudly instead of writing a version parsed out
    # of a filename that is not the release.
    module, _ = usb_portable
    monkeypatch.setattr(
        module, "get_session", lambda: _redirect_session("https://cdn/SomeOtherSetup.zip")
    )

    assert module.get_redirected_download_info() is None


def test_usb_portable_update_rewrites_manifest(usb_portable, monkeypatch):
    module, manifest_path = usb_portable
    write_manifest(manifest_path, {"version": "6.3.0"})
    monkeypatch.setattr(
        module,
        "get_redirected_download_info",
        lambda: {
            "version": "6.4.1",
            "download_url": "https://cdn/usbsafelyremovesetup_6-4-1.zip",
        },
    )

    assert module.update_manifest() is True

    manifest = read_manifest(manifest_path)
    assert manifest["version"] == "6.4.1"
    assert manifest["hash"] == f"sha256:{'f' * 64}"


def test_usb_portable_update_fails_when_redirect_unresolved(usb_portable, monkeypatch):
    module, manifest_path = usb_portable
    write_manifest(manifest_path, {"version": "6.3.0"})
    monkeypatch.setattr(module, "get_redirected_download_info", lambda: None)

    assert module.update_manifest() is False
