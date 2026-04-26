#!/usr/bin/env python3
"""
Shared Version Detection Module
Provides reusable functions for version detection and URL construction.
"""

import re
import os
import sys
import requests
import hashlib
import tempfile
import subprocess
import logging
import shutil
import zipfile
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass, field

# Optional Playwright support
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Optional semantic version parsing
try:
    from packaging.version import Version as _PVersion, InvalidVersion as _PInvalid
except Exception:  # pragma: no cover
    _PVersion = None
    _PInvalid = Exception

# Optional adapters/retries for robust and efficient HTTP requests
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - environment may not have urllib3
    HTTPAdapter = None
    Retry = None

# Optional caching support; used only if available and enabled by caller
try:
    import requests_cache  # type: ignore
except Exception:  # pragma: no cover
    requests_cache = None

DEFAULT_TIMEOUT = 15  # seconds

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if os.environ.get('AUTOMATION_LIB_SILENT') == '1':
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
            cache_name='version-detector-cache',
            backend='sqlite',
            expire_after=cache_expire_seconds,
        )
    else:
        session = requests.Session()

    # Default headers (prefer compressed responses)
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })

    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
        })

    # Configure connection pooling and retries if available
    if HTTPAdapter is not None and Retry is not None:
        retry = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(['HEAD', 'GET']),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry,
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)

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
        use_cache = bool(os.environ.get('AUTOMATION_HTTP_CACHE') or os.environ.get('REQUESTS_CACHE'))
        ttl = int(os.environ.get('AUTOMATION_HTTP_CACHE_TTL', '1800'))
        self.session = get_session(use_cache=use_cache, cache_expire_seconds=ttl)
        # Per-URL conditional request metadata and cached parsed version
        self._version_cache: Dict[str, Dict[str, str]] = {}

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
                page.set_extra_http_headers({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })
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

    def fetch_latest_version(self, homepage_url: str, version_patterns: List[str]) -> Optional[VersionResult]:
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
                if cached.get('etag'):
                    headers['If-None-Match'] = cached['etag']
                if cached.get('last_modified'):
                    headers['If-Modified-Since'] = cached['last_modified']

            response = self.session.get(homepage_url, timeout=DEFAULT_TIMEOUT, headers=headers)
            response.raise_for_status()

            # If not modified, return cached version immediately
            if response.status_code == 304 and cached and cached.get('version'):
                logger.info("Using cached version (304 Not Modified)")
                print("ℹ️  Not modified (304), using cached version")
                # When using cache, we don't have new match groups unless we cached them.
                # For now, return empty groups or retrieve from cache if I decide to store them.
                return VersionResult(version=cached['version'], match_groups=cached.get('match_groups', {}))

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
                        continue # No capturing groups, skip
                        
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
                         best_result = sorted(valid_versions, key=lambda r: _PVersion(r.version), reverse=True)[0]
                
                if not best_result:
                    best_result = sorted(all_results, key=version_key, reverse=True)[0]

                logger.info(f"Found version: {best_result.version}")
                print(f"✅ Found version: {best_result.version}")
                
                # Store conditional metadata and parsed version
                self._version_cache[homepage_url] = {
                    'etag': response.headers.get('ETag', ''),
                    'last_modified': response.headers.get('Last-Modified', ''),
                    'version': best_result.version,
                    'match_groups': best_result.match_groups
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

                        if _PVersion:
                             valid_versions = [r for r in all_results if _PVersion and _PVersion(r.version)] # Simplified check
                             # Re-implement proper check if needed, or just use the simplest sort for fallback
                             pass

                        # Just use the simple sort for now to avoid code duplication complexity in search/replace
                        # Ideally refactor sorting into a method
                        best_result = sorted(all_results, key=version_key_pw, reverse=True)[0]
                        
                        logger.info(f"Found version with Playwright: {best_result.version}")
                        print(f"✅ Found version with Playwright: {best_result.version}")
                        return best_result

            print("❌ No version found with any pattern")
            # Cache response metadata even when not found, to enable future 304
            self._version_cache[homepage_url] = {
                'etag': response.headers.get('ETag', ''),
                'last_modified': response.headers.get('Last-Modified', ''),
                'version': '',
            }
            return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch version info from {homepage_url}: {e}")
            print(f"❌ Failed to fetch version info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error during version detection for {homepage_url}: {e}")
            print(f"❌ Error during version detection: {e}")
            return None

    def construct_download_url(self, url_template: str, version: str, match_groups: Optional[Dict[str, str]] = None) -> str:
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
                headers = {'Range': 'bytes=0-0'}
                response = self.session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
                return response.status_code in [200, 206]  # 206 = Partial Content
            except Exception:
                return False

    def calculate_hash(self, url: str) -> Optional[str]:
        """
        Download file and calculate SHA256 hash with URL validation

        Args:
            url: URL of file to download and hash

        Returns:
            SHA256 hash string if successful, None otherwise
        """
        # Strip any fragment (e.g., "#/setup.exe") which is used by Scoop for local renaming
        clean_url = url.split('#', 1)[0]

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
            content_len = int(response.headers.get('Content-Length', '0') or '0')
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

            if os.environ.get('AUTOMATION_DISABLE_WINMETA') == '1' or sys.platform != 'win32':
                return None
            print(f"🔍 Downloading executable to analyze metadata: {download_url}")

            response = self.session.get(download_url, stream=True, timeout=max(30, DEFAULT_TIMEOUT))
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix='.exe') as temp_file:
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
    def head(self, url: str, *, timeout: int = DEFAULT_TIMEOUT, allow_redirects: bool = True) -> Optional[requests.Response]:
        try:
            return self.session.head(url, timeout=timeout, allow_redirects=allow_redirects)
        except Exception:
            return None

    def get_range_bytes(self, url: str, start: int = 0, end: int = 65535, *, timeout: int = DEFAULT_TIMEOUT) -> Optional[bytes]:
        """Fetch a byte range to avoid full downloads when only metadata is needed."""
        try:
            headers = {'Range': f'bytes={start}-{end}'}
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
                'powershell', '-Command',
                f"(Get-ItemProperty '{exe_path}').VersionInfo.FileVersion"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip()
                # Clean up version string
                version = re.sub(r'[^\d\.]', '', version)
                if re.match(r'^\d+\.\d+', version):
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
                'wmic', 'datafile', 'where', f'name="{escaped_path}"',
                'get', 'Version', '/value'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('Version='):
                        version = line.split('=', 1)[1].strip()
                        if version and re.match(r'^\d+\.\d+', version):
                            return version

        except Exception as e:
            print(f"Alternative version extraction failed: {e}")

        return None

    def get_local_executable_version(self, exe_path: Path) -> Optional[str]:
        """Extract a version from a local executable via Windows file metadata."""
        if os.environ.get('AUTOMATION_DISABLE_WINMETA') == '1' or sys.platform != 'win32':
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

    def guess_version_from_local_file(self, file_path: Path, *, first_bytes: int = 262144) -> Optional[str]:
        """Infer a version from a local file by scanning a small decoded byte window."""
        try:
            blob = file_path.read_bytes()[:first_bytes].decode('latin-1', errors='ignore')
            for key in ("FileVersion", "ProductVersion", "Product Version", "Version"):
                if (idx := blob.find(key)) != -1 and (version := self.infer_version(blob[idx: idx + 200])):
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
            if os.environ.get('AUTOMATION_DISABLE_WINMETA') == '1' or sys.platform != 'win32':
                return None
            print(f"🔍 Downloading MSI to analyze: {msi_url}")

            response = self.session.get(msi_url, stream=True, timeout=60)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix='.msi') as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                # Use msiexec to query MSI properties
                cmd = [
                    'powershell', '-Command',
                    f"Get-MSIProperty -Path '{temp_path}' -Property ProductVersion"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode == 0 and result.stdout.strip():
                    version = result.stdout.strip()
                    if re.match(r'^\d+\.\d+', version):
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

            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                if not zipfile.is_zipfile(temp_path):
                    print("ℹ️  Downloaded file is not a ZIP archive; trying direct file inspection")
                    with temp_path.open('rb') as handle:
                        signature = handle.read(2)

                    if signature == b'MZ':
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.exe') as temp_exe:
                            with temp_path.open('rb') as source:
                                shutil.copyfileobj(source, temp_exe)
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
                        if suffix in {'.exe', '.dll'}:
                            executable_members.append(name)

                    for member in executable_members[:5]:
                        suffix = Path(member).suffix.lower() or '.bin'
                        try:
                            with archive.open(member) as source, tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_member:
                                temp_member.write(source.read())
                                member_path = Path(temp_member.name)
                            try:
                                if version := self.get_local_executable_version(member_path):
                                    print(f"✅ Found ZIP executable version from {member}: {version}")
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
        if match := re.search(r'v?(\d+(?:[._-]\d+){1,3})', text):
            return self.normalize_version(match.group(1))
        return None

    def guess_version_from_url(self, url: str) -> Optional[str]:
        """Try to infer version from URL/filename patterns."""
        try:
            fname = url.split('/')[-1]
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
        cd = resp.headers.get('Content-Disposition') or resp.headers.get('content-disposition')
        if cd:
            # filename="app-1.2.3.exe"
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                return self.guess_version_from_url(m.group(1))
        return None

    def guess_version_from_partial_content(self, url: str, *, first_bytes: int = 262144) -> Optional[str]:
        """Download a small byte range and scan for typical version strings.
        This is best-effort and may not always succeed, but avoids full downloads.
        """
        try:
            data = self.get_range_bytes(url, 0, first_bytes)
            if not data:
                return None
            # Look for strings like FileVersion/ProductVersion and nearby version numbers
            blob = data.decode('latin-1', errors='ignore')
            # Search within 100 chars after the keyword for a version pattern
            for key in ("FileVersion", "ProductVersion", "Product Version", "Version"):
                idx = blob.find(key)
                if idx != -1:
                    window = blob[idx: idx + 200]
                    if version := self.infer_version(window):
                        return version
            # Fallback: any standalone version-looking pattern
            if version := self.infer_version(blob):
                return version
        except Exception:
            return None
        return None

    def get_version_from_download_artifact(self, download_url: str, installer_type: Optional[str] = None) -> Optional[str]:
        """Infer a version directly from a stable download URL when scraping fails."""
        if installer_type == 'msi' or download_url.lower().endswith('.msi'):
            return self.get_msi_version(download_url)
        if download_url.lower().endswith('.zip'):
            return self.get_zip_version(download_url)
        return self.get_version_from_executable(download_url)

    def supports_direct_download_fallback(self, url_template: str) -> bool:
        """Return True when a download URL can be used without version substitution."""
        return bool(url_template and not re.search(r'\$[A-Za-z_]\w*', url_template))

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

    def __post_init__(self):
        """Handle backward compatibility and defaults"""
        # Ensure version_patterns is a list
        if self.version_patterns is None:
            self.version_patterns = []

        # Handle backward compatibility for homepage_url
        if not hasattr(self, 'homepage_url'):
            self.homepage_url = self.homepage

# Keep old class name for backward compatibility
SoftwareVersionConfig = SoftwareConfig

def get_version_info(config: SoftwareVersionConfig) -> Optional[Dict[str, Any]]:
    """
    Get complete version information for a software package

    Args:
        config: Software configuration object

    Returns:
        Dictionary with version, download_url, and hash if successful
    """
    detector = VersionDetector()

    # Get latest version
    result = detector.fetch_latest_version(config.homepage, config.version_patterns)
    match_groups: Dict[str, str] = {}
    if result:
        version = result.version
        match_groups = result.match_groups
        download_url = detector.construct_download_url(config.download_url_template, version, match_groups)
    elif detector.supports_direct_download_fallback(config.download_url_template):
        download_url = config.download_url_template
        version = detector.get_version_from_download_artifact(download_url, config.installer_type)
        if not version:
            return None
        print(f"ℹ️  Falling back to direct download version detection: {version}")
    else:
        return None

    # Calculate hash
    hash_value = detector.calculate_hash(download_url)
    if not hash_value:
        return None

    return {
        'version': version,
        'download_url': download_url,
        'hash': hash_value
    }

# Common version patterns that can be reused
COMMON_VERSION_PATTERNS = {
    'standard': [
        r'Version:?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)',
        r'v\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)',
        r'([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:\.[0-9]+)?)\s*(?:version|release)',
    ],
    'github_release': [
        r'tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
        r'releases/tag/v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
    ],
    'download_link': [
        r'download.*?([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
        r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*,\s*Size:',
    ]
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
        import json

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        # Extract information from manifest
        name = manifest_path.stem
        homepage = manifest.get('homepage', '')

        # Get checkver configuration
        checkver = manifest.get('checkver', {})
        if isinstance(checkver, dict):
            homepage_url = checkver.get('url', homepage)
            version_regex = checkver.get('regex', checkver.get('re', ''))
        else:
            homepage_url = homepage
            version_regex = str(checkver) if checkver else ''

        # Get autoupdate configuration
        autoupdate = manifest.get('autoupdate', {})
        download_url_template = autoupdate.get('url', '')

        # Build version patterns
        version_patterns = []
        if version_regex:
            version_patterns.append(version_regex)

        # Add common patterns as fallback
        version_patterns.extend(COMMON_VERSION_PATTERNS['standard'])

        return SoftwareVersionConfig(
            name=name,
            homepage=homepage_url,
            version_patterns=version_patterns,
            download_url_template=download_url_template,
            description=manifest.get('description', ''),
            license=manifest.get('license', 'Unknown'),
            bin_name=manifest.get('bin'),
            shortcuts=manifest.get('shortcuts', [])
        )

    except Exception as e:
        print(f"❌ Failed to create config from manifest {manifest_path}: {e}")
