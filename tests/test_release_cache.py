"""Unit tests for the on-disk release-metadata cache in version_detector."""

import json
import time

import pytest

import version_detector
from version_detector import VersionDetector


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    """Isolate the release cache in a per-test file and enable it explicitly."""
    path = tmp_path / ".temp" / "release-cache.json"
    monkeypatch.setattr(version_detector, "_release_cache_path", lambda: path)
    monkeypatch.setenv("RELEASE_CACHE_TTL", "1800")
    return path


class _JsonResp:
    def __init__(self, data):
        self._data = data
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _RecordingSession:
    """Fake session returning a fixed JSON body and recording requests."""

    def __init__(self, body):
        self.body = body
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return _JsonResp(self.body)


class _ExplodingSession:
    def get(self, url, **kwargs):
        raise AssertionError("network must not be touched for a cache hit")


def test_cache_miss_fetches_and_persists_entry(cache_path):
    vd = VersionDetector()
    session = _RecordingSession({"tag_name": "v1.2.3"})
    vd.session = session

    url = "https://api.github.com/repos/owner/repo/releases/tags/v1.2.3"
    assert vd._cached_api_get(url) == {"tag_name": "v1.2.3"}
    assert session.urls == [url]

    on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
    entry = on_disk[url]
    assert entry["body"] == {"tag_name": "v1.2.3"}
    assert time.time() - entry["fetched_at"] < 60


def test_cache_hit_avoids_network_within_ttl(cache_path):
    vd = VersionDetector()
    session = _RecordingSession({"assets": []})
    vd.session = session
    url = "https://api.github.com/repos/owner/repo/releases/tags/v9.9.9"
    assert vd._cached_api_get(url) == {"assets": []}
    assert session.urls == [url]

    vd.session = _ExplodingSession()
    assert vd._cached_api_get(url) == {"assets": []}
    assert session.urls == [url]


def test_cache_entry_expires_after_ttl(cache_path):
    vd = VersionDetector()
    session = _RecordingSession({"fresh": True})
    vd.session = session
    url = "https://api.github.com/repos/owner/repo/releases/tags/v2.0.0"
    assert vd._cached_api_get(url) == {"fresh": True}

    # Age the entry beyond the 1800s TTL; the next call must refetch
    entries = json.loads(cache_path.read_text(encoding="utf-8"))
    entries[url]["fetched_at"] = time.time() - 1900
    cache_path.write_text(json.dumps(entries), encoding="utf-8")

    session2 = _RecordingSession({"fresh": False})
    vd.session = session2
    assert vd._cached_api_get(url) == {"fresh": False}
    assert session2.urls == [url]


def test_cache_respects_release_cache_ttl_env(cache_path, monkeypatch):
    vd = VersionDetector()
    session = _RecordingSession({"n": 1})
    vd.session = session
    url = "https://api.github.com/repos/owner/repo/releases/tags/v3"
    assert vd._cached_api_get(url) == {"n": 1}

    # 120s old: still fresh under the 1800s default, stale under a 30s TTL
    monkeypatch.setenv("RELEASE_CACHE_TTL", "30")
    entries = json.loads(cache_path.read_text(encoding="utf-8"))
    entries[url]["fetched_at"] = time.time() - 120
    cache_path.write_text(json.dumps(entries), encoding="utf-8")

    session2 = _RecordingSession({"n": 2})
    vd.session = session2
    assert vd._cached_api_get(url) == {"n": 2}
    assert session2.urls == [url]


def test_cache_key_includes_query_params(cache_path):
    vd = VersionDetector()
    session = _RecordingSession(["release"])
    vd.session = session
    url = "https://api.github.com/repos/owner/repo/releases"
    assert vd._cached_api_get(url, params={"per_page": 20}) == ["release"]
    assert vd._cached_api_get(url, params={"per_page": 50}) == ["release"]
    assert session.urls == [url, url]

    vd.session = _ExplodingSession()
    assert vd._cached_api_get(url, params={"per_page": 20}) == ["release"]


def test_empty_api_payload_is_not_cached(cache_path):
    """A 200 with an empty list/dict is a transient glitch, not a fact.

    Caching it would poison the asset gate for the whole TTL (zapfast,
    2026-09-22): the next runs keep seeing zero releases and fall back to
    scraping, which then fails the update.
    """
    vd = VersionDetector()
    session = _RecordingSession([])
    vd.session = session
    url = "https://api.github.com/repos/o/r/releases"
    assert vd._cached_api_get(url, params={"per_page": 20}) == []
    assert session.urls == [url]

    session2 = _RecordingSession([{"tag_name": "v1.0.0"}])
    vd.session = session2
    assert vd._cached_api_get(url, params={"per_page": 20}) == [{"tag_name": "v1.0.0"}]
    assert session2.urls == [url]

    # Only the non-empty payload may be persisted; the empty glitch must not
    # shadow it for the TTL window.
    entries = json.loads(cache_path.read_text(encoding="utf-8"))
    key = f"{url}?per_page=20"
    assert entries[key]["body"] == [{"tag_name": "v1.0.0"}]


def test_cache_network_failure_returns_none_and_writes_nothing(cache_path):
    vd = VersionDetector()

    class _DownSession:
        def get(self, url, **kwargs):
            raise ConnectionError("api down")

    vd.session = _DownSession()
    assert vd._cached_api_get("https://api.github.com/repos/o/r/releases") is None
    assert not cache_path.exists()


def test_cache_write_failure_is_silent(tmp_path, monkeypatch):
    blocker = tmp_path / "release-cache.json"
    blocker.mkdir()  # a directory at the cache path makes every write fail
    monkeypatch.setattr(version_detector, "_release_cache_path", lambda: blocker)
    monkeypatch.setenv("RELEASE_CACHE_TTL", "1800")

    vd = VersionDetector()
    vd.session = _RecordingSession({"ok": True})
    assert vd._cached_api_get("https://api.github.com/repos/o/r/releases") == {"ok": True}


def test_corrupt_cache_file_is_treated_as_empty(cache_path):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{ not json", encoding="utf-8")

    vd = VersionDetector()
    session = _RecordingSession({"recovered": True})
    vd.session = session
    url = "https://api.github.com/repos/owner/repo/releases"
    assert vd._cached_api_get(url) == {"recovered": True}
    assert session.urls == [url]


def test_release_cache_ttl_env_parsing(monkeypatch):
    monkeypatch.delenv("RELEASE_CACHE_TTL", raising=False)
    monkeypatch.setattr(version_detector, "_running_under_test", lambda: False)
    assert version_detector._release_cache_ttl() == 1800.0

    monkeypatch.setenv("RELEASE_CACHE_TTL", "60")
    assert version_detector._release_cache_ttl() == 60.0

    monkeypatch.setenv("RELEASE_CACHE_TTL", "not-a-number")
    assert version_detector._release_cache_ttl() == 1800.0


def test_release_cache_disabled_by_default_under_test_runner(monkeypatch):
    monkeypatch.delenv("RELEASE_CACHE_TTL", raising=False)
    monkeypatch.setattr(version_detector, "_running_under_test", lambda: True)
    assert version_detector._release_cache_ttl() == 0.0

    monkeypatch.setenv("RELEASE_CACHE_TTL", "60")
    assert version_detector._release_cache_ttl() == 60.0
