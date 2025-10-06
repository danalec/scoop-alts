# 🚀 Dan's Alternative Scoop Bucket

> **Enhanced applications with automation-powered quality assurance**

Alternative Scoop bucket featuring **carefully curated applications** with enhanced functionality, customized configurations, and automated quality-of-life improvements. Every package is maintained through a sophisticated **Python automation system** that ensures reliability and freshness.

## 📦 Featured Applications

| Package | Description | Special Features |
|---------|-------------|------------------|
| **ungoogled-chromium** | Privacy-focused browser | ✅ Widevine DRM support for Netflix/Spotify

## 🚀 Quick Start

### Install the Bucket
```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts
```

### Install Ungoogled Chromium with Widevine
```powershell
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
