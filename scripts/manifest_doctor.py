"""Deep-lint Scoop manifests for breakage that schema validation misses.

Schema validation (``automate-scoop.py validate``) only checks that required
fields exist. This doctor reproduces the incident classes that slipped past it:

- esptool: ``bin``/``env_add_path`` pointed into a zip folder that did not
  exist, so every shim was dead on install.
- widevinecdm: one architecture entry lagged the manifest ``version`` by two
  major versions, shipping stale metadata.
- veracrypt: top-level ``url``/``hash`` went stale while an architecture block
  carried the real download metadata.
- windhawk: a bare 64-hex hash without the ``sha256:`` prefix.

Checks per manifest (bucket/*.json):

1. ``zip-layout`` - for every ``url`` (top level and per architecture) that
   points at a ``.zip`` over http(s), list the archive's entries with HTTP
   range requests (tail for the End Of Central Directory, then the central
   directory itself) and verify every referenced path - ``bin`` entries,
   ``env_add_path``, ``extract_dir`` and the first element of each
   ``shortcuts`` entry - resolves to a file or folder inside the archive.
   References are resolved relative to ``extract_dir`` when present, and are
   skipped (with a note) when ``installer.script`` may relocate files.
2. ``hash-format`` - ``hash`` must be ``sha256:<64 hex>``; a bare 64-hex hash
   warns (standardize), anything else errors.
3. ``version-consistency`` - every architecture entry url should contain the
   manifest version string (warn otherwise).
4. ``scheme`` - download urls must be https.

Exit code is 0 when nothing worse than a warning was found, 1 otherwise;
``--warnings-as-errors`` upgrades warnings to failures. With STRUCTURED_ONLY=1
all human output is suppressed and a single JSON summary line is printed.
"""

from __future__ import annotations

import json
import os
import sys
import re
import struct
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

try:  # requests is only needed for real (non-mocked) zip layout checks
    import requests
except ImportError:  # pragma: no cover - requests is expected in practice
    requests = None  # type: ignore[assignment]

EOCD_SIGNATURE = b"PK\x05\x06"
CENTRAL_DIRECTORY_SIGNATURE = 0x02014B50
EOCD_MIN_SIZE = 22
EOCD_MAX_COMMENT = 65535
# Tail must cover the maximum-size EOCD (record + 65535-byte comment); ~66KB.
TAIL_FETCH_SIZE = 66 * 1024
CD_HEADER_SIZE = 46
ZIP64_SENTINEL_16 = 0xFFFF
ZIP64_SENTINEL_32 = 0xFFFFFFFF
UTF8_FLAG = 0x800

HASH_PREFIXED_RE = re.compile(r"sha256:[0-9a-fA-F]{64}")
HASH_BARE_RE = re.compile(r"[0-9a-fA-F]{64}")
VERSION_LIKE_RE = re.compile(r"v?\d+\.\d+(?:\.\d+)+")

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


class ZipListingError(Exception):
    """Zip layout could not be determined (zip64, truncated, network, ...)."""


class Zip64ListingError(ZipListingError):
    """The archive uses zip64 extensions; layout cannot be checked."""


class ZipUrlNotFoundError(ZipListingError):
    """The zip url itself is dead (HTTP 404/410) - that *is* a finding."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"{url} returned HTTP {status_code}")
        self.url = url
        self.status_code = status_code


def _requests_get(url: str, **kwargs: Any) -> Any:
    if requests is None:
        raise ZipListingError("the 'requests' package is required for zip layout checks")
    return requests.get(url, **kwargs)


class HttpRangeTransport:
    """Fetch byte ranges over HTTP, tolerating servers that ignore Range."""

    timeout = 30

    def fetch_tail(self, url: str, size: int = TAIL_FETCH_SIZE) -> bytes:
        response = self._get(url, headers={"Range": f"bytes=-{size}"})
        if response.status_code in (404, 410):
            raise ZipUrlNotFoundError(url, response.status_code)
        self._check_status(response)
        content = response.content
        if response.status_code == 206:
            return content
        # Server ignored the Range header and sent the whole file.
        return content[-size:]

    def fetch_range(self, url: str, start: int, end: int) -> bytes:
        response = self._get(url, headers={"Range": f"bytes={start}-{end}"})
        if response.status_code in (404, 410):
            raise ZipUrlNotFoundError(url, response.status_code)
        self._check_status(response)
        content = response.content
        if response.status_code == 206:
            return content
        return content[start : end + 1]

    def _get(self, url: str, headers: Dict[str, str]) -> Any:
        try:
            return _requests_get(url, headers=headers, timeout=self.timeout)
        except ZipListingError:
            raise
        except Exception as exc:
            raise ZipListingError(f"range request failed: {exc}") from exc

    @staticmethod
    def _check_status(response: Any) -> None:
        try:
            response.raise_for_status()
        except Exception as exc:
            raise ZipListingError(f"HTTP {response.status_code}: {exc}") from exc


def parse_eocd(tail: bytes) -> Tuple[int, int, int]:
    """Parse the End Of Central Directory record from a file tail.

    Returns ``(total_entries, cd_size, cd_offset)``. Raises
    :class:`Zip64ListingError` when the archive needs zip64 extensions and
    :class:`ZipListingError` when no valid EOCD is present.
    """
    earliest = max(0, len(tail) - EOCD_MIN_SIZE - EOCD_MAX_COMMENT)
    pos = len(tail) - EOCD_MIN_SIZE
    while pos >= earliest:
        if tail[pos : pos + 4] == EOCD_SIGNATURE:
            fields = struct.unpack_from("<IHHHHIIH", tail, pos)
            comment_len = fields[7]
            # The EOCD must end exactly at the end of the file; this also
            # rejects EOCD signatures embedded in the comment of the real one.
            if pos + EOCD_MIN_SIZE + comment_len == len(tail):
                disk, cd_disk = fields[1], fields[2]
                entries_disk, entries_total = fields[3], fields[4]
                cd_size, cd_offset = fields[5], fields[6]
                if disk != 0 or cd_disk != 0 or entries_disk != entries_total:
                    raise ZipListingError("multi-disk archives cannot be checked")
                if (
                    entries_total == ZIP64_SENTINEL_16
                    or cd_size == ZIP64_SENTINEL_32
                    or cd_offset == ZIP64_SENTINEL_32
                ):
                    raise Zip64ListingError("zip64 archives cannot be checked")
                return entries_total, cd_size, cd_offset
        pos -= 1
    raise ZipListingError("end of central directory not found in tail")


def parse_central_directory(data: bytes, expected_entries: int) -> List[str]:
    """Parse entry names from raw central-directory bytes."""
    entries: List[str] = []
    pos = 0
    for _ in range(expected_entries):
        if pos + CD_HEADER_SIZE > len(data):
            raise ZipListingError("central directory truncated")
        if struct.unpack_from("<I", data, pos)[0] != CENTRAL_DIRECTORY_SIGNATURE:
            raise ZipListingError("central directory signature mismatch")
        fields = struct.unpack_from("<I6H3I5H2I", data, pos)
        flags = fields[3]
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        name_start = pos + CD_HEADER_SIZE
        name_end = name_start + name_len
        if name_end > len(data):
            raise ZipListingError("central directory entry name truncated")
        encoding = "utf-8" if (flags & UTF8_FLAG) else "cp437"
        entries.append(data[name_start:name_end].decode(encoding, errors="replace"))
        pos = name_end + extra_len + comment_len
    return entries


def list_zip_entries(url: str, transport: HttpRangeTransport) -> List[str]:
    """List a remote zip archive's entry names without downloading the file."""
    tail = transport.fetch_tail(url)
    total_entries, cd_size, cd_offset = parse_eocd(tail)
    if cd_size == 0 or total_entries == 0:
        return []
    cd_data = transport.fetch_range(url, cd_offset, cd_offset + cd_size - 1)
    return parse_central_directory(cd_data, total_entries)


@dataclass
class Finding:
    severity: str  # SEVERITY_ERROR | SEVERITY_WARNING | SEVERITY_INFO
    check: str
    message: str


@dataclass
class ManifestReport:
    name: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)

    def passed(self, warnings_as_errors: bool = False) -> bool:
        if self.errors:
            return False
        return not (warnings_as_errors and self.warnings)


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def iter_download_urls(manifest: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Yield ``(location, url)`` for the top-level url and each architecture url."""
    urls: List[Tuple[str, str]] = []
    for index, url in enumerate(_as_str_list(manifest.get("url"))):
        location = "url" if index == 0 else f"url[{index}]"
        urls.append((location, url))
    architecture = manifest.get("architecture")
    if isinstance(architecture, dict):
        for key in sorted(architecture):
            entry = architecture[key]
            if not isinstance(entry, dict):
                continue
            for index, url in enumerate(_as_str_list(entry.get("url"))):
                location = f"architecture.{key}.url"
                if index:
                    location += f"[{index}]"
                urls.append((location, url))
    return urls


def iter_hashes(manifest: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Yield ``(location, hash)`` for the top-level hash and each architecture hash."""
    hashes: List[Tuple[str, Any]] = []
    if "hash" in manifest:
        hashes.append(("hash", manifest["hash"]))
    architecture = manifest.get("architecture")
    if isinstance(architecture, dict):
        for key in sorted(architecture):
            entry = architecture[key]
            if isinstance(entry, dict) and "hash" in entry:
                hashes.append((f"architecture.{key}.hash", entry["hash"]))
    return hashes


def check_scheme(location: str, url: str) -> Optional[Finding]:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme == "https":
        return None
    return Finding(SEVERITY_ERROR, "scheme", f"{location}: download url must be https: {url}")


def check_hash_format(location: str, value: Any) -> Optional[Finding]:
    if not isinstance(value, str):
        return None  # dict/list hashes (e.g. xpath lookups) cannot be checked here
    if HASH_PREFIXED_RE.fullmatch(value):
        return None
    if HASH_BARE_RE.fullmatch(value):
        return Finding(
            SEVERITY_WARNING,
            "hash-format",
            f"{location}: bare 64-hex hash; standardize to 'sha256:{value}'",
        )
    shown = value if len(value) <= 32 else value[:29] + "..."
    return Finding(
        SEVERITY_ERROR,
        "hash-format",
        f"{location}: hash must be 'sha256:<64 hex>' or a bare 64-hex string, got {shown!r}",
    )


def check_arch_version(arch_key: str, url: str, version: str) -> Optional[Finding]:
    if not version or version in url:
        return None
    return Finding(
        SEVERITY_WARNING,
        "version-consistency",
        f"architecture.{arch_key}.url does not contain manifest version "
        f"{version!r} (stale architecture entry?): {url}",
    )


def referenced_paths(manifest: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Yield ``(kind, path)`` for every zip-internal path the manifest references."""
    refs: List[Tuple[str, str]] = []
    for item in _as_str_list(manifest.get("bin")):
        refs.append(("bin", item))
    for item in _as_str_list(manifest.get("env_add_path")):
        refs.append(("env_add_path", item))
    extract_dir = manifest.get("extract_dir")
    if isinstance(extract_dir, str) and extract_dir:
        refs.append(("extract_dir", extract_dir))
    shortcuts = manifest.get("shortcuts")
    if isinstance(shortcuts, list):
        for shortcut in shortcuts:
            if isinstance(shortcut, list) and shortcut and isinstance(shortcut[0], str):
                refs.append(("shortcuts", shortcut[0]))
    return refs


def _normalize(path: str) -> str:
    norm = path.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.strip("/")


def target_folder(path: str) -> str:
    """The path whose existence is verified: the containing folder, or the file
    itself when the reference sits at the archive root."""
    norm = _normalize(path)
    if not norm:
        return ""
    return norm.rsplit("/", 1)[0] if "/" in norm else norm


def resolve_zip_target(path: str, extract_root: str, is_extract_dir: bool = False) -> str:
    """Map a manifest path to its expected location inside the archive.

    With ``extract_dir`` the archive's effective root is that folder, so
    ``bin``/``env_add_path``/``shortcuts`` references resolve underneath it
    (bucket/cache-relocator.json). ``extract_dir`` itself is checked as given.
    """
    norm = _normalize(path)
    if extract_root and not is_extract_dir:
        return f"{extract_root}/{norm}" if norm else extract_root
    return norm


def target_in_listing(
    path: str,
    files: Set[str],
    dirs: Set[str],
    extract_root: str = "",
    is_extract_dir: bool = False,
) -> bool:
    target = target_folder(resolve_zip_target(path, extract_root, is_extract_dir))
    if not target:
        return True  # nothing to check (e.g. "." or empty)
    return target in files or target in dirs


def _listing_index(entries: Sequence[str]) -> Tuple[Set[str], Set[str]]:
    files: Set[str] = set()
    dirs: Set[str] = set()
    for name in entries:
        norm = _normalize(name)
        if not norm:
            continue
        files.add(norm)
        parts = norm.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return files, dirs


def doctor_manifest(
    name: str,
    manifest: Dict[str, Any],
    transport: Optional[HttpRangeTransport] = None,
) -> ManifestReport:
    """Run every deep-lint check against one manifest."""
    report = ManifestReport(name)
    findings = report.findings

    urls = iter_download_urls(manifest)

    # (4) scheme
    for location, url in urls:
        finding = check_scheme(location, url)
        if finding:
            findings.append(finding)

    # (2) hash format
    for location, value in iter_hashes(manifest):
        finding = check_hash_format(location, value)
        if finding:
            findings.append(finding)

    # (3) version consistency (architecture entries + extract_dir)
    version = manifest.get("version")
    if isinstance(version, str) and version:
        architecture = manifest.get("architecture")
        if isinstance(architecture, dict):
            for key in sorted(architecture):
                entry = architecture[key]
                if not isinstance(entry, dict):
                    continue
                for url in _as_str_list(entry.get("url")):
                    finding = check_arch_version(key, url, version)
                    if finding:
                        findings.append(finding)
        extract_dir = manifest.get("extract_dir")
        if isinstance(extract_dir, str) and extract_dir:
            embedded = VERSION_LIKE_RE.findall(extract_dir)
            if embedded and not any(ver in extract_dir for ver in (version, version.lstrip("v"))):
                findings.append(
                    Finding(
                        SEVERITY_WARNING,
                        "version-consistency",
                        f"extract_dir {extract_dir!r} embeds version-like string(s) "
                        f"{embedded} but not the manifest version {version!r} "
                        "(stale extract_dir? - the corecycler install failure class)",
                    )
                )

    # (1) zip layout
    refs = referenced_paths(manifest)
    extract_dir = manifest.get("extract_dir")
    extract_root = _normalize(extract_dir) if isinstance(extract_dir, str) else ""
    installer = manifest.get("installer")
    installer_relocates = isinstance(installer, dict) and bool(installer.get("script"))
    checked_zip_layout = False
    for location, url in urls:
        base_url = url.split("#", 1)[0]  # scoop rename fragments are not remote paths
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme.lower() not in ("http", "https"):
            continue
        if not parts.path.lower().endswith(".zip"):
            continue
        if transport is None:
            transport = HttpRangeTransport()
        try:
            entries = list_zip_entries(base_url, transport)
        except ZipUrlNotFoundError as exc:
            findings.append(
                Finding(SEVERITY_ERROR, "zip-layout", f"{location}: zip url dead: {exc}")
            )
            continue
        except ZipListingError as exc:
            findings.append(
                Finding(SEVERITY_INFO, "zip-layout", f"{location}: cannot check zip layout: {exc}")
            )
            continue
        checked_zip_layout = True
        if not refs:
            continue
        files, dirs = _listing_index(entries)
        archive = parts.path.rsplit("/", 1)[-1] or base_url
        for kind, path in refs:
            if installer_relocates and kind != "extract_dir":
                # installer.script runs before shims are created and may move
                # files anywhere (bucket/victoria.json); not verifiable here.
                continue
            is_extract_dir = kind == "extract_dir"
            if not target_in_listing(path, files, dirs, extract_root, is_extract_dir):
                resolved = resolve_zip_target(path, extract_root, is_extract_dir)
                findings.append(
                    Finding(
                        SEVERITY_ERROR,
                        "zip-layout",
                        f"{location}: {kind} '{path}' -> '{target_folder(resolved)}' "
                        f"not found in {archive}",
                    )
                )
    if (
        checked_zip_layout
        and installer_relocates
        and any(kind != "extract_dir" for kind, _ in refs)
    ):
        findings.append(
            Finding(
                SEVERITY_INFO,
                "zip-layout",
                "installer.script may relocate files; bin/env_add_path/shortcuts "
                "were not verified against the zip layout",
            )
        )

    return report


def _print_report(
    report: ManifestReport, warnings_as_errors: bool, log: Callable[[str], None]
) -> None:
    ok = report.passed(warnings_as_errors)
    log(f"{'✅' if ok else '❌'} {report.name}: {'PASS' if ok else 'FAIL'}")
    icons = {SEVERITY_ERROR: "❌", SEVERITY_WARNING: "⚠️", SEVERITY_INFO: "ℹ️"}
    for finding in report.findings:
        log(f"   {icons.get(finding.severity, '-')} [{finding.severity}] {finding.message}")


def _summary_payload(reports: Sequence[ManifestReport], warnings_as_errors: bool) -> Dict[str, Any]:
    errors = sum(r.errors for r in reports)
    warnings = sum(r.warnings for r in reports)
    passed = sum(1 for r in reports if r.passed(warnings_as_errors))
    return {
        "command": "doctor",
        "manifests": len(reports),
        "passed": passed,
        "failed": len(reports) - passed,
        "errors": errors,
        "warnings": warnings,
        "results": [
            {
                "manifest": r.name,
                "status": "PASS" if r.passed(warnings_as_errors) else "FAIL",
                "findings": [
                    {"severity": f.severity, "check": f.check, "message": f.message}
                    for f in r.findings
                ],
            }
            for r in reports
        ],
    }


def doctor_bucket(
    bucket_dir: Path,
    names: Optional[Sequence[str]] = None,
    warnings_as_errors: bool = False,
    transport: Optional[HttpRangeTransport] = None,
) -> int:
    """Deep-lint every manifest in ``bucket_dir``; returns the process exit code.

    Exit code is 0 when no errors (and, without ``warnings_as_errors``, no
    warnings) were found, 1 otherwise. When STRUCTURED_ONLY=1 all human output
    is suppressed and only the final JSON summary line is printed.
    """
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    # Windows consoles default to cp1252 - status lines contain emoji, which
    # must not crash with UnicodeEncodeError when doctor runs there.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    def log(message: str) -> None:
        if not structured_only:
            print(message)

    paths = sorted(Path(bucket_dir).glob("*.json"))
    if names:
        wanted = set(names)
        paths = [p for p in paths if p.stem in wanted or p.name in wanted]

    log(f"🩺 Doctor: deep-linting {len(paths)} manifest(s) in {bucket_dir}")

    reports: List[ManifestReport] = []
    for path in paths:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            report = ManifestReport(path.name, [Finding(SEVERITY_ERROR, "manifest", str(exc))])
        else:
            report = doctor_manifest(path.name, manifest, transport=transport)
        reports.append(report)
        _print_report(report, warnings_as_errors, log)

    payload = _summary_payload(reports, warnings_as_errors)
    if structured_only:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        log(
            f"📋 Doctor summary: {payload['manifests']} checked | {payload['passed']} passed | "
            f"{payload['failed']} failed | {payload['errors']} errors | {payload['warnings']} warnings"
        )

    if payload["errors"] or (warnings_as_errors and payload["warnings"]):
        return 1
    return 0
