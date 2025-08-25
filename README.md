# danalec_scoop-alts

Alternative Scoop buckets for various applications, focusing on enhanced functionality, customized configurations, and quality-of-life improvements.

## Description

Dan's Alternative Scoop buckets provide enhanced applications with customized configurations and quality-of-life improvements. Dan's collection includes:

- **ungoogled-chromium with Widevine support** - Privacy-focused browser with DRM support for Netflix, Amazon Prime Video, and Spotify Web Player
- **esptool** - Enhanced ESP32/ESP8266 flashing utility with additional features
- **ntoptimizer** - Windows network optimization tools with custom configurations
- **windhawk** - System customization tool with tailored settings
- **wifiscanner** - Wireless network analysis with improved interface

Each package includes Dan's custom configurations and quality-of-life enhancements to improve the overall user experience.

## Installation

### Add the bucket

```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts
```

### Install ungoogled-chromium with Widevine

```powershell
scoop install danalec_scoop-alts/ungoogled-chromium
```

**Note:** You might need to run `scoop config force_update $true` to ensure updates from this bucket are not disregarded.

## Usage

After installation, launch **Chromium** from your Start Menu. To verify Widevine functionality, visit Netflix or Crunchyroll and test video playback.

## Contributing

Contributions welcome! Submit pull requests for improvements or new bucket suggestions.

## License

BSD-3-Clause - See [LICENSE](LICENSE) file for details
