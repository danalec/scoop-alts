import hashlib
from io import BytesIO
import zipfile

from version_detector import (
    SoftwareVersionConfig,
    VersionDetector,
    VersionResult,
    get_version_info,
)


def test_guess_version_from_url_basic():
    vd = VersionDetector()
    assert vd.guess_version_from_url("https://example.com/app-1.2.3.exe") == "1.2.3"
    assert vd.guess_version_from_url("https://example.com/v2.0.0/app.exe") == "2.0.0"
    assert vd.guess_version_from_url("file-2024.10.zip") == "2024.10"
    assert vd.guess_version_from_url("tool_7-1-2.zip") == "7.1.2"


def test_construct_download_url_template():
    vd = VersionDetector()
    url = vd.construct_download_url("https://host/app-$version.exe", "3.4.5")
    assert url == "https://host/app-3.4.5.exe"


def test_get_version_from_executable_url_guess():
    vd = VersionDetector()
    url = "https://example.com/app-1.2.3.exe"
    assert vd.get_version_from_executable(url) == "1.2.3"


def test_get_version_from_executable_headers_guess():
    vd = VersionDetector()

    class FakeResp:
        headers = {"Content-Disposition": "attachment; filename=tool-4.5.6.exe"}

    vd.head = lambda url, timeout=15, allow_redirects=True: FakeResp()  # type: ignore
    vd.guess_version_from_url = lambda u: None  # type: ignore
    vd.guess_version_from_headers = lambda resp: "4.5.6"  # type: ignore
    vd.guess_version_from_partial_content = lambda u: None  # type: ignore
    assert vd.get_version_from_executable("https://host/download") == "4.5.6"


def test_guess_version_from_partial_content_bytes():
    vd = VersionDetector()
    vd.get_range_bytes = lambda url, start=0, end=65535, timeout=15: b"FileVersion 5.6.7"  # type: ignore
    assert vd.guess_version_from_partial_content("http://example.com/app.exe") == "5.6.7"


def test_get_msi_version_url_guess():
    vd = VersionDetector()
    assert vd.get_msi_version("https://example.com/setup-1.2.3.msi") == "1.2.3"


def test_get_msi_version_headers_guess():
    vd = VersionDetector()

    class FakeResp:
        headers = {"Content-Disposition": "attachment; filename=tool-7.8.9.msi"}

    vd.head = lambda url, timeout=15, allow_redirects=True: FakeResp()  # type: ignore
    vd.guess_version_from_url = lambda u: None  # type: ignore
    vd.guess_version_from_headers = lambda resp: "7.8.9"  # type: ignore
    vd.guess_version_from_partial_content = lambda u: None  # type: ignore
    assert vd.get_msi_version("https://host/download") == "7.8.9"


def test_get_msi_version_partial_content_bytes():
    vd = VersionDetector()
    vd.get_range_bytes = lambda url, start=0, end=65535, timeout=15: b"ProductVersion 9.9.9"  # type: ignore
    assert vd.guess_version_from_partial_content("http://example.com/app.msi") == "9.9.9"


def test_get_version_from_download_artifact_uses_zip_handler():
    vd = VersionDetector()
    vd.get_zip_version = lambda url: "7.1.2"  # type: ignore
    assert vd.get_version_from_download_artifact("https://example.com/tool.zip") == "7.1.2"


def test_get_zip_version_falls_back_to_embedded_executable_metadata(monkeypatch):
    vd = VersionDetector()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("setup.exe", b"fake-exe")
    zip_bytes = buffer.getvalue()

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield zip_bytes

    monkeypatch.setattr(vd, "guess_version_from_url", lambda url: None)
    monkeypatch.setattr(vd, "head", lambda url: None)
    monkeypatch.setattr(vd, "guess_version_from_partial_content", lambda url: None)
    monkeypatch.setattr(vd.session, "get", lambda url, stream=True, timeout=60: FakeResp())
    monkeypatch.setattr(vd, "get_local_executable_version", lambda path: "7.1.2")

    assert vd.get_zip_version("https://example.com/tool.zip") == "7.1.2"


def test_get_zip_version_handles_executable_payload_at_zip_url(monkeypatch):
    vd = VersionDetector()
    exe_bytes = b"MZ" + b"\x00" * 32

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield exe_bytes

    monkeypatch.setattr(vd, "guess_version_from_url", lambda url: None)
    monkeypatch.setattr(vd, "head", lambda url: None)
    monkeypatch.setattr(vd, "guess_version_from_partial_content", lambda url: None)
    monkeypatch.setattr(vd.session, "get", lambda url, stream=True, timeout=60: FakeResp())
    monkeypatch.setattr(vd, "get_local_executable_version", lambda path: "4.7")

    assert vd.get_zip_version("https://example.com/tool.zip") == "4.7"


def test_get_version_info_falls_back_to_direct_download(monkeypatch):
    config = SoftwareVersionConfig(
        name="usb-safely-remove",
        homepage="https://example.com/download",
        version_patterns=[r"Version:\s*([\d.]+)"],
        download_url_template="https://example.com/tool.zip",
        description="Test app",
        license="Shareware",
    )

    monkeypatch.setattr(
        VersionDetector, "fetch_latest_version", lambda self, homepage, patterns: None
    )
    monkeypatch.setattr(
        VersionDetector,
        "get_version_from_download_artifact",
        lambda self, download_url, installer_type=None: "7.1.2",
    )
    monkeypatch.setattr(VersionDetector, "calculate_hash", lambda self, download_url: "abc123")

    assert get_version_info(config) == {
        "version": "7.1.2",
        "download_url": "https://example.com/tool.zip",
        "hash": "abc123",
    }


def test_get_version_info_skips_direct_download_fallback_for_templates(monkeypatch):
    config = SoftwareVersionConfig(
        name="templated-download",
        homepage="https://example.com/download",
        version_patterns=[r"Version:\s*([\d.]+)"],
        download_url_template="https://example.com/tool-$version.zip",
        description="Test app",
        license="Shareware",
    )

    monkeypatch.setattr(
        VersionDetector, "fetch_latest_version", lambda self, homepage, patterns: None
    )

    assert get_version_info(config) is None


def test_calculate_hash_uses_github_release_digest(monkeypatch):
    vd = VersionDetector()
    digest_hex = "a" * 64

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "assets": [
                    {"name": "app-1.2.3.exe", "digest": "sha256:" + "b" * 64},
                    {"name": "app-1.2.3.msi", "digest": "sha256:" + digest_hex},
                ]
            }

    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        return FakeResp()

    monkeypatch.setattr(vd.session, "get", fake_get)

    def forbidden_validate(url):
        raise AssertionError("validate_url must not be called for the digest shortcut")

    monkeypatch.setattr(vd, "validate_url", forbidden_validate)

    url = "https://github.com/owner/repo/releases/download/v1.2.3/app-1.2.3.msi?x=1#/renamed.msi"
    assert vd.calculate_hash(url) == digest_hex
    assert requested_urls == ["https://api.github.com/repos/owner/repo/releases/tags/v1.2.3"]


def test_calculate_hash_falls_back_when_github_digest_missing(monkeypatch):
    vd = VersionDetector()
    file_bytes = b"fake installer bytes"

    class ApiResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"assets": [{"name": "app.exe"}]}  # no digest field

    class FileResp:
        headers = {"Content-Length": str(len(file_bytes))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield file_bytes

    def fake_get(url, **kwargs):
        if "api.github.com" in url:
            return ApiResp()
        return FileResp()

    monkeypatch.setattr(vd.session, "get", fake_get)
    monkeypatch.setattr(vd, "validate_url", lambda url: True)

    url = "https://github.com/owner/repo/releases/download/v1.0.0/app.exe"
    assert vd.calculate_hash(url) == hashlib.sha256(file_bytes).hexdigest()


def test_calculate_hash_falls_back_when_github_api_fails(monkeypatch):
    vd = VersionDetector()
    file_bytes = b"fake installer bytes"

    class FileResp:
        headers = {"Content-Length": str(len(file_bytes))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield file_bytes

    def fake_get(url, **kwargs):
        if "api.github.com" in url:
            raise ConnectionError("rate limited")
        return FileResp()

    monkeypatch.setattr(vd.session, "get", fake_get)
    monkeypatch.setattr(vd, "validate_url", lambda url: True)

    url = "https://github.com/owner/repo/releases/download/v1.0.0/app.exe"
    assert vd.calculate_hash(url) == hashlib.sha256(file_bytes).hexdigest()


def test_calculate_hash_ignores_non_github_urls(monkeypatch):
    vd = VersionDetector()
    file_bytes = b"fake installer bytes"

    class FileResp:
        headers = {"Content-Length": str(len(file_bytes))}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield file_bytes

    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        return FileResp()

    monkeypatch.setattr(vd.session, "get", fake_get)
    monkeypatch.setattr(vd, "validate_url", lambda url: True)

    url = "https://example.com/releases/download/v1.0.0/app.exe"
    assert vd.calculate_hash(url) == hashlib.sha256(file_bytes).hexdigest()
    assert requested_urls == [url]


def test_get_version_info_skips_hash_when_version_unchanged(monkeypatch):
    config = SoftwareVersionConfig(
        name="unchanged-version",
        homepage="https://example.com/download",
        version_patterns=[r"Version:\s*([\d.]+)"],
        download_url_template="https://example.com/tool-$version.zip",
        description="Test app",
        license="MIT",
    )

    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(version="7.1.2", match_groups={}),
    )

    def forbidden_hash(self, download_url):
        raise AssertionError("calculate_hash must not be called for an unchanged version")

    monkeypatch.setattr(VersionDetector, "calculate_hash", forbidden_hash)

    assert get_version_info(config, current_version="7.1.2") == {
        "version": "7.1.2",
        "download_url": "https://example.com/tool-7.1.2.zip",
        "hash": None,
    }


def test_get_version_info_hashes_when_version_changed(monkeypatch):
    config = SoftwareVersionConfig(
        name="changed-version",
        homepage="https://example.com/download",
        version_patterns=[r"Version:\s*([\d.]+)"],
        download_url_template="https://example.com/tool-$version.zip",
        description="Test app",
        license="MIT",
    )

    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(version="7.1.3", match_groups={}),
    )
    hash_calls = []
    monkeypatch.setattr(
        VersionDetector,
        "calculate_hash",
        lambda self, download_url: hash_calls.append(download_url) or "abc123",
    )

    assert get_version_info(config, current_version="7.1.2") == {
        "version": "7.1.3",
        "download_url": "https://example.com/tool-7.1.3.zip",
        "hash": "abc123",
    }
    assert hash_calls == ["https://example.com/tool-7.1.3.zip"]


class _FakeReleasesSession:
    """Minimal stand-in for requests.Session serving the GitHub releases API."""

    def __init__(self, releases=None, exc=None):
        self.releases = releases
        self.exc = exc
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.exc is not None:
            raise self.exc

        class _Resp:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        return _Resp(self.releases)


def _forbidden_fetch(self, homepage, patterns):
    raise AssertionError("fetch_latest_version must not run when the release gate fires")


def test_force_https_upgrades_scheme_before_hash(monkeypatch):
    config = SoftwareVersionConfig(
        name="crlset-test",
        homepage="https://clients2.google.com/service/update2/crx",
        version_patterns=[r'codebase="(?P<codebase>https?://[^"]+)"'],
        download_url_template="$matchcodebase",
        description="Test app",
        license="BSD-3-Clause",
        force_https=True,
    )

    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(
            version="10786",
            match_groups={"codebase": "http://www.google.com/dl/release2/f.crx3"},
        ),
    )
    hash_calls = []
    monkeypatch.setattr(
        VersionDetector,
        "calculate_hash",
        lambda self, download_url: hash_calls.append(download_url) or "abc123",
    )

    assert get_version_info(config, current_version="1") == {
        "version": "10786",
        "download_url": "https://www.google.com/dl/release2/f.crx3",
        "hash": "abc123",
    }
    assert hash_calls == ["https://www.google.com/dl/release2/f.crx3"]

    # The unchanged-version early return must already carry the https URL
    assert get_version_info(config, current_version="10786") == {
        "version": "10786",
        "download_url": "https://www.google.com/dl/release2/f.crx3",
        "hash": None,
    }


def test_force_https_disabled_keeps_http_scheme(monkeypatch):
    config = SoftwareVersionConfig(
        name="crlset-test",
        homepage="https://clients2.google.com/service/update2/crx",
        version_patterns=[r'codebase="(?P<codebase>https?://[^"]+)"'],
        download_url_template="$matchcodebase",
        description="Test app",
        license="BSD-3-Clause",
    )

    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(
            version="10786",
            match_groups={"codebase": "http://www.google.com/dl/release2/f.crx3"},
        ),
    )
    hash_calls = []
    monkeypatch.setattr(
        VersionDetector,
        "calculate_hash",
        lambda self, download_url: hash_calls.append(download_url) or "abc123",
    )

    assert get_version_info(config, current_version="1") == {
        "version": "10786",
        "download_url": "http://www.google.com/dl/release2/f.crx3",
        "hash": "abc123",
    }
    assert hash_calls == ["http://www.google.com/dl/release2/f.crx3"]


def test_require_release_asset_selects_first_release_with_matching_asset(monkeypatch):
    config = SoftwareVersionConfig(
        name="ripgrep-all-test",
        homepage="https://github.com/phiresky/ripgrep-all/releases",
        version_patterns=[r"releases/tag/v([\d.]+)"],
        download_url_template=(
            "https://github.com/phiresky/ripgrep-all/releases/download/"
            "v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
        ),
        description="Test app",
        license="MIT",
        require_release_asset=True,
    )
    releases = [
        {
            "tag_name": "v9.9.9",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "ripgrep_all-v9.9.9-x86_64-unknown-linux-gnu.tar.gz"}],
        },
        {
            "tag_name": "v0.10.10",
            "draft": False,
            "prerelease": True,
            "assets": [{"name": "ripgrep_all-v0.10.10-x86_64-pc-windows-msvc.zip"}],
        },
        {
            "tag_name": "v0.10.9",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"}],
        },
    ]
    session = _FakeReleasesSession(releases=releases)
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)
    monkeypatch.setattr(VersionDetector, "fetch_latest_version", _forbidden_fetch)
    hash_calls = []
    monkeypatch.setattr(
        VersionDetector,
        "calculate_hash",
        lambda self, download_url: hash_calls.append(download_url) or "abc123",
    )

    assert get_version_info(config, current_version="0.10.8") == {
        "version": "0.10.9",
        "download_url": (
            "https://github.com/phiresky/ripgrep-all/releases/download/"
            "v0.10.9/ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"
        ),
        "hash": "abc123",
    }
    assert hash_calls == [
        "https://github.com/phiresky/ripgrep-all/releases/download/"
        "v0.10.9/ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"
    ]
    assert session.requests[0][0] == "https://api.github.com/repos/phiresky/ripgrep-all/releases"
    assert session.requests[0][1]["params"] == {"per_page": 20}


def test_require_release_asset_strips_prefix_literalized_in_template(monkeypatch):
    config = SoftwareVersionConfig(
        name="thorium-test",
        homepage="https://github.com/gz83/thorium/releases",
        version_patterns=[r"releases/tag/M([\d.]+)"],
        download_url_template=(
            "https://github.com/gz83/thorium/releases/download/"
            "M$version/Thorium_AVX2_$version.zip"
        ),
        description="Test app",
        license="BSD-3-Clause",
        require_release_asset=True,
    )
    releases = [
        {
            "tag_name": "M152.0.7977.55",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": "Thorium_AVX2_152.0.7977.55.zip"}],
        }
    ]
    session = _FakeReleasesSession(releases=releases)
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)
    monkeypatch.setattr(VersionDetector, "fetch_latest_version", _forbidden_fetch)
    monkeypatch.setattr(VersionDetector, "calculate_hash", lambda self, download_url: "abc123")

    assert get_version_info(config, current_version="152.0.7977.0") == {
        "version": "152.0.7977.55",
        "download_url": (
            "https://github.com/gz83/thorium/releases/download/"
            "M152.0.7977.55/Thorium_AVX2_152.0.7977.55.zip"
        ),
        "hash": "abc123",
    }


def test_require_release_asset_falls_back_silently_on_api_failure(monkeypatch):
    config = SoftwareVersionConfig(
        name="ripgrep-all-test",
        homepage="https://github.com/phiresky/ripgrep-all/releases",
        version_patterns=[r"releases/tag/v([\d.]+)"],
        download_url_template=(
            "https://github.com/phiresky/ripgrep-all/releases/download/"
            "v$version/ripgrep_all-v$version-x86_64-pc-windows-msvc.zip"
        ),
        description="Test app",
        license="MIT",
        require_release_asset=True,
    )
    session = _FakeReleasesSession(exc=ConnectionError("rate limited"))
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)
    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(version="0.10.9", match_groups={}),
    )
    monkeypatch.setattr(VersionDetector, "calculate_hash", lambda self, download_url: "abc123")

    assert get_version_info(config, current_version="0.10.8") == {
        "version": "0.10.9",
        "download_url": (
            "https://github.com/phiresky/ripgrep-all/releases/download/"
            "v0.10.9/ripgrep_all-v0.10.9-x86_64-pc-windows-msvc.zip"
        ),
        "hash": "abc123",
    }


class _ChecksumSession:
    """Serves the GitHub release API plus a configurable checksum asset."""

    def __init__(self, checksum_text, include_checksum_asset=True):
        self.checksum_text = checksum_text
        self.include_checksum_asset = include_checksum_asset
        self.api_requests = []
        self.asset_requests = []

    def get(self, url, **kwargs):
        if "api.github.com" in url:
            self.api_requests.append(url)
            assets = [{"name": "app-1.2.3.zip", "digest": "sha256:" + "a" * 64}]
            if self.include_checksum_asset:
                assets.append(
                    {
                        "name": "app-1.2.3.zip.sha256",
                        "browser_download_url": (
                            "https://github.com/owner/repo/releases/download/"
                            "v1.2.3/app-1.2.3.zip.sha256"
                        ),
                    }
                )
            return _JsonReleaseResponse({"assets": assets})
        self.asset_requests.append(url)
        return _ChecksumTextResponse(self.checksum_text)


class _JsonReleaseResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _ChecksumTextResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        raise ValueError("not json")


GITHUB_DOWNLOAD_URL = "https://github.com/owner/repo/releases/download/v1.2.3/app-1.2.3.zip"


def _checksum_config(**overrides):
    params = {
        "name": "checksum-app",
        "homepage": "https://github.com/owner/repo/releases",
        "version_patterns": [r"releases/tag/v([\d.]+)"],
        "download_url_template": (
            "https://github.com/owner/repo/releases/download/v$version/app-$version.zip"
        ),
        "description": "Test app",
        "license": "MIT",
        "checksum_asset_suffix": ".sha256",
    }
    params.update(overrides)
    return SoftwareVersionConfig(**params)


def _stub_detection(monkeypatch, computed_hash):
    monkeypatch.setattr(
        VersionDetector,
        "fetch_latest_version",
        lambda self, homepage, patterns: VersionResult(version="1.2.3", match_groups={}),
    )
    monkeypatch.setattr(VersionDetector, "calculate_hash", lambda self, download_url: computed_hash)


def test_get_version_info_verifies_matching_checksum_asset(monkeypatch, capsys):
    digest = "a" * 64
    config = _checksum_config()
    _stub_detection(monkeypatch, digest)
    session = _ChecksumSession(f"{digest}  app-1.2.3.zip\n")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    assert get_version_info(config, current_version="0.0.1") == {
        "version": "1.2.3",
        "download_url": GITHUB_DOWNLOAD_URL,
        "hash": digest,
    }
    assert "✅ Upstream checksum verified" in capsys.readouterr().out


def test_get_version_info_checksum_match_is_case_insensitive(monkeypatch, capsys):
    computed = "a" * 64
    config = _checksum_config()
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession(f"{computed.upper()}  app-1.2.3.zip\n")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    info = get_version_info(config, current_version="0.0.1")
    assert info is not None
    assert info["hash"] == computed
    assert "✅ Upstream checksum verified" in capsys.readouterr().out


def test_get_version_info_fails_on_checksum_mismatch(monkeypatch, capsys):
    computed = "a" * 64
    upstream = "b" * 64
    config = _checksum_config()
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession(f"{upstream}  app-1.2.3.zip\n")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    assert get_version_info(config, current_version="0.0.1") is None
    assert "❌ Upstream checksum mismatch" in capsys.readouterr().out


def test_get_version_info_skips_verification_when_checksum_asset_missing(monkeypatch, capsys):
    computed = "a" * 64
    config = _checksum_config()
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession("unused", include_checksum_asset=False)
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    info = get_version_info(config, current_version="0.0.1")
    assert info == {
        "version": "1.2.3",
        "download_url": GITHUB_DOWNLOAD_URL,
        "hash": computed,
    }
    assert session.asset_requests == []
    out = capsys.readouterr().out
    assert "Upstream checksum" not in out


def test_get_version_info_skips_verification_for_unparseable_checksum(monkeypatch, capsys):
    computed = "a" * 64
    config = _checksum_config()
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession("no checksum in this file\n")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    info = get_version_info(config, current_version="0.0.1")
    assert info is not None
    assert info["hash"] == computed
    assert "Upstream checksum" not in capsys.readouterr().out


def test_get_version_info_skips_verification_for_non_github_url(monkeypatch, capsys):
    computed = "a" * 64
    config = _checksum_config(
        homepage="https://example.com/download",
        download_url_template="https://example.com/app-$version.zip",
    )
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession("unused")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    info = get_version_info(config, current_version="0.0.1")
    assert info == {
        "version": "1.2.3",
        "download_url": "https://example.com/app-1.2.3.zip",
        "hash": computed,
    }
    assert session.api_requests == []
    assert "Upstream checksum" not in capsys.readouterr().out


def test_get_version_info_without_checksum_suffix_makes_no_api_calls(monkeypatch):
    computed = "a" * 64
    config = _checksum_config(checksum_asset_suffix="")
    _stub_detection(monkeypatch, computed)
    session = _ChecksumSession("unused")
    monkeypatch.setattr("version_detector.get_session", lambda **kwargs: session)

    info = get_version_info(config, current_version="0.0.1")
    assert info is not None
    assert info["hash"] == computed
    assert session.api_requests == []
