"""Tests for scripts/manifest_doctor.py - deep-lint checks for Scoop manifests."""

import io
import json
import os
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import manifest_doctor as md

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOMATE_SCOOP = REPO_ROOT / "scripts" / "automate-scoop.py"
SHA256_HEX = "a" * 64
HASH_OK = f"sha256:{SHA256_HEX}"


def make_zip_bytes(entries):
    """Build a real zip archive in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


GOOD_ZIP = make_zip_bytes(
    {
        "app-1.0.0/app.exe": b"MZ fake exe",
        "app-1.0.0/lib/tool.exe": b"MZ fake exe",
        "docs/README.txt": b"hello",
    }
)


class FakeRangeTransport:
    """Serves byte ranges from an in-memory blob, recording requests."""

    def __init__(self, blob, fail=None):
        self.blob = blob
        self.fail = fail
        self.tail_requests = []
        self.range_requests = []

    def fetch_tail(self, url, size=md.TAIL_FETCH_SIZE):
        self.tail_requests.append((url, size))
        if self.fail is not None:
            raise self.fail
        return self.blob[-size:]

    def fetch_range(self, url, start, end):
        self.range_requests.append((url, start, end))
        if self.fail is not None:
            raise self.fail
        return self.blob[start : end + 1]


def exe_manifest(**overrides):
    manifest = {
        "version": "1.2.3",
        "description": "A test application",
        "homepage": "https://example.com",
        "license": "MIT",
        "url": "https://example.com/downloads/app-1.2.3.exe",
        "hash": HASH_OK,
    }
    manifest.update(overrides)
    return manifest


def zip_manifest(**overrides):
    manifest = exe_manifest(url="https://example.com/downloads/app-1.2.3.zip")
    manifest.update(overrides)
    return manifest


def findings_by_check(report, check):
    return [f for f in report.findings if f.check == check]


def write_bucket(tmp_path, manifests):
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    for name, manifest in manifests.items():
        text = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (bucket / f"{name}.json").write_text(text, encoding="utf-8")
    return bucket


# ============================================================================
# Zip listing: EOCD parsing
# ============================================================================


def make_eocd_tail(entries_total=1, cd_size=64, cd_offset=10, comment=b"", pad=64):
    record = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        entries_total,
        entries_total,
        cd_size,
        cd_offset,
        len(comment),
    )
    return b"\x00" * pad + record + comment


def test_parse_eocd_returns_directory_location():
    tail = make_eocd_tail(entries_total=3, cd_size=200, cd_offset=42)
    assert md.parse_eocd(tail) == (3, 200, 42)


def test_parse_eocd_skips_signature_lookalike_in_comment():
    comment = b"junk PK\x05\x06 junk" + b"x" * 30
    tail = make_eocd_tail(entries_total=1, cd_size=64, cd_offset=0, comment=comment)
    assert md.parse_eocd(tail) == (1, 64, 0)


def test_parse_eocd_detects_zip64_entry_sentinel():
    tail = make_eocd_tail(entries_total=0xFFFF)
    with pytest.raises(md.Zip64ListingError):
        md.parse_eocd(tail)


def test_parse_eocd_detects_zip64_size_sentinel():
    tail = make_eocd_tail(cd_size=0xFFFFFFFF)
    with pytest.raises(md.Zip64ListingError):
        md.parse_eocd(tail)


def test_parse_eocd_rejects_multi_disk_archive():
    record = struct.pack("<IHHHHIIH", 0x06054B50, 1, 0, 1, 1, 64, 0, 0)
    with pytest.raises(md.ZipListingError):
        md.parse_eocd(b"\x00" * 32 + record)


def test_parse_eocd_missing_record():
    with pytest.raises(md.ZipListingError):
        md.parse_eocd(b"\x00" * 4096)


# ============================================================================
# Zip listing: central directory + full listing via mocked transport
# ============================================================================


def test_parse_central_directory_names():
    total, cd_size, cd_offset = md.parse_eocd(GOOD_ZIP[-md.TAIL_FETCH_SIZE :])
    cd_data = GOOD_ZIP[cd_offset : cd_offset + cd_size]
    names = md.parse_central_directory(cd_data, total)
    assert names == ["app-1.0.0/app.exe", "app-1.0.0/lib/tool.exe", "docs/README.txt"]


def test_list_zip_entries_with_range_transport():
    transport = FakeRangeTransport(GOOD_ZIP)
    entries = md.list_zip_entries("https://example.com/app.zip", transport)
    assert set(entries) == {
        "app-1.0.0/app.exe",
        "app-1.0.0/lib/tool.exe",
        "docs/README.txt",
    }
    # Two range requests: one tail, one central directory window.
    assert len(transport.tail_requests) == 1
    assert len(transport.range_requests) == 1
    _, start, end = transport.range_requests[0]
    assert 0 <= start <= end < len(GOOD_ZIP)


def test_list_zip_entries_empty_archive():
    blob = make_zip_bytes({})
    transport = FakeRangeTransport(blob)
    assert md.list_zip_entries("https://example.com/empty.zip", transport) == []


# ============================================================================
# Check: scheme
# ============================================================================


def test_scheme_https_ok():
    report = md.doctor_manifest("ok.json", exe_manifest())
    assert findings_by_check(report, "scheme") == []


def test_scheme_http_is_error():
    report = md.doctor_manifest("plain.json", exe_manifest(url="http://example.com/app-1.2.3.exe"))
    findings = findings_by_check(report, "scheme")
    assert len(findings) == 1
    assert findings[0].severity == "error"


# ============================================================================
# Check: hash format
# ============================================================================


def test_hash_prefixed_sha256_ok():
    report = md.doctor_manifest("ok.json", exe_manifest())
    assert findings_by_check(report, "hash-format") == []


def test_hash_bare_hex_warns_to_standardize():
    report = md.doctor_manifest("bare.json", exe_manifest(hash=SHA256_HEX))
    findings = findings_by_check(report, "hash-format")
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "sha256:" in findings[0].message
    assert report.passed()
    assert not report.passed(warnings_as_errors=True)


def test_hash_invalid_is_error():
    report = md.doctor_manifest("bad.json", exe_manifest(hash="not-a-real-hash"))
    findings = findings_by_check(report, "hash-format")
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_hash_wrong_algorithm_is_error():
    report = md.doctor_manifest("sha1.json", exe_manifest(hash="sha1:" + "b" * 40))
    findings = findings_by_check(report, "hash-format")
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_hash_non_string_is_skipped():
    report = md.doctor_manifest(
        "xpath.json",
        exe_manifest(hash={"url": "https://example.com/hashes.xml", "xpath": "/hash"}),
    )
    assert findings_by_check(report, "hash-format") == []


def test_architecture_hash_bare_hex_warns():
    manifest = exe_manifest(
        url=None,
        architecture={"64bit": {"url": "https://example.com/app-x64.exe", "hash": SHA256_HEX}},
    )
    del manifest["url"]
    report = md.doctor_manifest("arch.json", manifest)
    findings = findings_by_check(report, "hash-format")
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].message.startswith("architecture.64bit.hash")


# ============================================================================
# Check: version consistency (architecture entries)
# ============================================================================


def test_arch_url_containing_version_ok():
    manifest = exe_manifest(
        version="4.40.0",
        architecture={
            "64bit": {
                "url": "https://example.com/dl/4.40.0/app-x64.exe",
                "hash": HASH_OK,
            }
        },
    )
    del manifest["url"]
    report = md.doctor_manifest("synced.json", manifest)
    assert findings_by_check(report, "version-consistency") == []


def test_arch_url_with_stale_version_warns():
    # The widevinecdm class: one architecture lags the manifest version.
    manifest = exe_manifest(
        version="152.0.7977.65",
        architecture={
            "64bit": {
                "url": "https://dl.example.com/rel/152.0.7977.65/app-x64.exe",
                "hash": HASH_OK,
            },
            "32bit": {
                "url": "https://dl.example.com/rel/150.0.0000.00/app-x86.exe",
                "hash": HASH_OK,
            },
        },
    )
    del manifest["url"]
    report = md.doctor_manifest("stale.json", manifest)
    findings = findings_by_check(report, "version-consistency")
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "32bit" in findings[0].message


def test_top_level_url_version_not_checked():
    # The version-consistency check is scoped to architecture entries.
    report = md.doctor_manifest("toplevel.json", exe_manifest(url="https://example.com/dl"))
    assert findings_by_check(report, "version-consistency") == []


# ============================================================================
# Check: zip layout
# ============================================================================


def test_zip_layout_all_references_present():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(
        version="1.0.0",
        bin=["app.exe", "lib/tool.exe"],
        env_add_path=".",
        extract_dir="app-1.0.0",
        shortcuts=[["app.exe", "App"]],
    )
    report = md.doctor_manifest("zip.json", manifest, transport=transport)
    assert report.findings == []
    assert len(transport.tail_requests) == 1


def test_zip_layout_missing_bin_folder_errors():
    # The esptool class: bin points into a folder the zip does not contain.
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(bin="missing-folder/app.exe")
    report = md.doctor_manifest("zip.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "bin 'missing-folder/app.exe'" in findings[0].message
    assert "'missing-folder'" in findings[0].message


def test_zip_layout_missing_env_add_path_errors():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(env_add_path="no-such-dir")
    report = md.doctor_manifest("zip.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert "env_add_path 'no-such-dir'" in findings[0].message


def test_zip_layout_missing_extract_dir_errors():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(extract_dir="app-9.9.9")
    report = md.doctor_manifest("zip.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert "extract_dir 'app-9.9.9'" in findings[0].message


def test_zip_layout_missing_shortcut_target_errors():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(shortcuts=[["other-dir/app.exe", "App"]])
    report = md.doctor_manifest("zip.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert "shortcuts 'other-dir/app.exe'" in findings[0].message


def test_zip_layout_bin_at_archive_root():
    blob = make_zip_bytes({"tool.exe": b"MZ", "lib/inner.exe": b"MZ"})
    transport = FakeRangeTransport(blob)
    ok = md.doctor_manifest("root.json", zip_manifest(bin="tool.exe"), transport=transport)
    assert findings_by_check(ok, "zip-layout") == []
    bad = md.doctor_manifest("root.json", zip_manifest(bin="nope.exe"), transport=transport)
    assert len(findings_by_check(bad, "zip-layout")) == 1


def test_zip_layout_bins_resolve_relative_to_extract_dir():
    # bucket/cache-relocator.json class: extract_dir contents become the app
    # root, so bin lives directly under the extract_dir folder in the archive.
    blob = make_zip_bytes({"64-bit/cacherelocator.exe": b"MZ", "32-bit/tool.exe": b"MZ"})
    transport = FakeRangeTransport(blob)
    manifest = zip_manifest(
        bin="cacherelocator.exe",
        shortcuts=[["cacherelocator.exe", "Cache Relocator"]],
        extract_dir="64-bit",
    )
    report = md.doctor_manifest("relocated.json", manifest, transport=transport)
    assert report.findings == []


def test_zip_layout_missing_extract_dir_reports_joined_target():
    blob = make_zip_bytes({"64-bit/cacherelocator.exe": b"MZ"})
    transport = FakeRangeTransport(blob)
    manifest = zip_manifest(bin="cacherelocator.exe", extract_dir="missing-dir")
    report = md.doctor_manifest("missing.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 2
    assert all("'missing-dir'" in f.message for f in findings)


def test_zip_layout_installer_script_relocates_files_without_false_positive():
    # bucket/victoria.json class: installer.script moves the versioned folder
    # content to the app root before shims are created - unverifiable, so the
    # check must stand down with an info note instead of flagging bin.
    blob = make_zip_bytes({"Victoria537/Victoria.exe": b"MZ"})
    transport = FakeRangeTransport(blob)
    manifest = zip_manifest(
        bin="Victoria.exe",
        shortcuts=[["Victoria.exe", "Victoria"]],
        installer={"script": "Get-ChildItem ... | Move-Item -Destination $dir"},
    )
    report = md.doctor_manifest("installer.json", manifest, transport=transport)
    assert findings_by_check(report, "zip-layout") == [
        md.Finding(
            "info",
            "zip-layout",
            "installer.script may relocate files; bin/env_add_path/shortcuts "
            "were not verified against the zip layout",
        )
    ]
    assert report.passed()


def test_zip_layout_non_zip_url_skipped():
    transport = FakeRangeTransport(GOOD_ZIP)
    report = md.doctor_manifest("exe.json", exe_manifest(), transport=transport)
    assert report.findings == []
    assert transport.tail_requests == []
    assert transport.range_requests == []


def test_zip_layout_scoop_rename_fragment_still_checked():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = zip_manifest(url="https://example.com/app-1.2.3.zip#/renamed.zip")
    manifest["bin"] = "app-1.0.0/app.exe"
    report = md.doctor_manifest("frag.json", manifest, transport=transport)
    assert transport.tail_requests == [("https://example.com/app-1.2.3.zip", md.TAIL_FETCH_SIZE)]
    assert report.findings == []


def test_zip_layout_reports_location_per_architecture():
    transport = FakeRangeTransport(GOOD_ZIP)
    manifest = exe_manifest(
        architecture={
            "32bit": {"url": "https://example.com/app-x86.zip", "hash": HASH_OK},
            "64bit": {"url": "https://example.com/app-x64.zip", "hash": HASH_OK},
        },
        bin="missing-folder/app.exe",
    )
    del manifest["url"]
    report = md.doctor_manifest("multi.json", manifest, transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 2
    assert any(f.message.startswith("architecture.32bit.url") for f in findings)
    assert any(f.message.startswith("architecture.64bit.url") for f in findings)


def test_zip_layout_dead_url_is_error():
    transport = FakeRangeTransport(
        GOOD_ZIP, fail=md.ZipUrlNotFoundError("https://example.com/app.zip", 404)
    )
    report = md.doctor_manifest("dead.json", zip_manifest(), transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "404" in findings[0].message
    assert not report.passed()


def test_zip_layout_network_failure_is_cannot_check_not_failure():
    transport = FakeRangeTransport(GOOD_ZIP, fail=md.ZipListingError("connection reset"))
    report = md.doctor_manifest("net.json", zip_manifest(), transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert "cannot check" in findings[0].message
    assert report.passed()


def test_zip_layout_zip64_falls_back_to_cannot_check():
    transport = FakeRangeTransport(GOOD_ZIP, fail=md.Zip64ListingError("zip64"))
    report = md.doctor_manifest("z64.json", zip_manifest(), transport=transport)
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert report.passed()


# ============================================================================
# HttpRangeTransport with mocked requests
# ============================================================================


def make_response(status_code, content):
    def raise_for_status():
        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}")

    return SimpleNamespace(
        status_code=status_code, content=content, raise_for_status=raise_for_status
    )


def patch_requests(monkeypatch, responses):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        response = responses(url) if callable(responses) else responses
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(md, "requests", SimpleNamespace(get=fake_get))
    return calls


def test_transport_honors_206_ranges(monkeypatch):
    patch_requests(monkeypatch, lambda url: make_response(206, GOOD_ZIP[-32:]))
    transport = md.HttpRangeTransport()
    assert transport.fetch_tail("https://example.com/app.zip") == GOOD_ZIP[-32:]

    patch_requests(monkeypatch, lambda url: make_response(206, GOOD_ZIP[10:20]))
    assert transport.fetch_range("https://example.com/app.zip", 10, 19) == GOOD_ZIP[10:20]


def test_transport_tolerates_servers_ignoring_range(monkeypatch):
    patch_requests(monkeypatch, lambda url: make_response(200, GOOD_ZIP))
    transport = md.HttpRangeTransport()
    assert transport.fetch_tail("https://example.com/app.zip") == GOOD_ZIP[-md.TAIL_FETCH_SIZE :]
    assert transport.fetch_range("https://example.com/app.zip", 4, 9) == GOOD_ZIP[4:10]


def test_transport_404_raises_not_found(monkeypatch):
    patch_requests(monkeypatch, lambda url: make_response(404, b""))
    transport = md.HttpRangeTransport()
    with pytest.raises(md.ZipUrlNotFoundError):
        transport.fetch_tail("https://example.com/app.zip")


def test_transport_server_error_is_listing_error(monkeypatch):
    patch_requests(monkeypatch, lambda url: make_response(500, b"boom"))
    transport = md.HttpRangeTransport()
    with pytest.raises(md.ZipListingError):
        transport.fetch_tail("https://example.com/app.zip")


def test_transport_network_error_is_listing_error(monkeypatch):
    patch_requests(monkeypatch, ConnectionError("refused"))
    transport = md.HttpRangeTransport()
    with pytest.raises(md.ZipListingError):
        transport.fetch_tail("https://example.com/app.zip")


# ============================================================================
# doctor_bucket runner
# ============================================================================


def test_bucket_all_pass_exit_zero(tmp_path, capsys):
    bucket = write_bucket(
        tmp_path,
        {
            "good": exe_manifest(),
            "also-good": exe_manifest(version="2.0.0", hash=HASH_OK),
        },
    )
    assert md.doctor_bucket(bucket) == 0
    out = capsys.readouterr().out
    assert "good.json: PASS" in out
    assert "also-good.json: PASS" in out
    assert "0 errors" in out


def test_bucket_error_exit_one(tmp_path, capsys):
    bucket = write_bucket(tmp_path, {"dirty": exe_manifest(url="http://example.com/app.exe")})
    assert md.doctor_bucket(bucket) == 1
    out = capsys.readouterr().out
    assert "dirty.json: FAIL" in out
    assert "[error]" in out


def test_bucket_warnings_pass_by_default_and_fail_with_flag(tmp_path):
    bucket = write_bucket(tmp_path, {"warned": exe_manifest(hash=SHA256_HEX)})
    assert md.doctor_bucket(bucket) == 0
    assert md.doctor_bucket(bucket, warnings_as_errors=True) == 1


def test_bucket_invalid_json_manifest_is_error(tmp_path):
    bucket = write_bucket(tmp_path, {"broken": "{not json"})
    assert md.doctor_bucket(bucket) == 1


def test_bucket_names_filter(tmp_path, capsys):
    bucket = write_bucket(
        tmp_path,
        {
            "wanted": exe_manifest(),
            "unwanted": exe_manifest(url="http://example.com/app.exe"),
        },
    )
    assert md.doctor_bucket(bucket, names=["wanted"]) == 0
    out = capsys.readouterr().out
    assert "wanted.json" in out
    assert "unwanted.json" not in out


def test_structured_only_emits_single_json_summary(tmp_path, capsys, monkeypatch):
    bucket = write_bucket(
        tmp_path,
        {
            "clean": exe_manifest(),
            "dirty": exe_manifest(url="http://example.com/app.exe"),
        },
    )
    monkeypatch.setenv("STRUCTURED_ONLY", "1")
    assert md.doctor_bucket(bucket) == 1
    out = capsys.readouterr().out.strip()
    lines = out.splitlines()
    assert len(lines) == 1, "structured output must be a single JSON line"
    payload = json.loads(lines[0])
    assert payload["command"] == "doctor"
    assert payload["manifests"] == 2
    assert payload["passed"] == 1
    assert payload["failed"] == 1
    assert payload["errors"] == 1
    statuses = {r["manifest"]: r["status"] for r in payload["results"]}
    assert statuses == {"clean.json": "PASS", "dirty.json": "FAIL"}


# ============================================================================
# End-to-end: automate-scoop.py doctor
# ============================================================================


def run_doctor_cli(args, env=None):
    return subprocess.run(
        [sys.executable, str(AUTOMATE_SCOOP), "doctor", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(REPO_ROOT),
        env=env,
    )


def test_cli_doctor_passes_clean_bucket(tmp_path):
    bucket = write_bucket(tmp_path, {"clean": exe_manifest()})
    result = run_doctor_cli(["--bucket-dir", str(bucket)])
    assert result.returncode == 0
    assert "clean.json: PASS" in result.stdout


def test_cli_doctor_fails_dirty_bucket(tmp_path):
    bucket = write_bucket(tmp_path, {"dirty": exe_manifest(url="http://example.com/app.exe")})
    result = run_doctor_cli(["--bucket-dir", str(bucket)])
    assert result.returncode == 1
    assert "dirty.json: FAIL" in result.stdout


def test_cli_doctor_warnings_as_errors(tmp_path):
    bucket = write_bucket(tmp_path, {"warned": exe_manifest(hash=SHA256_HEX)})
    assert run_doctor_cli(["--bucket-dir", str(bucket)]).returncode == 0
    flagged = run_doctor_cli(["--bucket-dir", str(bucket), "--warnings-as-errors"])
    assert flagged.returncode == 1


def test_cli_doctor_structured_only(tmp_path):
    bucket = write_bucket(tmp_path, {"clean": exe_manifest()})
    env = dict(os.environ)
    env["STRUCTURED_ONLY"] = "1"
    result = run_doctor_cli(["--bucket-dir", str(bucket)], env=env)
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["command"] == "doctor"
    assert payload["passed"] == 1


# ============================================================================
# 7z layout checks (full download + 7z binary; skipped when 7z is absent)
# ============================================================================

import shutil

SEVEN_ZIP = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
needs_7z = pytest.mark.skipif(SEVEN_ZIP is None, reason="no 7z binary available")


def make_7z_bytes(files: dict) -> bytes:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "test.7z"
        for rel, content in files.items():
            target = Path(tmp) / "src" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        subprocess.run(
            [SEVEN_ZIP, "a", str(archive), f"{tmp}/src/*"],
            check=True,
            capture_output=True,
        )
        return archive.read_bytes()


@needs_7z
def test_7z_layout_verifies_references(monkeypatch):
    archive = make_7z_bytes({"app-1.2.3/app.exe": b"MZ", "app-1.2.3/lib/tool.exe": b"MZ"})

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": str(len(archive))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, chunk_size=65536):
            yield archive

        def close(self):
            pass

    def fake_get(url, **kwargs):
        if kwargs.get("stream"):
            return FakeResponse()
        raise AssertionError("expected stream=True")

    monkeypatch.setattr(md, "_requests_get", fake_get)
    manifest = zip_manifest(
        version="1.2.3",
        url="https://example.com/downloads/app-1.2.3.7z",
        bin=["app.exe", "lib/tool.exe"],
        extract_dir="app-1.2.3",
    )
    report = md.doctor_manifest("seven.json", manifest, transport=FakeRangeTransport(GOOD_ZIP))
    assert [f for f in report.findings if f.check == "zip-layout"] == []


@needs_7z
def test_7z_layout_missing_reference_errors(monkeypatch):
    archive = make_7z_bytes({"app-1.2.3/app.exe": b"MZ"})

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": str(len(archive))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, chunk_size=65536):
            yield archive

        def close(self):
            pass

    monkeypatch.setattr(md, "_requests_get", lambda url, **kw: FakeResponse())
    manifest = zip_manifest(
        version="1.2.3",
        url="https://example.com/downloads/app-1.2.3.7z",
        bin=["nope/missing.exe"],
    )
    report = md.doctor_manifest("seven.json", manifest, transport=FakeRangeTransport(GOOD_ZIP))
    findings = findings_by_check(report, "zip-layout")
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "missing.exe" in findings[0].message


def test_7z_without_binary_cannot_check(monkeypatch):
    monkeypatch.setattr(md, "_find_7z_binary", lambda: None)
    with pytest.raises(md.ZipListingError):
        md.list_7z_entries("https://example.com/app.7z")


# ============================================================================
# Plain-exe bin name checks (the ntoptimizer class)
# ============================================================================


def test_exe_bin_name_mismatch_errors():
    manifest = exe_manifest(url="https://example.com/files/NetOptimizer.exe", bin="Other.exe")
    report = md.doctor_manifest("exe.json", manifest, transport=FakeRangeTransport(GOOD_ZIP))
    findings = findings_by_check(report, "exe-bin-name")
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "NetOptimizer.exe" in findings[0].message


def test_exe_bin_name_matching_passes():
    manifest = exe_manifest(
        url="https://example.com/files/NetOptimizer.exe", bin="NetOptimizer.exe"
    )
    report = md.doctor_manifest("exe.json", manifest, transport=FakeRangeTransport(GOOD_ZIP))
    assert findings_by_check(report, "exe-bin-name") == []


def test_exe_rename_fragment_satisfies_bin():
    manifest = exe_manifest(
        url="https://example.com/files/setup.exe#/NetOptimizer.exe", bin="NetOptimizer.exe"
    )
    report = md.doctor_manifest("exe.json", manifest, transport=FakeRangeTransport(GOOD_ZIP))
    assert findings_by_check(report, "exe-bin-name") == []
