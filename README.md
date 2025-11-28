# 🚀 Dan's Alternative Scoop Bucket

> **Enhanced applications with automation-powered quality assurance**

Alternative Scoop bucket featuring **carefully curated applications** with enhanced functionality, customized configurations, and automated quality-of-life improvements. Every package is maintained through a sophisticated **Python automation system** that ensures reliability and freshness.

## 📦 Featured Applications

| Package | Description | Special Features |
|---------|-------------|------------------|
| **ungoogled-chromium** | Privacy-focused browser | ✅ Widevine DRM support for Netflix/Spotify · 💾 Persisted profile across updates · ⚙️ Opt-in default-browser post_install

## 🚀 Quick Start

### Install the Bucket
```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts
```

### Install Ungoogled Chromium with Widevine
```powershell
scoop install danalec_scoop-alts/ungoogled-chromium
```

### Ungoogled Chromium

Install Ungoogled Chromium with Widevine:
```powershell
scoop install danalec_scoop-alts/ungoogled-chromium
```

For the full guide (persist, default‑browser setup, migration, clean uninstall, and verification), see:

[docs/ungoogled-chromium.md](docs/ungoogled-chromium.md)

## 📚 Documentation
For a centralized documentation index, see:
[docs/index.md](docs/index.md)


### Browse All Packages
Online:
https://github.com/danalec/scoop-alts/tree/main/bucket

Locally (after adding the bucket):
```powershell
Get-ChildItem "$env:SCOOP\\buckets\\danalec_scoop-alts\\bucket\\*.json" | Select-Object -ExpandProperty BaseName
```

### Other packages with persist and purge

Some packages in this bucket use Scoop’s persist to keep app data across updates and standard uninstalls. Use the --purge flag to remove those data folders during uninstall.

- Windhawk
  - Persisted path:
    ``
    %USERPROFILE%\scoop\persist\windhawk\windhawk\AppData
    ``
  - Clean uninstall (remove settings/mods):
    ```powershell
    scoop uninstall windhawk --purge
    ```
  - Verify the junction (optional):
    ```powershell
    Get-Item "$env:USERPROFILE\scoop\apps\windhawk\current\windhawk\AppData" | Format-List *
    ```
    LinkType should be Junction and Target should point to the persist path above.

### Uninstall verification checklist

- Confirm the app files and shim are removed:
  - App directory removed:
    - %USERPROFILE%\scoop\apps\ungoogled-chromium\current\
  - Shim no longer resolves:
    - PowerShell: Get-Command chrome (should report not found)
- Confirm persisted data is removed when using --purge:
  - Directory removed:
    - %USERPROFILE%\scoop\persist\ungoogled-chromium\User Data\
  - In the app directory, there should be no junction pointing to "User Data" (the whole app directory is gone after uninstall)
- Registry sanity checks after cleanup:
  - HKCU\Software\Clients\StartMenuInternet\Chromium — removed
  - HKCU\Software\Classes\ChromiumHTML — removed
  - HKCU\Software\RegisteredApplications — value named "Chromium" — removed
  - HKCU\Software\Classes\http\shell\open\command — restored or no override to the Scoop path
  - HKCU\Software\Classes\https\shell\open\command — restored or no override to the Scoop path
  - If associations look broken, open Windows Default Apps and reselect your default browser.

### Persist cheat sheet

- ungoogled-chromium
  - Persist path: %USERPROFILE%\scoop\persist\ungoogled-chromium\User Data
  - Purge command: scoop uninstall ungoogled-chromium --purge
  - Notes: Profile data is intentionally persisted. The uninstaller prompts for default‑browser registry cleanup and will restore http/https handlers from a backup if you opted-in to override them.
- windhawk
  - Persist path: %USERPROFILE%\scoop\persist\windhawk\windhawk\AppData
  - Purge command: scoop uninstall windhawk --purge
  - Optional: Verify junctions with Get-ChildItem $env:USERPROFILE\scoop\apps\windhawk\current -Force | Where-Object {$_.LinkType}


## 🤖 Automation

This bucket features **automated package maintenance** powered by a Python automation system that ensures packages stay up-to-date and reliable:

### For Developers
Complete automation framework available for creating your own automated Scoop buckets:
- **[AUTOMATION-GUIDE.md](docs/AUTOMATION-GUIDE.md)**: Setup and usage documentation
- **[AUTOMATION-SCRIPTS-DOCUMENTATION.md](docs/AUTOMATION-SCRIPTS-DOCUMENTATION.md)**: Technical reference

## 🛠️ For Developers & Contributors

### **Create Your Own Automated Bucket**
This repository includes a complete automation framework for maintaining Scoop buckets:

```bash
# Quick setup
git clone https://github.com/danalec/scoop-alts
cd scoop-alts
pip install -r scripts/requirements-automation.txt

# Interactive wizard (no JSON editing required!)
python scripts/automate-scoop.py wizard
```

**See [AUTOMATION-GUIDE.md](docs/AUTOMATION-GUIDE.md) for complete setup and usage documentation.**

Audit provider classification and write a map:
```bash
python scripts/automate-scoop.py audit-providers --write-map
```

### Orchestrator quick start
Run all updates (parallel by default):
```bash
python scripts/update-all.py
```
Common flags:
```bash
python scripts/update-all.py --workers 6
python scripts/update-all.py --sequential --delay 0.5
python scripts/update-all.py --fast
python scripts/update-all.py --retry 2
python scripts/update-all.py --structured-output
python scripts/update-all.py --http-cache --http-cache-ttl 1800
python scripts/update-all.py --json-summary .temp/update-summary.json
python scripts/update-all.py --md-summary .temp/update-summary.md
python scripts/update-all.py --sequential --fail-fast
python scripts/update-all.py --sequential --max-fail 2
python scripts/update-all.py --circuit-threshold 3 --circuit-sleep 5.0
python scripts/update-all.py --no-error-exit
python scripts/update-all.py --only-providers github microsoft
python scripts/update-all.py --skip-providers google
python scripts/update-all.py --skip-scripts windhawk esptool
```

### Structured output
- Use `--structured-output` to prefer strict JSON parsing from update scripts and avoid text heuristics in the orchestrator.
- When `--structured-output` is set, the orchestrator sets `STRUCTURED_ONLY=1` for child scripts so they emit only a single JSON line.

### Manifest validation
- Manifests are validated against a JSON Schema during CI and via `python scripts/automate-scoop.py validate`.

### GitHub API rate limits
- Set `GITHUB_TOKEN` (or `GH_TOKEN`) in the environment to enable authenticated requests and higher GitHub API rate limits used by the version detector.

### Provider throttling mapping
- Optionally place `scripts/providers.json` to map scripts or packages to a provider (`github`, `microsoft`, `google`, `other`) to improve throttling accuracy.

### Resume failed scripts
- Use `--resume .temp/update-summary.json` to rerun only the scripts that failed in the previous run.

### CI environment guard
- Set `AUTOMATION_DISABLE_WINMETA=1` to disable Windows-specific metadata extraction paths in the version detector (useful on non-Windows CI runners).

### Webhook notifications
- Provide `--webhook-url` (and optionally `--webhook-header-name`/`--webhook-header-value`) to POST the JSON summary to a webhook endpoint after a run.
- Set `--webhook-type` to `slack` or `discord` to format payloads for those platforms (`generic` by default sends the raw JSON summary).

### Environment overrides
- `AUTOMATION_WEBHOOK_URL`, `AUTOMATION_WEBHOOK_HEADER_NAME`, `AUTOMATION_WEBHOOK_HEADER_VALUE` can provide webhook settings.
- `AUTOMATION_JSON_SUMMARY` and `AUTOMATION_MD_SUMMARY` can provide default output paths for summaries.
- `SCOOP_GIT_REMOTE` and `SCOOP_GIT_BRANCH` can control which remote/branch is used for auto push.

### Update dashboard
- Generate a Markdown dashboard from a summary JSON: `python scripts/generate-dashboard.py .temp/update-summary.json docs/update-health.md`.

## 🤝 Contributing

### **For Users**
- 🐛 **Report Issues**: Found a problem? Open an issue!
- 💡 **Request Packages**: Suggest new software to include
- ⭐ **Star the Repo**: Help others discover this bucket

### **For Developers**
- 🔧 **Improve Automation**: Enhance the Python scripts
- 📦 **Add Packages**: Contribute new software configurations
- 🧪 **Testing**: Help improve validation and testing
- 📚 **Documentation**: Improve guides and examples

**See [AUTOMATION-GUIDE.md](docs/AUTOMATION-GUIDE.md) for detailed contribution instructions.**

## 📄 License

BSD-3-Clause - See [LICENSE](LICENSE) file for details.
