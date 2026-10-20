"""Regression tests for the degraded-page guard and the failure classification.

The guard: a vendor serving an outage page instead of the product page must not
be able to hand the updater a version it never shipped.
The classification: a failure caused by the network is reported as upstream, so
it does not read like a broken updater.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from failure_classification import (  # noqa: E402
    FAILURE_CODE,
    FAILURE_UPSTREAM,
    classify_failure,
    group_failures,
)
from version_detector import VersionDetector, _page_marker  # noqa: E402


class TestPageMarker:
    def test_generic_trailing_segment_is_skipped(self):
        assert _page_marker("https://github.com/espressif/esptool/releases") == "esptool"
        assert _page_marker("https://lizardsystems.com/wi-fi-scanner/") == "wifiscanner"
        assert (
            _page_marker("https://www.softperfect.com/products/cacherelocator/") == "cacherelocator"
        )

    def test_urls_without_a_page_identity_are_left_alone(self):
        assert _page_marker("https://example.com/") == ""
        assert _page_marker("https://example.com/a") == ""  # too short to be identity
        # An api url names the repository, not a page: nothing to guard.
        assert _page_marker("https://api.github.com/repos/x/y/releases/latest") == ""


class TestDegradedPageGuard:
    def test_product_page_is_accepted(self):
        page = (
            "<html><head><title>Wi-Fi Scanner - LizardSystems</title></head>"
            "<body><script>{'product': 'wifiscanner', 'version': '25.05'}</script>"
            "</body></html>"
        )
        assert VersionDetector._page_looks_like_product(
            "https://lizardsystems.com/wi-fi-scanner/", page
        )

    def test_outage_page_is_rejected(self):
        # A maintenance page that happens to mention a version: the number is
        # not the product's, and publishing it would ship a version that never
        # existed.
        page = "<html><body><h1>Service unavailable</h1><p>Version 1.89</p></body></html>"
        assert not VersionDetector._page_looks_like_product(
            "https://lizardsystems.com/wi-fi-scanner/", page
        )

    def test_non_html_content_is_not_guarded(self):
        assert VersionDetector._page_looks_like_product(
            "https://api.github.com/repos/x/y/releases/latest", '{"tag_name": "v1.2.3"}'
        )

    def test_slightly_different_spelling_still_passes(self):
        # The vendor page spells the product with a doubled letter; the guard
        # matches n-grams, not the exact string. The url is the real one, so
        # the test keeps meaning what it says when the vendor rewords.
        import json

        registry = json.loads(
            (Path(__file__).resolve().parent.parent / "scripts" / "packages.json").read_text(
                encoding="utf-8"
            )
        )
        homepage = registry["hdd-lff-portable"]["homepage"]
        page = "<html><body>HDD LLF LowLevelFormat Tool 4.50 download</body></html>"
        assert VersionDetector._page_looks_like_product(homepage, page)

    def test_detector_refuses_a_version_from_an_outage_page(self, monkeypatch):
        # The integration point: a vendor that answers with an outage page
        # must not hand the updater a version at all.
        import requests

        class _Response:
            status_code = 200
            headers = {}

            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class _Session:
            def __init__(self, text):
                self._text = text

            def get(self, url, **kwargs):
                return _Response(self._text)

        outage = (
            "<html><head><title>Maintenance</title></head>"
            "<body><h1>We'll be back soon</h1><p>Version 1.89</p></body></html>"
        )
        detector = VersionDetector()
        detector.session = _Session(outage)

        result = detector.fetch_latest_version(
            "https://lizardsystems.com/wi-fi-scanner/", [r"Version\s+([0-9]+\.[0-9]+)"]
        )

        assert result is None, "a version scraped from an outage page must be refused"
        assert requests is not None  # keep the import meaningful for readers


class TestFailureClassification:
    @pytest.mark.parametrize(
        "text",
        [
            "HTTPSConnectionPool(host='safelyremove.com', port=443): "
            "Max retries exceeded with url: /startdownload.htm",
            "NewConnectionError('Failed to establish a new connection')",
            "urllib3.exceptions.NewConnectionError: Connection refused",
            "403 Client Error: rate limit exceeded for url: https://api.github.com/...",
            "socket.gaierror: [Errno -2] Name or service not known",
            "requests.exceptions.ConnectionError: Connection reset by peer",
        ],
    )
    def test_network_failures_are_upstream(self, text):
        assert classify_failure(text) == FAILURE_UPSTREAM

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "Traceback (most recent call last):\n  KeyError: 'version'",
            "ERROR: manifest has no 'url' field",
            "Timeout after 120s",
        ],
    )
    def test_everything_else_is_our_code(self, text):
        # A failure we cannot explain is treated as ours on purpose.
        assert classify_failure(text) == FAILURE_CODE

    def test_grouping_separates_the_two_kinds(self):
        buckets = group_failures(
            [
                ("upstream-pkg", "Connection refused"),
                ("code-pkg", "KeyError: 'version'"),
            ]
        )
        kinds = {bucket.kind: bucket.packages for bucket in buckets}
        assert kinds[FAILURE_UPSTREAM] == ["upstream-pkg"]
        assert kinds[FAILURE_CODE] == ["code-pkg"]
