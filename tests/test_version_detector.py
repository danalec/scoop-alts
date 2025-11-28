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
