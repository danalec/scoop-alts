# Scoop Bucket Automation Guide

This guide explains how to use and maintain the comprehensive automation system for this Scoop bucket.

## Overview

The automation system consists of several Python scripts that work together to:
- Detect new software versions using configurable patterns
- Generate and update Scoop manifests with atomic operations
- Maintain package configurations through `software-configs.json`
- Run automated updates with parallel processing and error handling
- Provide template-based script generation for consistency

For detailed technical documentation of all scripts, see [AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md).

## 🎯 Quick Start

### Prerequisites
- **Python 3.8+** with pip
- **Git** for version control
- **Basic understanding** of Scoop manifests and JSON

### 5-Minute Setup
```bash
# 1. Clone the repository
git clone https://github.com/danalec/scoop-alts
cd scoop-alts

# 2. Install dependencies
pip install -r requirements-automation.txt

# 3. Test the system
python scripts/automate-scoop.py test

# 4. Generate everything
python scripts/automate-scoop.py generate-all
```

## 📁 Understanding the File Structure

### JSON Files: Source vs Generated

This automation system uses two distinct types of JSON files that serve different purposes:

#### 📝 `software-configs.json` - Source Configuration (Recipe)
- **Purpose**: Contains the metadata and rules for generating Scoop manifests
- **Location**: `scripts/software-configs.json`
- **Content**: Version detection patterns, download URL templates, installation options
- **Analogy**: Like a recipe that tells you how to cook a meal

```json
{
  "software": [
    {
      "name": "my-app",
      "description": "My awesome application",
      "homepage": "https://example.com/releases",
      "version_regex": "tag_name\":\\s*\"v?([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)\"",
      "download_url_template": "https://example.com/releases/download/v$version/app-$version.exe"
    }
  ]
}
```

#### 📦 `bucket/*.json` - Generated Scoop Manifests (Product)
- **Purpose**: Actual Scoop manifests that users install with `scoop install`
- **Location**: `bucket/my-app.json`
- **Content**: Complete Scoop manifest with current version, hash, download URL
- **Analogy**: Like the cooked meal that's ready to eat

```json
{
  "version": "1.2.3",
  "description": "My awesome application",
  "homepage": "https://example.com",
  "license": "MIT",
  "url": "https://example.com/releases/download/v1.2.3/app-1.2.3.exe",
  "hash": "sha256:abc123...",
  "bin": "app.exe"
}
```

#### 🔄 The Transformation Process
1. **Source** (`software-configs.json`) contains the rules
2. **Automation** applies these rules to detect current versions and generate manifests
3. **Product** (`bucket/*.json`) is created with real version data and file hashes

> **💡 Key Insight**: You edit the source configuration once, and the automation generates/updates the manifests automatically whenever new versions are released.

## 🛠️ Step-by-Step Automation Creation

### 🧙‍♂️ Interactive Wizard (Recommended)

**The easiest way to create automation is using our interactive wizard:**

```bash
# Start the configuration wizard
python scripts/automate-scoop.py wizard

# Keep the JSON configuration file for inspection/reuse (optional)
python scripts/automate-scoop.py wizard --keep-json
```

The wizard will:
- ✅ **Guide you step-by-step** through all required information
- ✅ **Test your configuration** automatically
- ✅ **Generate all files** (manifest + update script)
- ✅ **No JSON editing required** - just answer questions!
- ✅ **Auto-cleanup** temporary files (unless `--keep-json` is used)

**Perfect for beginners** or when you want to avoid manual JSON configuration.

---

### 📝 Manual Configuration (Advanced)

For advanced users who prefer manual control:

#### Creating Your First Automated Package

This walkthrough will guide you through adding a new software package to the automation system from scratch.

#### Step 1: Research Your Software

Before configuring automation, gather essential information:

```bash
# Example: Let's automate "Example App"
# 1. Find the homepage or release page
HOMEPAGE="https://example.com/releases"

# 2. Check the HTML source for version patterns
curl -s "$HOMEPAGE" | grep -i version

# 3. Identify download URL structure
# Look for patterns like: https://example.com/download/app-1.2.3.exe
```

**Key Information to Collect:**
- ✅ **Homepage URL**: Where to scrape version information
- ✅ **Version Pattern**: How version appears in HTML (e.g., "Version 1.2.3")
- ✅ **Download URL**: Template with version placeholder
- ✅ **License**: Software license type
- ✅ **Executable Name**: Main .exe file name

#### Step 2: Configure in JSON (Temporary)

Add your software to `scripts/software-configs.json` (this file will be automatically cleaned up after generation):

```json
{
  "software": [
    // ... existing software ...
    
    {
      "name": "example-app",                    // 📝 Package identifier
      "description": "Example App - Demo application for automation",
      "homepage": "https://example.com/releases",
      "license": "MIT",
      "version_regex": "Version\\s+([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)",
      "download_url_template": "https://example.com/download/app-$version.exe",
      "bin_name": "app.exe",
      "shortcuts": [
        ["app.exe", "Example App"]
      ]
    }
  ]
}
```

**💡 Pro Tips:**
- Use descriptive `name` (becomes filename: `update-example-app.py`)
- Test `version_regex` with [regex101.com](https://regex101.com)
- Verify `download_url_template` manually with actual version

#### Step 3: Generate Automation Files

Create the manifest and update script:

```bash
# Generate for your new software
python scripts/automate-scoop.py generate-all --software example-app

# This creates:
# ✅ bucket/example-app.json (Scoop manifest)
# ✅ scripts/update-example-app.py (Update script)
```

#### Step 4: Test Version Detection

Verify your configuration works:

```bash
# Test the update script in dry-run mode
python scripts/update-example-app.py --dry-run

# Expected output:
# ✅ Current version: 1.2.3
# ✅ Latest version: 1.2.4
# ✅ Download URL: https://example.com/download/app-1.2.4.exe
# ✅ Hash: sha256:abc123...
# 🧪 DRY RUN: Would update manifest
```

#### Step 5: Validate the Manifest

Ensure the generated manifest is valid:

```bash
# Validate the manifest structure
python scripts/automate-scoop.py validate --software example-app

# Check with Scoop's built-in validation
scoop checkver bucket/example-app.json
```

#### Step 6: Test Full Integration

Add to the orchestrator and test:

```bash
# Update the orchestrator to include new script
python scripts/automate-scoop.py update-orchestrator

# Test the complete system
python scripts/automate-scoop.py test

# Run your script through the orchestrator
python scripts/update-all.py --scripts example-app --dry-run
```

#### Step 7: Production Deployment

When everything works correctly:

```bash
# Run the actual update (removes --dry-run)
python scripts/update-example-app.py

# Verify the manifest was updated
git diff bucket/example-app.json

# Commit your changes
git add .
git commit -m "Add example-app automation"
git push
```

### Advanced Scenarios

For complex configurations like multi-architecture software, custom installers, and advanced troubleshooting, see **[AUTOMATION-ADVANCED.md](AUTOMATION-ADVANCED.md)**.

### Troubleshooting Your Configuration

#### Common Issues and Solutions

**❌ Version Not Detected**
```bash
# Debug: Check what the homepage returns
curl -s "https://example.com/releases" | head -20

# Test your regex pattern
python -c "
import re
import requests
response = requests.get('https://example.com/releases')
matches = re.findall(r'Version\s+([0-9]+\.[0-9]+)', response.text)
print('Found versions:', matches)
"
```

**❌ Download URL Issues**
```bash
# Test the download URL manually
VERSION="1.2.3"
URL="https://example.com/download/app-$VERSION.exe"
ACTUAL_URL="${URL/\$VERSION/$VERSION}"
curl -I "$ACTUAL_URL"  # Should return 200 OK
```

**❌ Hash Calculation Fails**
```bash
# Test hash calculation manually
python -c "
import requests
import hashlib
url = 'https://example.com/download/app-1.2.3.exe'
response = requests.get(url, stream=True)
hash_sha256 = hashlib.sha256()
for chunk in response.iter_content(chunk_size=8192):
    hash_sha256.update(chunk)
print(f'SHA256: {hash_sha256.hexdigest()}')
"
```

### Best Practices

#### 1. Configuration Design
- ✅ **Use descriptive names**: `my-awesome-tool` not `tool1`
- ✅ **Test regex patterns**: Use [regex101.com](https://regex101.com) first
- ✅ **Verify URLs manually**: Test download links before automation
- ✅ **Include proper licensing**: Research and specify correct license

#### 2. Testing Strategy
- ✅ **Always dry-run first**: Test with `--dry-run` flag
- ✅ **Validate manifests**: Use `automate-scoop.py validate`
- ✅ **Test version detection**: Verify regex patterns work
- ✅ **Check integration**: Test with `update-all.py`

#### 3. Maintenance
- ✅ **Monitor for changes**: Software sites may change structure
- ✅ **Update regex patterns**: Version formats may evolve
- ✅ **Test regularly**: Run automation tests periodically
- ✅ **Document special cases**: Note any unusual requirements

## 🏗️ Architecture Overview

The automation system consists of several Python scripts that work together to detect versions, generate manifests, and update packages automatically.

For detailed technical documentation of script internals, classes, and integration patterns, see [AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md).

## 📝 Configuration System

### Software Configuration File

The automation system uses `scripts/software-configs.json` as a temporary input file (automatically cleaned up after generation). Here's how to configure software:

```json
{
  "software": [
    {
      "name": "my-awesome-app",
      "description": "My Awesome App - Does amazing things",
      "homepage": "https://example.com/app",
      "license": "MIT",
      "version_regex": "Version\\s+([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)",
      "download_url_template": "https://example.com/downloads/app-$version.exe",
      "bin_name": "app.exe",
      "shortcuts": [
        ["app.exe", "My Awesome App"]
      ]
    }
  ]
}
```

### Configuration Reference

| Field | Required | Type | Description | Example |
|-------|----------|------|-------------|---------|
| `name` | ✅ | string | Package identifier (used for filenames) | `"my-app"` |
| `description` | ✅ | string | Package description for manifest | `"My App - Description"` |
| `homepage` | ✅ | string | URL to scrape version from | `"https://example.com"` |
| `license` | ✅ | string | Software license | `"MIT"`, `"Freeware"`, `"GPL-3.0"` |
| `version_regex` | ✅ | string | Regex to extract version | `"Version\\s+([\\d\\.]+)"` |
| `download_url_template` | ✅ | string | Download URL with `$version` placeholder | `"https://example.com/app-$version.exe"` |
| `bin_name` | ❌ | string | Executable name (supports `$version`) | `"app-$version.exe"` |
| `shortcuts` | ❌ | array | Desktop shortcuts | `[["app.exe", "My App"]]` |
| `installer_type` | ❌ | string | Installer type | `"inno"`, `"nsis"`, `"msi"` |
| `extract_dir` | ❌ | string | Extract directory | `"app-$version"` |
| `pre_install` | ❌ | array | Pre-installation commands | `["echo Installing..."]` |
| `post_install` | ❌ | array | Post-installation commands | `["echo Done!"]` |
| `architecture` | ❌ | object | Architecture-specific configs | See examples below |

### Advanced Configuration Examples

For complex scenarios including multi-architecture support, custom installers, and advanced configurations, see **[AUTOMATION-ADVANCED.md](AUTOMATION-ADVANCED.md)**.

## 🔍 Version Detection Patterns

### Common Patterns

**GitHub Releases**: `"tag_name\":\\s*\"v?([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)"`  
**Direct Pages**: `"Version:?\\s*([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)"`  
**SourceForge**: `"([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)/"`

### Testing Version Detection

```bash
# Test your regex pattern
python scripts/automate-scoop.py test --software your-app
```

For complex version detection scenarios, see **[AUTOMATION-ADVANCED.md](AUTOMATION-ADVANCED.md)**.

## 🛠️ Core Commands

### Main Orchestrator Commands

```bash
# Interactive wizard (recommended for beginners)
python scripts/automate-scoop.py wizard

# Generate everything (manifests + update scripts)
python scripts/automate-scoop.py generate-all

# Generate for specific software only
python scripts/automate-scoop.py generate-all --software app1 app2

# Test all update scripts
python scripts/automate-scoop.py test

# Validate all manifests
python scripts/automate-scoop.py validate

# Dry run to preview changes
python scripts/automate-scoop.py generate-all --dry-run
```

### Update Management Commands

```bash
# Run all update scripts
python scripts/update-all.py

# Run specific scripts
python scripts/update-all.py --scripts app1 app2

# Dry run (test without changes)
python scripts/update-all.py --dry-run

# Parallel execution (set worker count)
python scripts/update-all.py --workers 4

# Force sequential mode
python scripts/update-all.py --sequential --delay 0.5

# Fast mode (auto-selects worker count)
python scripts/update-all.py --fast

# Provider throttling (avoid rate limits)
python scripts/update-all.py --github-workers 2 --microsoft-workers 2 --google-workers 3

# Prefer structured output (JSON) from scripts
python scripts/update-all.py --structured-output

# Enable short-lived HTTP caching for this run (TTL in seconds)
python scripts/update-all.py --http-cache --http-cache-ttl 1200

# Retry failed scripts up to N times
python scripts/update-all.py --retry 2
```

## 🧪 Testing & Validation

### Automated Testing

The system includes comprehensive testing capabilities:

```bash
# Test all update scripts
python scripts/automate-scoop.py test

# Validate all manifests
python scripts/automate-scoop.py validate

# Test specific software
python scripts/automate-scoop.py test --software my-app
```

### Manual Testing

#### Test Update Script Generation
```bash
# Generate and test a single script
python scripts/automate-scoop.py generate-scripts --software my-app
python scripts/update-my-app.py --dry-run
```

#### Test Manifest Generation
```bash
# Generate and validate a manifest
python scripts/automate-scoop.py generate-manifests --software my-app
python scripts/automate-scoop.py validate --software my-app
```

#### Test Version Detection
```python
# Test version detection directly
from version_detector import detect_version

version = detect_version(
    url="https://example.com",
    pattern=r"Version\s+([0-9]+\.[0-9]+)"
)
print(f"Found version: {version}")
```

## 🛡️ Anti-Blocking Features

Generated scripts include sophisticated anti-blocking measures:

### HTTP Headers
```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'identity',  # Disable compression
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
```

### Session Management
```python
import requests

session = requests.Session()
session.headers.update(headers)

# Reuse connections for efficiency
response = session.get(url, timeout=30)
```

### Rate Limiting
## 🚀 Advanced Usage

### Debugging Commands
```bash
# Test version detection
python scripts/automate-scoop.py test --software app-name

# Verbose output for troubleshooting
python scripts/automate-scoop.py generate-all --verbose

# Validate configurations
python scripts/automate-scoop.py validate
```

For advanced scenarios including custom version detection, performance optimization, and detailed troubleshooting, see **[AUTOMATION-ADVANCED.md](AUTOMATION-ADVANCED.md)**.

### Custom Script Templates

Modify `scripts/update_script_template.py` to customize generated scripts:

```python
# Add custom imports
import custom_module

# Add custom functions
def custom_version_detection(url: str) -> str:
    """Custom version detection logic."""
    # Your implementation here
    pass

# Modify the main update logic
def update_manifest(manifest_path: str, new_version: str, new_hash: str) -> None:
    """Enhanced manifest update with custom logic."""
    # Your enhanced implementation here
    pass
```

### Batch Operations

Process multiple software packages efficiently:

```python
from automate_scoop import AutomateScoop

automator = AutomateScoop()

# Generate for multiple packages
packages = ["app1", "app2", "app3"]
for package in packages:
    automator.generate_manifest(package)
    automator.generate_update_script(package)
```

### Integration with CI/CD

Example GitHub Actions workflow:

```yaml
name: Update Packages
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements-automation.txt
      
      - name: Run updates
        run: python scripts/update-all.py
      
      - name: Commit changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add .
          git diff --staged --quiet || git commit -m "Auto-update packages"
          git push
```

## 🔧 Troubleshooting

### Common Issues and Solutions

#### 1. Version Detection Fails
**Symptoms**: Scripts report "No version found" or "Version detection failed"

**Solutions**:
```bash
# Debug version detection patterns
python scripts/manifest-generator.py --debug-regex package-name

# Test with verbose output
python scripts/automate-scoop.py test --software app-name --verbose
```

**Quick Fixes**:
- **Version detection fails**: Check homepage URL and regex pattern
- **Download 404 errors**: Verify version regex captures complete version string
- **Hash mismatches**: Use `--force` flag to recalculate
- **Import errors**: Run `pip install -r requirements-automation.txt`
- **Performance issues**: Use `--timeout 60` for slow networks

For detailed troubleshooting scenarios, see **[AUTOMATION-ADVANCED.md](AUTOMATION-ADVANCED.md)**.