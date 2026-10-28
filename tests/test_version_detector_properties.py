"""Property tests for the pure parsers in ``version_detector``.

``version_detector.py`` is the largest module in the repo (over 1100 lines) and
most of its failure surface is text parsing: version inference from vendor pages,
tag-to-template normalisation, http/https rewriting. Those parsers meet
untrusted third-party HTML, so the interesting question is not "does this one
page parse" but "does the parser hold its invariants on inputs nobody wrote".

There is no hypothesis dependency in this repo, so the generators below are a
seeded ``random.Random`` -- deterministic across runs, which matters because a
fuzz test that only fails on Tuesdays is worse than no test.
"""

import random
import re
import string

import pytest

from version_detector import VersionDetector, _https_url, _tag_version_for_template

SEED = 20251011
ROUNDS = 400

DETECTOR = VersionDetector()

# infer_version() only recognises 2..4 numeric components; beyond that it
# truncates, so round-trip is asserted only inside that range.
ROUND_TRIP_SEGMENTS = (2, 3, 4)

NORMALIZED_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
VERSION_TOKEN_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")


def _random_version(rng, segments):
    return ".".join(str(rng.randint(0, 999)) for _ in range(segments))


def _random_url(rng):
    scheme = rng.choice(["http", "https", "ftp"])
    host = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 10)))
    path = "/" + "".join(
        rng.choice(string.ascii_letters + "._-") for _ in range(rng.randint(0, 20))
    )
    tail = rng.choice(["", "?a=1", "?imm&v=&t=", "#/x.exe"])
    return f"{scheme}://{host}{path}{tail}"


def _random_junk(rng):
    alphabet = string.ascii_letters + string.digits + " ._-/\\v"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))


# --------------------------------------------------------------- infer_version


@pytest.mark.parametrize("segments", ROUND_TRIP_SEGMENTS)
def test_infer_version_round_trips_dot_versions(segments):
    rng = random.Random(SEED + segments)
    for _ in range(ROUNDS):
        version = _random_version(rng, segments)
        assert DETECTOR.infer_version(version) == version


@pytest.mark.parametrize("segments", ROUND_TRIP_SEGMENTS)
def test_infer_version_treats_separators_equivalently(segments):
    # A vendor that publishes 1-2-3 and 1.2.3 for the same release must not
    # look like two different versions.
    rng = random.Random(SEED * 2 + segments)
    for _ in range(ROUNDS):
        parts = [str(rng.randint(0, 999)) for _ in range(segments)]
        dotted = ".".join(parts)
        dashed = "-".join(parts)
        underscored = "_".join(parts)
        assert DETECTOR.infer_version(dashed) == dotted
        assert DETECTOR.infer_version(underscored) == dotted


def test_infer_version_never_returns_separators():
    rng = random.Random(SEED + 99)
    for _ in range(ROUNDS * 2):
        text = _random_junk(rng)
        found = DETECTOR.infer_version(text)
        if found is not None:
            assert "-" not in found and "_" not in found
            assert VERSION_TOKEN_RE.match(found), f"{found!r} from {text!r}"


def test_infer_version_is_stable_on_embedded_text():
    rng = random.Random(SEED + 100)
    for _ in range(ROUNDS):
        version = _random_version(rng, rng.choice(ROUND_TRIP_SEGMENTS))
        for template in ("Download v%s now", "release-%s-x64.zip", "Version: %s", "%s"):
            text = template % version
            assert DETECTOR.infer_version(text) == version


@pytest.mark.parametrize("empty", [None, "", "   ", "no digits here", "v", "-", "."])
def test_infer_version_returns_none_for_non_versions(empty):
    assert DETECTOR.infer_version(empty) is None


# ------------------------------------------------------------ normalize_version


def test_normalize_version_is_idempotent():
    rng = random.Random(SEED + 200)
    for _ in range(ROUNDS):
        value = _random_junk(rng)
        once = DETECTOR.normalize_version(value)
        if once is None:
            continue
        assert DETECTOR.normalize_version(once) == once
        assert "-" not in once and "_" not in once


def test_normalize_version_strips_wrapper_characters():
    assert DETECTOR.normalize_version("-1.2.3-") == "1.2.3"
    assert DETECTOR.normalize_version("_1.2.3_") == "1.2.3"
    assert DETECTOR.normalize_version("...") is None


# -------------------------------------------------------------------- _https_url


def test_https_url_is_idempotent():
    rng = random.Random(SEED + 300)
    for _ in range(ROUNDS):
        url = _random_url(rng)
        once = _https_url(url)
        assert _https_url(once) == once


def test_https_url_preserves_path_and_query():
    rng = random.Random(SEED + 301)
    for _ in range(ROUNDS):
        url = _random_url(rng)
        upgraded = _https_url(url)
        if url.lower().startswith("http://"):
            assert upgraded.startswith("https://")
            assert upgraded[len("https://") :] == url[len("http://") :]
        else:
            assert upgraded == url


# ------------------------------------------------- _tag_version_for_template


def test_tag_version_for_template_returns_suffix_of_tag():
    rng = random.Random(SEED + 400)
    prefixes = ["", "v", "V", "release-", "ver", "x"]
    templates = [
        "/download/v$version/file.zip",
        "/download/$version/file.zip",
        "/download/release-$version/file.zip",
        "/download/file-$version.zip",
        "/static/file.zip",
    ]
    for _ in range(ROUNDS):
        tag = rng.choice(prefixes) + _random_version(rng, rng.choice(ROUND_TRIP_SEGMENTS))
        template = rng.choice(templates)
        result = _tag_version_for_template(tag, template)
        assert tag.endswith(result), f"{tag!r} / {template!r} -> {result!r}"
        assert "\n" not in result


def test_tag_version_for_template_strips_prefix_that_template_literalizes():
    assert _tag_version_for_template("v1.2.3", "/dl/v$version/x.zip") == "1.2.3"
    assert _tag_version_for_template("1.2.3", "/dl/v$version/x.zip") == "1.2.3"
    # A prefix the template does not repeat is part of the version string.
    assert _tag_version_for_template("v1.2.3", "/dl/$version/x.zip") == "v1.2.3"


def test_tag_version_for_template_ignores_template_without_token():
    rng = random.Random(SEED + 401)
    for _ in range(ROUNDS):
        tag = rng.choice(["v1.2.3", "1.2.3", "release-1.2.3"])
        assert _tag_version_for_template(tag, "/dl/latest/file.zip") == tag


# -------------------------------------------------- supports_direct_download_fallback


def test_supports_direct_download_fallback_matches_token_presence():
    rng = random.Random(SEED + 500)
    for _ in range(ROUNDS):
        template = _random_junk(rng)
        if not template:
            continue
        expected = re.search(r"\$[A-Za-z_]\w*", template) is None
        assert DETECTOR.supports_direct_download_fallback(template) is expected


def test_supports_direct_download_fallback_rejects_empty_template():
    # An empty template has no token to substitute, but it is also not a URL
    # anyone can download from, so the method short-circuits to False. Fuzzing
    # this property first is what surfaced the distinction.
    assert DETECTOR.supports_direct_download_fallback("") is False
    assert DETECTOR.supports_direct_download_fallback(None) is False
    assert DETECTOR.supports_direct_download_fallback("/dl/latest.zip") is True


# ------------------------------------------------------ guess_version_from_url


def test_guess_version_from_url_never_raises():
    rng = random.Random(SEED + 600)
    for _ in range(ROUNDS):
        # Must survive whatever the vendor puts in a filename.
        DETECTOR.guess_version_from_url(_random_junk(rng))
        DETECTOR.guess_version_from_url(_random_url(rng))


def test_guess_version_from_url_recovers_version_from_filename():
    assert DETECTOR.guess_version_from_url("https://x/tool-1.2.3-x64.zip") == "1.2.3"
