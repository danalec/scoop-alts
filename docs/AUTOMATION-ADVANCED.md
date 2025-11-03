# Advanced Automation Guide

Quick links:
- [Advanced Configuration Examples](#advanced-configuration-examples)
- [Complex Version Detection](#complex-version-detection)
- [Performance Optimization](#performance-optimization)
- [Advanced Troubleshooting](#advanced-troubleshooting)
- [CI/CD Integration](#cicd-integration)
- [Custom Script Templates](#custom-script-templates)
- [Monitoring & Metrics](#monitoring--metrics)
- [Advanced Configuration Management](#advanced-configuration-management)
- [Additional Resources](#additional-resources)

This document contains advanced scenarios, complex configurations, and detailed technical information for the Scoop automation system.

> **Prerequisites**: Complete the basic setup in [AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md) first.

## Navigation

- **[README.md](../README.md)** - Project overview and quick start
- **[AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md)** - Basic setup and common usage
- **[AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md)** - Technical API reference
- **AUTOMATION-ADVANCED.md** (this document) - Advanced scenarios and troubleshooting

## Table of Contents

1. [Advanced Configuration Examples](#advanced-configuration-examples)
2. [Complex Version Detection](#complex-version-detection)
3. [Performance Optimization](#performance-optimization)
4. [Advanced Troubleshooting](#advanced-troubleshooting)
5. [CI/CD Integration](#cicd-integration)
6. [Custom Script Templates](#custom-script-templates)
7. [Monitoring & Metrics](#monitoring--metrics)
8. [Contributing Guidelines](#contributing-guidelines)

## 🔧 Advanced Configuration Examples

### Multi-Architecture Software
```json
{
  "name": "cross-platform-tool",
  "description": "Cross Platform Tool - Works on multiple architectures",
  "homepage": "https://github.com/user/tool/releases/latest",
  "license": "Apache-2.0",
  "version_regex": "tag_name\":\\s*\"v?([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)",
  "architecture": {
    "64bit": {
      "download_url_template": "https://github.com/user/tool/releases/download/v$version/tool-$version-x64.zip",
      "extract_dir": "tool-$version-x64",
      "bin_name": "tool.exe"
    },
    "32bit": {
      "download_url_template": "https://github.com/user/tool/releases/download/v$version/tool-$version-x86.zip",
      "extract_dir": "tool-$version-x86",
      "bin_name": "tool.exe"
    }
  }
}
```

### Complex Installer with Pre/Post Actions
```json
{
  "name": "complex-software",
  "description": "Complex Software - Requires special installation steps",
  "homepage": "https://software.com/download",
  "license": "Commercial",
  "version_regex": "Current Version: ([0-9]+\\.[0-9]+)",
  "download_url_template": "https://software.com/files/installer-$version.msi",
  "installer_type": "msi",
  "pre_install": [
    "Write-Host 'Preparing installation environment...'",
    "Stop-Process -Name 'old-software' -Force -ErrorAction SilentlyContinue"
  ],
  "post_install": [
    "Write-Host 'Configuring software...'",
    "New-Item -Path '$env:APPDATA\\Software' -ItemType Directory -Force",
    "Copy-Item '$dir\\config.ini' '$env:APPDATA\\Software\\' -Force"
  ],
  "shortcuts": [
    ["software.exe", "Complex Software"],
    ["config-tool.exe", "Software Configuration"]
  ]
}
```

## 🔍 Complex Version Detection

### Custom Version Detection Patterns

For software with non-standard version formats:

```python
# Custom version detection in update script
def detect_custom_version():
    """Handle complex version detection scenarios."""

    # Example: Version embedded in JavaScript
    js_pattern = r'version:\s*["\']([0-9]+\.[0-9]+(?:\.[0-9]+)?)["\']'

    # Example: Version in XML/RSS feed
    xml_pattern = r'<version>([^<]+)</version>'

    # Example: Version from API endpoint
    api_url = "https://api.example.com/latest"
    response = requests.get(api_url)
    data = response.json()
    return data.get('version', '').strip('v')
```

### Advanced URL Construction

```python
def build_complex_download_url(version: str) -> str:
    """Build download URLs with complex logic."""

    # Example: Different URL patterns based on version
    if version.startswith('2.'):
        base_url = "https://new-cdn.example.com"
    else:
        base_url = "https://legacy.example.com"

    # Example: URL encoding for special characters
    encoded_version = urllib.parse.quote(version)

    return f"{base_url}/releases/{encoded_version}/app.zip"
```

## 🚀 Performance Optimization

### HTTP Session Reuse
```python
# Optimize HTTP requests with session reuse
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# Reuse session for multiple requests
response1 = session.get(version_url)
response2 = session.get(download_url)
```

### Parallel Processing Configuration
```python
# Configure parallel execution
MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)
TIMEOUT_SECONDS = 30

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(update_script, script) for script in scripts]
    results = [future.result(timeout=TIMEOUT_SECONDS) for future in futures]
```

### Caching Strategies
```python
# Implement response caching
@lru_cache(maxsize=128)
def get_cached_version(url: str) -> str:
    """Cache version detection results."""
    response = requests.get(url, timeout=10)
    return extract_version(response.text)
```

## 🛡️ Advanced Troubleshooting

### Debug Mode Configuration
```bash
# Enable comprehensive debugging
export DEBUG_AUTOMATION=1
export VERBOSE_LOGGING=1

# Run with detailed output
python scripts/automate-scoop.py test --debug --verbose
```

### Custom Error Handling
```python
def robust_version_detection(url: str, patterns: list) -> str:
    """Implement fallback version detection."""

    for attempt, pattern in enumerate(patterns, 1):
        try:
            response = requests.get(url, timeout=10)
            match = re.search(pattern, response.text)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning(f"Pattern {attempt} failed: {e}")
            continue

    raise ValueError("All version detection patterns failed")
```

### Performance Profiling
```python
import cProfile
import pstats

# Profile script execution
profiler = cProfile.Profile()
profiler.enable()

# Your automation code here
run_automation()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(20)
```

## 🔄 CI/CD Integration

### GitHub Actions Workflow
```yaml
name: Automated Package Updates
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:

jobs:
  update-packages:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r scripts/requirements-automation.txt

      - name: Run automation
        run: |
          # Parallel by default; customize workers and providers as needed
          python scripts/update-all.py --workers 6 --github-workers 3 --microsoft-workers 3 --google-workers 4

      - name: Create Pull Request
        if: success()
        uses: peter-evans/create-pull-request@v5
        with:
          title: 'Automated package updates'
          body: 'Updates generated by automation system'
          branch: 'automation/updates'
```

### Advanced Batch Operations
```bash
# Update specific scripts with controlled concurrency
python scripts/update-all.py --scripts corecycler esptool --workers 4

# Update with custom retry logic (exponential backoff built-in)
python scripts/update-all.py --retry 5

# Verbose logging for performance insights; summary includes durations
python scripts/update-all.py --verbose
```

### HTTP caching tips
- When to use: helpful for repeated runs within a short period or to reduce load on provider APIs.
- Recommended TTL: 600–1800 seconds. Default is 1800; shorter TTLs (e.g., 1200) are good when changes may occur frequently.
- What is cached: HTTP GET responses via requests-cache; avoid caching endpoints that require fresh state (e.g., dynamic download URLs that expire quickly).
- Caveats: caching can mask transient availability issues; disable caching when verifying a fresh release.
- How to enable: use `--http-cache --http-cache-ttl <seconds>` on `update-all.py`. The orchestrator propagates env vars `AUTOMATION_HTTP_CACHE=1` and `AUTOMATION_HTTP_CACHE_TTL=<seconds>` to scripts.
- Pair with provider throttling: combine `--github-workers`, `--microsoft-workers`, `--google-workers` limits with caching to stay under rate limits.

```bash
# Enable caching for 20 minutes
python scripts/update-all.py --http-cache --http-cache-ttl 1200

# Disable caching (default)
python scripts/update-all.py --retry 2
```

## 🎨 Custom Script Templates

### Creating Custom Templates
```python
# custom_template.py
CUSTOM_UPDATE_TEMPLATE = '''
#!/usr/bin/env python3
"""
Custom update script for {software_name}
Generated on: {generation_date}
"""

import requests
import json
from pathlib import Path

def update_{software_name_safe}():
    """Update {software_name} with custom logic."""

    # Custom version detection
    version = detect_version_custom()

    # Custom URL construction
    download_url = build_download_url(version)

    # Custom hash calculation
    file_hash = calculate_hash_with_retry(download_url)

    # Update manifest
    update_manifest(version, download_url, file_hash)

if __name__ == "__main__":
    update_{software_name_safe}()
'''
```

## 📊 Monitoring & Metrics

### Success Tracking
```python
# Track automation success rates
class AutomationMetrics:
    def __init__(self):
        self.success_count = 0
        self.failure_count = 0
        self.execution_times = []

    def record_success(self, execution_time: float):
        self.success_count += 1
        self.execution_times.append(execution_time)

    def record_failure(self, error: Exception):
        self.failure_count += 1
        logger.error(f"Automation failed: {error}")

    def get_success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return (self.success_count / total) * 100 if total > 0 else 0
```

### Health Checks
```bash
# Comprehensive health check
python scripts/automate-scoop.py health-check --comprehensive

# Check specific components
python scripts/automate-scoop.py health-check --component version-detection
python scripts/automate-scoop.py health-check --component manifest-generation
```

## 🔧 Advanced Configuration Management

### Environment-Specific Configs
```json
{
  "environments": {
    "development": {
      "timeout": 5,
      "max_retries": 2,
      "parallel_workers": 2
    },
    "production": {
      "timeout": 30,
      "max_retries": 5,
      "parallel_workers": 8
    }
  }
}
```

### Dynamic Configuration Loading
```python
def load_environment_config(env: str = "production") -> dict:
    """Load environment-specific configuration."""

    config_file = Path(f"configs/{env}.json")
    if config_file.exists():
        return json.loads(config_file.read_text())

    # Fallback to default configuration
    return load_default_config()
```

## 📚 Additional Resources

### Advanced Documentation
- [AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md) - Technical reference
- [AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md) - Basic setup and usage

### Performance Tools
- **cProfile**: Python performance profiling
- **memory_profiler**: Memory usage analysis
- **py-spy**: Production profiling tool

### Community Resources
- **GitHub Discussions**: Share advanced configurations
- **Issue Tracker**: Report complex automation scenarios
- **Wiki**: Community-contributed examples

---

[← Back to Docs Index](index.md)
