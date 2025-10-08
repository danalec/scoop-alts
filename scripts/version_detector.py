#!/usr/bin/env python3
"""
Shared Version Detection Module
Provides reusable functions for version detection and URL construction.
"""

import re
import os
import requests
import hashlib
import tempfile
import subprocess
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass

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
    
    def fetch_latest_version(self, homepage_url: str, version_patterns: List[str]) -> Optional[str]:
        """
        Fetch the latest version from a homepage using provided regex patterns
        
        Args:
            homepage_url: URL to scrape for version information
            version_patterns: List of regex patterns to match version numbers
            
        Returns:
            Latest version string if found, None otherwise
        """
        try:
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
                print("ℹ️  Not modified (304), using cached version")
                return cached['version']

            content = response.text
            
            # Try each pattern until we find a match
            for pattern in version_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    # Normalize match to a string if regex returns tuples of groups
                    first_match = matches[0]
                    version = first_match[0] if isinstance(first_match, (tuple, list)) else first_match
                    print(f"✅ Found version: {version}")
                    # Store conditional metadata and parsed version
                    self._version_cache[homepage_url] = {
                        'etag': response.headers.get('ETag', ''),
                        'last_modified': response.headers.get('Last-Modified', ''),
                        'version': version,
                    }
                    return version
            
            print("❌ No version found with any pattern")
            # Cache response metadata even when not found, to enable future 304
            self._version_cache[homepage_url] = {
                'etag': response.headers.get('ETag', ''),
                'last_modified': response.headers.get('Last-Modified', ''),
                'version': '',
            }
            return None
            
        except requests.RequestException as e:
            print(f"❌ Failed to fetch version info: {e}")
            return None
        except Exception as e:
            print(f"❌ Error during version detection: {e}")
            return None
    
    def construct_download_url(self, url_template: str, version: str) -> str:
        """
        Construct download URL from template and version
        
        Args:
            url_template: URL template with $version placeholder
            version: Version string to substitute
            
        Returns:
            Constructed download URL
        """
        download_url = url_template.replace("$version", version)
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
            for chunk in response.iter_content(chunk_size=8192):
                sha256_hash.update(chunk)
            
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
        # Try cheaper strategies first to avoid full downloads
        try:
            # 1) Try to guess version from URL/filename
            v_guess = self.guess_version_from_url(download_url)
            if v_guess:
                print(f"✅ Version guessed from URL: {v_guess}")
                return v_guess

            # 2) Try HEAD for headers-based hints (e.g., Content-Disposition)
            head_resp = self.head(download_url)
            v_head = self.guess_version_from_headers(head_resp) if head_resp else None
            if v_head:
                print(f"✅ Version guessed from headers: {v_head}")
                return v_head

            # 3) Try partial content scan for common version strings
            v_partial = self.guess_version_from_partial_content(download_url)
            if v_partial:
                print(f"✅ Version inferred from partial content: {v_partial}")
                return v_partial

            # 4) Fallback to full download and metadata extraction
            print(f"🔍 Downloading executable to analyze metadata: {download_url}")

            response = self.session.get(download_url, stream=True, timeout=max(30, DEFAULT_TIMEOUT))
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, suffix='.exe') as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = Path(temp_file.name)

            try:
                # Extract version using PowerShell
                version = self._extract_version_powershell(temp_path)
                if version:
                    print(f"✅ Found version in executable metadata: {version}")
                    return version

                # Fallback: Try alternative methods
                version = self._extract_version_alternative(temp_path)
                if version:
                    print(f"✅ Found version using alternative method: {version}")
                    return version

                print("❌ No version found in executable metadata")
                return None

            finally:
                # Clean up temporary file
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
            cmd = [
                'wmic', 'datafile', 'where', f'name="{str(exe_path).replace("\\", "\\\\")}"',
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

    # Lightweight version inference helpers
    def guess_version_from_url(self, url: str) -> Optional[str]:
        """Try to infer version from URL/filename patterns."""
        try:
            fname = url.split('/')[-1]
            candidates = [fname, url]
            for text in candidates:
                # Common patterns: v1.2.3, 1.2.3, 1.2.3.4, 2024.10
                m = re.search(r'v?(\d+\.\d+(?:\.\d+){0,2})', text)
                if m:
                    return m.group(1)
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
                    m = re.search(r'(\d+\.\d+(?:\.\d+){0,2})', window)
                    if m:
                        return m.group(1)
            # Fallback: any standalone version-looking pattern
            m2 = re.search(r'\b(\d+\.\d+(?:\.\d+){0,2})\b', blob)
            if m2:
                return m2.group(1)
        except Exception:
            return None
        return None

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
    version = detector.fetch_latest_version(config.homepage, config.version_patterns)
    if not version:
        return None
    
    # Construct download URL
    download_url = detector.construct_download_url(config.download_url_template, version)
    
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
        return None