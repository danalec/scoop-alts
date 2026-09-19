#!/usr/bin/env python3
"""
Shared Version Detection Module
Provides reusable functions for version detection and URL construction.
"""

import re
import os
import sys
import json
import time
import requests
import hashlib
import tempfile
import subprocess
import logging
import shutil
import zipfile
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pathlib import Path
from dataclasses import dataclass, field

# Optional Playwright support
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Optional semantic version parsing
if TYPE_CHECKING:
    from packaging.version import Version as _PVersion, InvalidVersion as _PInvalid
else:
    try:
        from packaging.version import Version as _PVersion, InvalidVersion as _PInvalid
    except Exception:  # pragma: no cover
        _PVersion = None  # type: ignore[assignment]
        _PInvalid = Exception  # type: ignore[assignment]

# Optional adapters/retries for robust and efficient HTTP requests
if TYPE_CHECKING:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
else:
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except Exception:  # pragma: no cover - environment may not have urllib3
        HTTPAdapter = None  # type: ignore[assignment]
        Retry = None  # type: ignore[assignment]

# Optional caching support; used only if available and enabled by caller
try:
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

DEFAULT_TIMEOUT = 15  # seconds

# Release-metadata cache (Feature: avoid re-fetching GitHub API responses every run)
RELEASE_CACHE_TTL_DEFAULT = 1800  # seconds


def _release_cache_path() -> Path:
    """On-disk location of the release-metadata cache (repo-local, gitignored)."""
    return Path(__file__).resolve().parent.parent / ".temp" / "release-cache.json"


def _running_under_test() -> bool:
    """True when imported under a test runner (pytest).

    The on-disk release cache defaults to disabled in that case so mocked
    sessions are always consulted; production runs (pytest not imported) get
    the real default TTL.
    """
    return "pytest" in sys.modules


def _release_cache_ttl() -> float:
    """Freshness window for cached release metadata, in seconds (env-tunable).

    ``RELEASE_CACHE_TTL`` overrides the default of 1800 seconds; a TTL of 0
    disables caching. Under test runners the cache defaults to disabled unless
    the env var is set explicitly.
    """
    raw = os.environ.get("RELEASE_CACHE_TTL")
    if raw is None:
        if _running_under_test():
            return 0.0
        return float(RELEASE_CACHE_TTL_DEFAULT)
    try:
        return float(raw)
    except ValueError:
        return float(RELEASE_CACHE_TTL_DEFAULT)


def _read_release_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load the release cache; a missing or corrupt file yields an empty cache."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    entries: Dict[str, Dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, dict):
            entries[key] = value
    return entries


def _write_release_cache_entry(path: Path, key: str, body: Any) -> None:
    """Persist one cache entry; write failures are silent by design."""
    try:
        entries = _read_release_cache(path)
        entries[key] = {"fetched_at": time.time(), "body": body}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if os.environ.get("AUTOMATION_LIB_SILENT") == "1":

    def _noop_print(*args, **kwargs):
        return None

    print = _noop_print


def get_session(
    *,
    retries: int = 2,
    backoff_factor: float = 0.3,
    pool_connections: int = 10,
    pool_maxsize: int = 20,
    use_cache: bool = False,
    cache_expire_seconds: int = 1800,
) -> requests.Session:
    """Create a configured HTTP session with pooling, retries, and optional caching.

    Args:
        retries: Total retry attempts for transient errors
        backoff_factor: Backoff factor for retry delays
        pool_connections: Connection pool size per host
        pool_maxsize: Max pooled connections
        use_cache: Enable requests-cache if available
        cache_expire_seconds: Cache TTL when using requests-cache

    Returns:
        Configured requests.Session (or CachedSession if caching enabled)
    """
    if use_cache and requests_cache is not None:
        session: requests.Session = requests_cache.CachedSession(
            cache_name="version-detector-cache",
            backend="sqlite",
            expire_after=cache_expire_seconds,
        )
    else:
        session = requests.Session()

    # Default headers (prefer compressed responses)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )

    # Configure connection pooling and retries if available
    if HTTPAdapter is not None and Retry is not None:
        retry = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

    return session


@dataclass
class VersionResult:
    """Result of version detection including captured groups"""

    version: str
    match_groups: Dict[str, str] = field(default_factory=dict)


class VersionDetector:
    """Shared class for version detection and URL construction"""

    def __init__(self):
        # Use shared session with pooling, retries, and compressed responses
        # Enable cache if env variables request it
        use_cache = bool(
            os.environ.get("AUTOMATION_HTTP_CACHE") or os.environ.get("REQUESTS_CACHE")
        )
        ttl = int(os.environ.get("AUTOMATION_HTTP_CACHE_TTL", "1800"))
        self.session = get_session(use_cache=use_cache, cache_expire_seconds=ttl)
        # Per-URL conditional request metadata and cached parsed version
        self._version_cache: Dict[str, Dict[str, Any]] = {}

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Fetch content using Playwright"""
        if not sync_playwright:
            return None

        try:
            logger.info(f"Fetching with Playwright: {url}")
            print(f"🎭 Fetching with Playwright: {url}")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                # Set a realistic user agent
                page.set_extra_http_headers(
                    {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait a bit for dynamic content
                page.wait_for_timeout(2000)
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error(f"Playwright fetch failed: {e}")
            print(f"⚠️  Playwright fetch failed: {e}")
            return None

    def fetch_latest_version(
        self, homepage_url: str, version_patterns: List[str]
    ) -> Optional[VersionResult]:
        """
        Fetch the latest version from a homepage using provided regex patterns

        Args:
            homepage_url: URL to scrape for version information
            version_patterns: List of regex patterns to match version numbers

        Returns:
            Latest VersionResult if found, None otherwise
        """
        try:
            logger.info(f"Scraping version from: {homepage_url}")
            print(f"🔍 Scraping version from: {homepage_url}")

            # Use conditional headers when we have prior metadata
            headers: Dict[str, str] = {}
            cached = self._version_cache.get(homepage_url)
            if cached:
                if cached.get("etag"):
                    headers["If-None-Match"] = cached["etag"]
                if cached.get("last_modified"):
                    headers["If-Modified-Since"] = cached["last_modified"]

            response = self.session.get(homepage_url, timeout=DEFAULT_TIMEOUT, headers=headers)
            response.raise_for_status()

            # If not modified, return cached version immediately
            if response.status_code == 304 and cached and cached.get("version"):
                logger.info("Using cached version (304 Not Modified)")
                print("ℹ️  Not modified (304), using cached version")
                # When using cache, we don't have new match groups unless we cached them.
                # For now, return empty groups or retrieve from cache if I decide to store them.
                return VersionResult(
                    version=cached["version"], match_groups=cached.get("match_groups", {})
                )

            content = response.text

            # Try each pattern and collect all matches
            all_results: List[VersionResult] = []
            for pattern in version_patterns:
                # Use finditer to capture named groups
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    groups = match.groupdict()

                    # Determine the version string
                    # If "version" group exists, use it. Otherwise use the first group.
                    if "version" in groups:
                        v = groups["version"]
                    elif match.groups():
                        v = match.group(1)
                    else:
                        continue  # No capturing groups, skip

                    # Basic sanity filter: must start with a digit
                    if v and v[0].isdigit():
                        all_results.append(VersionResult(version=v, match_groups=groups))

            if all_results:
                # Prefer semantic version ordering when available
                best_result: Optional[VersionResult] = None

                # Sort based on version string
                def get_version_obj(res: VersionResult):
                    if _PVersion:
                        try:
                            return _PVersion(res.version)
                        except _PInvalid:
                            pass
                    return None

                # Fallback key
                def version_key(res: VersionResult) -> List[int]:
                    parts = re.split(r"[._-]", res.version)
                    key: List[int] = []
                    for p in parts:
                        try:
                            key.append(int(p))
                        except ValueError:
                            # Non-numeric parts sort after numeric
                            key.append(-1)
                    return key

                if _PVersion:
                    # Filter out invalid versions if using packaging.version
                    valid_versions = [r for r in all_results if get_version_obj(r) is not None]
                    if valid_versions:
                        best_result = sorted(
                            valid_versions, key=lambda r: _PVersion(r.version), reverse=True
                        )[0]

                if not best_result:
                    best_result = sorted(all_results, key=version_key, reverse=True)[0]

                logger.info(f"Found version: {best_result.version}")
                print(f"✅ Found version: {best_result.version}")

                # Store conditional metadata and parsed version
                self._version_cache[homepage_url] = {
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                    "version": best_result.version,
                    "match_groups": best_result.match_groups,
                }
                return best_result

            logger.warning("No version found with any pattern using requests")

            # Try Playwright fallback if available and requests failed to find version
            if sync_playwright:
                print("⚠️  No version found with requests, trying Playwright...")
                pw_content = self._fetch_with_playwright(homepage_url)
                if pw_content:
                    # Retry patterns on Playwright content
                    all_results = []
                    for pattern in version_patterns:
                        for match in re.finditer(pattern, pw_content, re.IGNORECASE):
                            groups = match.groupdict()
                            if "version" in groups:
                                v = groups["version"]
                            elif match.groups():
                                v = match.group(1)
                            else:
                                continue

                            if v and v[0].isdigit():
                                all_results.append(VersionResult(version=v, match_groups=groups))

                    if all_results:
                        # Reuse sorting logic (simplified here or extracted later)
                        def version_key_pw(res: VersionResult) -> List[int]:
                            parts = re.split(r"[._-]", res.version)
                            key: List[int] = []
                            for p in parts:
                                try:
                                    key.append(int(p))
                                except ValueError:
                                    key.append(-1)
                            return key

                        # Just use the simple sort for now to avoid code duplication complexity in search/replace
                        # Ideally refactor sorting into a method
                        best_result = sorted(all_results, key=version_key_pw, reverse=True)[0]

                        logger.info(f"Found version with Playwright: {best_result.version}")
                        print(f"✅ Found version with Playwright: {best_result.version}")
                        return best_result

            print("❌ No version found with any pattern")
            # Cache response metadata even when not found, to enable future 304
            self._version_cache[homepage_url] = {
                "etag": response.headers.get("ETag", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "version": "",
            }
            return None

        except requests.RequestException as e:
            page = _GITHUB_RELEASES_PAGE_RE.match(homepage_url)
            if page is not None:
                # GitHub sometimes 406s HTML scrapes from runner IPs; the API
                # path works there, so fall back to /releases/latest. If the
                # fallback yields nothing, surface the original scrape error.
                api_result = self._github_latest_release_fallback(page, version_patterns, e)
                if api_result is not None:
                    return api_result
                raise
            logger.error(f"Failed to fetch version info from {homepage_url}: {e}")
            print(f"❌ Failed to fetch version info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error during version detection for {homepage_url}: {e}")
            print(f"❌ Error during version detection: {e}")
            return None

    def _github_latest_release_fallback(
        self,
        page: "re.Match[str]",
        version_patterns: List[str],
        original_error: Exception,
    ) -> Optional[VersionResult]:
        """Recover a version via the GitHub API when the HTML scrape failed.

        Fetches ``/repos/<owner>/<repo>/releases/latest`` through the release
        cache and runs the same ``version_patterns`` over the JSON body (the
        ``tag_name``/``html_url`` fields match the usual patterns). Sends an
        explicit bearer token when GITHUB_TOKEN is set. Returns the first
        pattern match, or None when the API call fails or nothing matches (the
        caller then propagates the original scrape error).
        """
        api_url = (
            f"https://api.github.com/repos/{page.group('owner')}/{page.group('repo')}"
            "/releases/latest"
        )
        headers: Optional[Dict[str, str]] = None
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers = {"Authorization": f"Bearer {token}"}
        body = self._cached_api_get(api_url, headers=headers)
        if body is None:
            return None
        content = json.dumps(body, ensure_ascii=False)
        for pattern in version_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                groups = match.groupdict()
                if "version" in groups:
                    version = groups["version"]
                elif match.groups():
                    version = match.group(1)
                else:
                    continue
                if version and version[0].isdigit():
                    response = getattr(original_error, "response", None)
                    status = response.status_code if response is not None else "?"
                    print(f"ℹ️ HTML scrape failed ({status}), fell back to GitHub API: {version}")
                    return VersionResult(version=version, match_groups=groups)
        return None

    def construct_download_url(
        self, url_template: str, version: str, match_groups: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Construct download URL from template and version

        Args:
            url_template: URL template with $version placeholder
            version: Version string to substitute
            match_groups: Optional dictionary of regex match groups for substitution

        Returns:
            Constructed download URL
        """
        if not url_template or not version:
            logger.error("Invalid url_template or version provided")
            raise ValueError("url_template and version cannot be empty")

        download_url = url_template.replace("$version", version)

        if match_groups:
            for name, value in match_groups.items():
                if value:
                    download_url = download_url.replace(f"$match{name}", value)

        logger.info(f"Constructed download URL: {download_url}")
        print(f"📦 Download URL: {download_url}")
        return download_url

    def validate_url(self, url: str) -> bool:
        """Validate if URL is accessible without downloading the full file"""
        try:
            response = self.session.head(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            # If HEAD fails, try GET with range to check first byte
            try:
                headers = {"Range": "bytes=0-0"}
                response = self.session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
                return response.status_code in [200, 206]  # 206 = Partial Content
            except Exception:
                return False

    def _cached_api_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """Fetch a GitHub API/asset URL through the small on-disk release cache.

        The cache lives at ``<repo>/.temp/release-cache.json``, is keyed by
        request URL (query params included), and stores
        ``{"fetched_at": epoch, "body": ...}`` entries reused while younger
        than ``RELEASE_CACHE_TTL`` seconds (default 1800; 0 disables caching,
        which test runners default to). Returns the decoded JSON body, the raw
        text for non-JSON responses, or None on any network/parse failure
        (callers fall back to their default behavior).
        """
        key = url
        if params:
            key = f"{url}?{urlencode(sorted(params.items()))}"
        cache_path = _release_cache_path()
        ttl = _release_cache_ttl()
        if ttl > 0:
            try:
                entry = _read_release_cache(cache_path).get(key)
                if entry is not None and time.time() - float(entry.get("fetched_at", 0)) < ttl:
                    return entry.get("body")
            except Exception:
                pass
        try:
            response = self.session.get(
                url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT
            )
            response.raise_for_status()
            try:
                body: Any = response.json()
            except Exception:
                body = response.text
        except Exception:
            return None
        if ttl > 0:
            _write_release_cache_entry(cache_path, key, body)
        return body

    def _try_github_release_digest(self, url: str) -> Optional[str]:
        """Return the sha256 hex digest GitHub publishes for a release asset.

        Matches ``https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>``
        and queries the release API for the asset's ``digest`` field, avoiding a
        full download. Returns None for non-GitHub URLs, missing digest fields,
        or any API/network failure so callers can fall back to downloading.
        """
        match = re.match(
            r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/releases/download/"
            r"(?P<tag>[^/]+)/(?P<asset>[^/?#]+)$",
            url,
        )
        if not match:
            return None
        asset_name = unquote(match.group("asset"))
        api_url = (
            f"https://api.github.com/repos/{match.group('owner')}/{match.group('repo')}"
            f"/releases/tags/{match.group('tag')}"
        )
        release = self._cached_api_get(api_url)
        if not isinstance(release, dict):
            return None
        try:
            for asset in release.get("assets", []):
                if isinstance(asset, dict) and asset.get("name") == asset_name:
                    digest = str(asset.get("digest") or "")
                    if digest.startswith("sha256:"):
                        hex_digest = digest.split(":", 1)[1].strip().lower()
                        if hex_digest:
                            return hex_digest
                    return None
        except Exception:
            return None
        return None

    def calculate_hash(self, url: str) -> Optional[str]:
        """
        Calculate the SHA256 hash for a download URL with URL validation.

        GitHub release assets prefer the digest published in the release metadata
        so the file does not need to be downloaded at all.

        Args:
            url: URL of file to hash

        Returns:
            SHA256 hash string if successful, None otherwise
        """
        # Strip any fragment (e.g., "#/setup.exe") which is used by Scoop for local renaming
        clean_url = url.split("#", 1)[0]

        # Query strings do not take part in the GitHub release-asset match
        stripped_url = clean_url.split("?", 1)[0]
        digest = self._try_github_release_digest(stripped_url)
        if digest:
            print(f"⚡ Using GitHub-provided digest: {digest}")
            return digest

        # First validate the URL is accessible
        if not self.validate_url(clean_url):
            print(f"❌ URL not accessible: {clean_url}")
            return None

        try:
            print("🔍 Calculating hash...")
            response = self.session.get(clean_url, timeout=max(30, DEFAULT_TIMEOUT), stream=True)
            response.raise_for_status()

            sha256_hash = hashlib.sha256()
            total_bytes = 0
            content_len = int(response.headers.get("Content-Length", "0") or "0")
            if content_len:
                print(f"⬇️  Content-Length: {content_len} bytes")
            for chunk in response.iter_content(chunk_size=8192):
                sha256_hash.update(chunk)
                total_bytes += len(chunk)

            hash_value = sha256_hash.hexdigest()
            print(f"✅ Hash: {hash_value}")
            return hash_value

        except requests.RequestException as e:
            print(f"❌ Failed to calculate hash: {e}")
            return None
        except Exception as e:
            print(f"❌ Error during hash calculation: {e}")
            return None

    def get_version_from_executable(self, download_url: str) -> Optional[str]:
        """
        Download executable and extract version from metadata

        Args:
            download_url: URL to download the executable

        Returns:
            Version string if found, None otherwise
        """
        try:
            v_guess = self.guess_version_from_url(download_url)
            if v_guess:
                print(f"✅ Version guessed from URL: {v_guess}")
                return v_guess

            head_resp = self.head(download_url)
            v_head = self.guess_version_from_headers(head_resp) if head_resp else None
            if v_head:
                print(f"✅ Version guessed from headers: {v_head}")
                return v_head

            v_partial = self.guess_version_from_partial_content(download_url)
            if v_partial:
                print(f"✅ Version inferred from partial content: {v_partial}")
                return v_partial

            if os.environ.get("AUTOMATION_DISABLE_WINMETA") == "1" or sys.platform != "win32":
                return None
            print(f"🔍 Downloading executable to analyze metadata: {download_url}")

            response = self.session.get(download_url, stream=True, timeout=max(30, DEFAULT_TIMEOUT))
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                version = self._extract_version_powershell(temp_path)
                if version:
                    print(f"✅ Found version in executable metadata: {version}")
                    return version

                version = self._extract_version_alternative(temp_path)
                if version:
                    print(f"✅ Found version using alternative method: {version}")
                    return version

                print("❌ No version found in executable metadata")
                return None
            finally:
                temp_path.unlink(missing_ok=True)

        except Exception as e:
            print(f"❌ Error extracting version from executable: {e}")
            return None

    # Utility helpers for efficient network access
    def head(
        self, url: str, *, timeout: int = DEFAULT_TIMEOUT, allow_redirects: bool = True
    ) -> Optional[requests.Response]:
        try:
            return self.session.head(url, timeout=timeout, allow_redirects=allow_redirects)
        except Exception:
            return None

    def get_range_bytes(
        self, url: str, start: int = 0, end: int = 65535, *, timeout: int = DEFAULT_TIMEOUT
    ) -> Optional[bytes]:
        """Fetch a byte range to avoid full downloads when only metadata is needed."""
        try:
            headers = {"Range": f"bytes={start}-{end}"}
            resp = self.session.get(url, headers=headers, timeout=timeout)
            if resp.status_code in (200, 206):
                return resp.content
        except Exception:
            return None
        return None

    def _extract_version_powershell(self, exe_path: Path) -> Optional[str]:
        """Extract version using PowerShell Get-ItemProperty"""
        try:
            cmd = [
                "powershell",
                "-Command",
                f"(Get-ItemProperty '{exe_path}').VersionInfo.FileVersion",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip()
                # Clean up version string
                version = re.sub(r"[^\d\.]", "", version)
                if re.match(r"^\d+\.\d+", version):
                    return version

        except Exception as e:
            print(f"PowerShell version extraction failed: {e}")

        return None

    def _extract_version_alternative(self, exe_path: Path) -> Optional[str]:
        """Alternative version extraction using file properties"""
        try:
            # Try using wmic (Windows Management Instrumentation)
            escaped_path = str(exe_path).replace("\\", "\\\\")
            cmd = [
                "wmic",
                "datafile",
                "where",
                f'name="{escaped_path}"',
                "get",
                "Version",
                "/value",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Version="):
                        version = line.split("=", 1)[1].strip()
                        if version and re.match(r"^\d+\.\d+", version):
                            return version

        except Exception as e:
            print(f"Alternative version extraction failed: {e}")

        return None

    def get_local_executable_version(self, exe_path: Path) -> Optional[str]:
        """Extract a version from a local executable via Windows file metadata."""
        if os.environ.get("AUTOMATION_DISABLE_WINMETA") == "1" or sys.platform != "win32":
            return None
        try:
            if version := self._extract_version_powershell(exe_path):
                print(f"✅ Found version in executable metadata: {version}")
                return version
            if version := self._extract_version_alternative(exe_path):
                print(f"✅ Found version using alternative method: {version}")
                return version
        except Exception as e:
            print(f"❌ Error extracting local executable version: {e}")
        return None

    def guess_version_from_local_file(
        self, file_path: Path, *, first_bytes: int = 262144
    ) -> Optional[str]:
        """Infer a version from a local file by scanning a small decoded byte window."""
        try:
            blob = file_path.read_bytes()[:first_bytes].decode("latin-1", errors="ignore")
            for key in ("FileVersion", "ProductVersion", "Product Version", "Version"):
                if (idx := blob.find(key)) != -1 and (
                    version := self.infer_version(blob[idx : idx + 200])
                ):
                    return version
            return self.infer_version(blob)
        except Exception:
            return None

    def get_msi_version(self, msi_url: str) -> Optional[str]:
        """Extract version from MSI installer"""
        try:
            # 1) Try to guess version from URL/filename
            v_guess = self.guess_version_from_url(msi_url)
            if v_guess:
                print(f"✅ Version guessed from URL: {v_guess}")
                return v_guess

            # 2) Headers-based hints
            head_resp = self.head(msi_url)
            v_head = self.guess_version_from_headers(head_resp) if head_resp else None
            if v_head:
                print(f"✅ Version guessed from headers: {v_head}")
                return v_head

            # 3) Partial content scan for ProductVersion strings
            v_partial = self.guess_version_from_partial_content(msi_url)
            if v_partial:
                print(f"✅ Version inferred from partial content: {v_partial}")
                return v_partial

            # 4) Fallback: full download and query MSI properties
            if os.environ.get("AUTOMATION_DISABLE_WINMETA") == "1" or sys.platform != "win32":
                return None
            print(f"🔍 Downloading MSI to analyze: {msi_url}")

            response = self.session.get(msi_url, stream=True, timeout=60)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".msi") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                # Use msiexec to query MSI properties
                cmd = [
                    "powershell",
                    "-Command",
                    f"Get-MSIProperty -Path '{temp_path}' -Property ProductVersion",
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0 and result.stdout.strip():
                    version = result.stdout.strip()
                    if re.match(r"^\d+\.\d+", version):
                        print(f"✅ Found MSI version: {version}")
                        return version

            finally:
                temp_path.unlink(missing_ok=True)

        except Exception as e:
            print(f"❌ Error extracting MSI version: {e}")

        return None

    def get_zip_version(self, archive_url: str) -> Optional[str]:
        """Extract version from a ZIP archive using names and embedded executables."""
        try:
            if v_guess := self.guess_version_from_url(archive_url):
                print(f"✅ Version guessed from URL: {v_guess}")
                return v_guess

            head_resp = self.head(archive_url)
            if v_head := self.guess_version_from_headers(head_resp) if head_resp else None:
                print(f"✅ Version guessed from headers: {v_head}")
                return v_head

            if v_partial := self.guess_version_from_partial_content(archive_url):
                print(f"✅ Version inferred from partial content: {v_partial}")
                return v_partial

            print(f"🔍 Downloading ZIP to analyze: {archive_url}")
            response = self.session.get(archive_url, stream=True, timeout=60)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                if not zipfile.is_zipfile(temp_path):
                    print("ℹ️  Downloaded file is not a ZIP archive; trying direct file inspection")
                    with temp_path.open("rb") as handle:
                        signature = handle.read(2)

                    if signature == b"MZ":
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as temp_exe:
                            with temp_path.open("rb") as source:
                                shutil.copyfileobj(source, temp_exe)  # type: ignore[misc]
                            exe_path = Path(temp_exe.name)
                        try:
                            if version := self.get_local_executable_version(exe_path):
                                print(f"✅ Found version from executable payload: {version}")
                                return version
                        finally:
                            exe_path.unlink(missing_ok=True)

                    if version := self.guess_version_from_local_file(temp_path):
                        print(f"✅ Found version from non-ZIP payload content: {version}")
                        return version
                    return None

                with zipfile.ZipFile(temp_path) as archive:
                    executable_members = []
                    for name in archive.namelist():
                        if version := self.infer_version(name):
                            print(f"✅ Found ZIP member version: {version}")
                            return version
                        suffix = Path(name).suffix.lower()
                        if suffix in {".exe", ".dll"}:
                            executable_members.append(name)

                    for member in executable_members[:5]:
                        suffix = Path(member).suffix.lower() or ".bin"
                        try:
                            with archive.open(member) as source, tempfile.NamedTemporaryFile(
                                delete=False, suffix=suffix
                            ) as temp_member:
                                temp_member.write(source.read())
                                member_path = Path(temp_member.name)
                            try:
                                if version := self.get_local_executable_version(member_path):
                                    print(
                                        f"✅ Found ZIP executable version from {member}: {version}"
                                    )
                                    return version
                            finally:
                                member_path.unlink(missing_ok=True)
                        except Exception as member_error:
                            print(f"⚠️  Failed to inspect ZIP member {member}: {member_error}")
            finally:
                temp_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"❌ Error extracting ZIP version: {e}")

        return None

    # Lightweight version inference helpers
    def normalize_version(self, value: Optional[str]) -> Optional[str]:
        """Normalize version separators to dots and strip wrapper characters."""
        if not value:
            return None
        candidate = value.strip().strip("._-")
        if not candidate:
            return None
        return re.sub(r"[-_]+", ".", candidate)

    def infer_version(self, text: Optional[str]) -> Optional[str]:
        """Infer a version from text, accepting dot, dash, or underscore separators."""
        if not text:
            return None
        if match := re.search(r"v?(\d+(?:[._-]\d+){1,3})", text):
            return self.normalize_version(match.group(1))
        return None

    def guess_version_from_url(self, url: str) -> Optional[str]:
        """Try to infer version from URL/filename patterns."""
        try:
            fname = url.split("/")[-1]
            candidates = [fname, url]
            for text in candidates:
                if version := self.infer_version(text):
                    return version
        except Exception:
            pass
        return None

    def guess_version_from_headers(self, resp: Optional[requests.Response]) -> Optional[str]:
        """Infer version from Content-Disposition filename or other headers."""
        if not resp:
            return None
        cd = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
        if cd:
            # filename="app-1.2.3.exe"
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                return self.guess_version_from_url(m.group(1))
        return None

    def guess_version_from_partial_content(
        self, url: str, *, first_bytes: int = 262144
    ) -> Optional[str]:
        """Download a small byte range and scan for typical version strings.
        This is best-effort and may not always succeed, but avoids full downloads.
        """
        try:
            data = self.get_range_bytes(url, 0, first_bytes)
            if not data:
                return None
            # Look for strings like FileVersion/ProductVersion and nearby version numbers
            blob = data.decode("latin-1", errors="ignore")
            # Search within 100 chars after the keyword for a version pattern
            for key in ("FileVersion", "ProductVersion", "Product Version", "Version"):
                idx = blob.find(key)
                if idx != -1:
                    window = blob[idx : idx + 200]
                    if version := self.infer_version(window):
                        return version
            # Fallback: any standalone version-looking pattern
            if version := self.infer_version(blob):
                return version
        except Exception:
            return None
        return None

    def get_version_from_download_artifact(
        self, download_url: str, installer_type: Optional[str] = None
    ) -> Optional[str]:
        """Infer a version directly from a stable download URL when scraping fails."""
        if installer_type == "msi" or download_url.lower().endswith(".msi"):
            return self.get_msi_version(download_url)
        if download_url.lower().endswith(".zip"):
            return self.get_zip_version(download_url)
        return self.get_version_from_executable(download_url)

    def supports_direct_download_fallback(self, url_template: str) -> bool:
        """Return True when a download URL can be used without version substitution."""
        return bool(url_template and not re.search(r"\$[A-Za-z_]\w*", url_template))


@dataclass
class SoftwareConfig:
    """Unified configuration for all software packages"""

    name: str
    description: str
    homepage: str
    license: str = "Unknown"
    version_patterns: Optional[List[str]] = None
    version_regex: str = ""  # For backward compatibility
    download_url_template: str = ""
    url_pattern: str = ""  # For backward compatibility
    bin_name: Optional[str] = None
    shortcuts: Optional[List[List[str]]] = None
    installer_type: Optional[str] = None
    extract_dir: Optional[str] = None
    pre_install: Optional[List[str]] = None
    post_install: Optional[List[str]] = None
    # Support for Scoop uninstaller script lines
    uninstaller_script: Optional[List[str]] = None
    # Scoop allows persist to be a string or a list; keep it flexible
    persist: Optional[Any] = None
    architecture: Optional[Dict[str, Any]] = None
    # Per-architecture download URL templates keyed by Scoop arch ("64bit", ...)
    architecture_templates: Optional[Dict[str, str]] = None
    # Upgrade an http:// download URL to https:// before accessibility check/hash
    force_https: bool = False
    # Gate detection on the GitHub release API actually shipping the template asset
    require_release_asset: bool = False
    # Optional release-asset suffix (e.g. ".sha256") published upstream so the
    # computed download hash can be verified against the vendor's checksum
    checksum_asset_suffix: str = ""

    def __post_init__(self):
        """Handle backward compatibility and defaults"""
        # Ensure version_patterns is a list
        if self.version_patterns is None:
            self.version_patterns = []

        # Handle backward compatibility for homepage_url
        if not hasattr(self, "homepage_url"):
            self.homepage_url = self.homepage


# Keep old class name for backward compatibility
SoftwareVersionConfig = SoftwareConfig


def _https_url(url: str) -> str:
    """Return ``url`` with an http:// scheme upgraded to https:// (identity otherwise)."""
    parts = urlsplit(url)
    if parts.scheme.lower() == "http":
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return url


def _tag_version_for_template(tag: str, url_template: str) -> str:
    """Derive the version to substitute into ``url_template`` from a release ``tag``.

    Leading letters are stripped from the tag only when the template already
    literalizes them right before a ``$version`` token (e.g. ``v$version``
    expects tags like ``v1.2.3`` to substitute as ``1.2.3``); otherwise the
    tag is substituted as-is.
    """
    template_prefixes = set(re.findall(r"([A-Za-z]+)(?=\$version)", url_template))
    leading = re.match(r"^([A-Za-z]+)", tag)
    if leading and leading.group(1) in template_prefixes:
        return tag[len(leading.group(1)) :]
    return tag


def _select_release_with_matching_asset(
    config: SoftwareVersionConfig, detector: VersionDetector
) -> Optional[VersionResult]:
    """Pick the newest non-draft, non-prerelease GitHub release whose assets
    contain the exact basename the download URL template expands to.

    Only applies when ``config.homepage`` is a GitHub releases page. Returns
    None on any API/network/parse failure or when no release matches, so the
    caller silently falls back to the standard detection path.
    """
    match = re.match(r"^https://github\.com/([^/]+)/([^/]+)/releases/?$", config.homepage)
    if not match:
        return None
    api_url = f"https://api.github.com/repos/{match.group(1)}/{match.group(2)}/releases"
    releases = detector._cached_api_get(api_url, params={"per_page": 20})
    if not isinstance(releases, list):
        return None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        version = _tag_version_for_template(tag, config.download_url_template)
        candidate_url = config.download_url_template.replace("$version", version)
        basename = urlsplit(candidate_url).path.rsplit("/", 1)[-1]
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        if any(isinstance(asset, dict) and asset.get("name") == basename for asset in assets):
            logger.info("Selected release with matching asset: %s", tag)
            print(f"🎯 Selected release with matching asset: {tag}")
            return VersionResult(version=version, match_groups={})
    return None


_SHA256_HEX_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

# GitHub releases pages whose HTML scrape can fall back to the releases API
_GITHUB_RELEASES_PAGE_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/releases/?(?:[?#].*)?$"
)


def _verify_upstream_checksum(
    detector: VersionDetector,
    download_url: str,
    computed_hash: str,
    checksum_asset_suffix: str,
) -> bool:
    """Compare ``computed_hash`` against an upstream-published checksum asset.

    Looks up the GitHub release backing ``download_url`` and, when it ships an
    asset named ``<basename><checksum_asset_suffix>``, fetches that (small,
    cacheable) file and compares the first 64-hex sha256 it contains against
    the computed hash. Returns False only on a parsed, genuine mismatch; a
    non-GitHub URL, a missing checksum asset, or unparseable content skips
    verification silently and returns True.
    """
    match = re.match(
        r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/releases/download/"
        r"(?P<tag>[^/]+)/(?P<asset>[^/?#]+)$",
        download_url.split("#", 1)[0].split("?", 1)[0],
    )
    if not match:
        return True
    checksum_name = unquote(match.group("asset")) + checksum_asset_suffix
    api_url = (
        f"https://api.github.com/repos/{match.group('owner')}/{match.group('repo')}"
        f"/releases/tags/{match.group('tag')}"
    )
    release = detector._cached_api_get(api_url)
    if not isinstance(release, dict):
        return True
    assets = release.get("assets")
    if not isinstance(assets, list):
        return True
    checksum_url: Optional[str] = None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == checksum_name:
            candidate = asset.get("browser_download_url")
            if isinstance(candidate, str) and candidate:
                checksum_url = candidate
                break
    if not checksum_url:
        return True
    content = detector._cached_api_get(checksum_url)
    if not isinstance(content, str):
        return True
    parsed = _SHA256_HEX_RE.search(content)
    if not parsed:
        return True
    expected = parsed.group(0).lower()
    actual = re.sub(r"^sha256:", "", computed_hash.strip(), flags=re.IGNORECASE).lower()
    if expected == actual:
        print("✅ Upstream checksum verified")
        return True
    print("❌ Upstream checksum mismatch")
    return False


def get_version_info(
    config: SoftwareVersionConfig, current_version: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get complete version information for a software package

    Args:
        config: Software configuration object
        current_version: Version already recorded in the manifest; when it
            matches the detected version the download/hash is skipped and the
            returned dict carries ``hash: None``

    Returns:
        Dictionary with version, download_url, and hash if successful
    """
    detector = VersionDetector()

    # Optionally gate on a GitHub release that actually ships the template asset
    result: Optional[VersionResult] = None
    if config.require_release_asset:
        result = _select_release_with_matching_asset(config, detector)

    # Get latest version
    if result is None:
        result = detector.fetch_latest_version(config.homepage, config.version_patterns)
    match_groups: Dict[str, str] = {}
    if result:
        version = result.version
        match_groups = result.match_groups
        download_url = detector.construct_download_url(
            config.download_url_template, version, match_groups
        )
    elif detector.supports_direct_download_fallback(config.download_url_template):
        download_url = config.download_url_template
        version = detector.get_version_from_download_artifact(download_url, config.installer_type)
        if not version:
            return None
        print(f"ℹ️  Falling back to direct download version detection: {version}")
    else:
        return None

    # Upgrade http:// download URLs before the accessibility check/hash
    if config.force_https:
        download_url = _https_url(download_url)

    # Skip the download and hash calculation entirely when the version is
    # unchanged — the caller will not consume a hash in that case anyway.
    if current_version is not None and current_version == version:
        print(f"ℹ️  Version unchanged ({version}); skipping hash calculation")
        return {"version": version, "download_url": download_url, "hash": None}

    # Calculate hash
    hash_value = detector.calculate_hash(download_url)
    if not hash_value:
        return None

    # Optionally verify the computed hash against an upstream checksum asset
    if config.checksum_asset_suffix:
        if not _verify_upstream_checksum(
            detector, download_url, hash_value, config.checksum_asset_suffix
        ):
            return None

    return {"version": version, "download_url": download_url, "hash": hash_value}


# Common version patterns that can be reused
COMMON_VERSION_PATTERNS = {
    "standard": [
        r"Version:?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)",
        r"v\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)",
        r"([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)\s*(?:version|release)",
    ],
    "github_release": [
        r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
        r"releases/tag/v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ],
    "download_link": [
        r"download.*?([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*,\s*Size:",
    ],
}


def create_software_config_from_manifest(manifest_path: Path) -> Optional[SoftwareVersionConfig]:
    """
    Create a SoftwareVersionConfig from an existing Scoop manifest

    Args:
        manifest_path: Path to the manifest JSON file

    Returns:
        SoftwareVersionConfig object if successful
    """
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # Extract information from manifest
        name = manifest_path.stem
        homepage = manifest.get("homepage", "")

        # Get checkver configuration
        checkver = manifest.get("checkver", {})
        if isinstance(checkver, dict):
            homepage_url = checkver.get("url", homepage)
            version_regex = checkver.get("regex", checkver.get("re", ""))
        else:
            homepage_url = homepage
            version_regex = str(checkver) if checkver else ""

        # Get autoupdate configuration
        autoupdate = manifest.get("autoupdate", {})
        download_url_template = autoupdate.get("url", "")

        # Build version patterns
        version_patterns = []
        if version_regex:
            version_patterns.append(version_regex)

        # Add common patterns as fallback
        version_patterns.extend(COMMON_VERSION_PATTERNS["standard"])

        return SoftwareVersionConfig(
            name=name,
            homepage=homepage_url,
            version_patterns=version_patterns,
            download_url_template=download_url_template,
            description=manifest.get("description", ""),
            license=manifest.get("license", "Unknown"),
            bin_name=manifest.get("bin"),
            shortcuts=manifest.get("shortcuts", []),
        )

    except Exception as e:
        print(f"❌ Failed to create config from manifest {manifest_path}: {e}")
        return None
