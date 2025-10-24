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

### Ungoogled Chromium: Persist + Default Browser Setup

This bucket’s Ungoogled Chromium manifest includes:
- persist: "User Data" to preserve your profile across updates
- a gated post_install script to help set it as your default browser when you opt in

Default browser post_install (opt-in):
- Automatic (no prompt):
```powershell
$env:SCOOP_SET_DEFAULT_BROWSER = '1'
scoop uninstall ungoogled-chromium
scoop install danalec_scoop-alts/ungoogled-chromium
```
- Interactive prompt:
```powershell
$env:SCOOP_INTERACTIVE = '1'
scoop uninstall ungoogled-chromium
scoop install danalec_scoop-alts/ungoogled-chromium
```
- Notes:
  - Ensure you install from this bucket (danalec_scoop-alts), not extras, so the post_install runs.
  - Windows 10/11 protects default app associations; the script updates command paths and opens Settings → Default Apps for confirmation when needed.

Persist migration (no reinstall required):
If you installed Chromium earlier without persist, you can migrate your profile:
```powershell
powershell -ExecutionPolicy Bypass -File .\bin\migrate-ungoogled-chromium-persist.ps1
```
Then verify the junction:
```powershell
Get-Item "$env:USERPROFILE\scoop\apps\ungoogled-chromium\current\User Data" | Format-List *
```
LinkType should be Junction and Target should point to:
```
%USERPROFILE%\scoop\persist\ungoogled-chromium\User Data
```

Confirm the manifest/source in use:
```powershell
scoop info ungoogled-chromium
```
The Source should be danalec_scoop-alts. If it shows extras, reinstall explicitly from this bucket:
```powershell
scoop uninstall ungoogled-chromium
scoop install danalec_scoop-alts/ungoogled-chromium
```

### Browse All Packages
Online:
https://github.com/danalec/scoop-alts/tree/main/bucket

Locally (after adding the bucket):
```powershell
Get-ChildItem "$env:SCOOP\\buckets\\danalec_scoop-alts\\bucket\\*.json" | Select-Object -ExpandProperty BaseName
```

## 🤖 Automation

This bucket features **automated package maintenance** powered by a Python automation system that ensures packages stay up-to-date and reliable:

### For Developers
Complete automation framework available for creating your own automated Scoop buckets:
- **[AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md)**: Setup and usage documentation
- **[AUTOMATION-SCRIPTS-DOCUMENTATION.md](AUTOMATION-SCRIPTS-DOCUMENTATION.md)**: Technical reference

## 🛠️ For Developers & Contributors

### **Create Your Own Automated Bucket**
This repository includes a complete automation framework for maintaining Scoop buckets:

```bash
# Quick setup
git clone https://github.com/danalec/scoop-alts
cd scoop-alts
pip install -r requirements-automation.txt

# Interactive wizard (no JSON editing required!)
python scripts/automate-scoop.py wizard
```

**See [AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md) for complete setup and usage documentation.**

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
```

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

**See [AUTOMATION-GUIDE.md](AUTOMATION-GUIDE.md) for detailed contribution instructions.**

## 📄 License

BSD-3-Clause - See [LICENSE](LICENSE) file for details.
