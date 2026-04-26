from io import BytesIO
import zipfile

from version_detector import SoftwareVersionConfig, VersionDetector, get_version_info


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

    monkeypatch.setattr(VersionDetector, "fetch_latest_version", lambda self, homepage, patterns: None)
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

    monkeypatch.setattr(VersionDetector, "fetch_latest_version", lambda self, homepage, patterns: None)

    assert get_version_info(config) is None
