from version_detector import VersionDetector


def test_guess_version_from_url_basic():
    vd = VersionDetector()
    assert vd.guess_version_from_url("https://example.com/app-1.2.3.exe") == "1.2.3"
    assert vd.guess_version_from_url("https://example.com/v2.0.0/app.exe") == "2.0.0"
    assert vd.guess_version_from_url("file-2024.10.zip") == "2024.10"


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
