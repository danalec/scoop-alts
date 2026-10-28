# Dan's Alternative Scoop Bucket (`scoop-alts`)

[![CI](https://github.com/danalec/scoop-alts/actions/workflows/ci.yml/badge.svg)](https://github.com/danalec/scoop-alts/actions/workflows/ci.yml)
[![Manifests](https://img.shields.io/badge/manifests-30%20packages-blue.svg)](bucket/)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-brightgreen.svg)](https://www.python.org/)

> Curated Windows software manifests with enhanced packaging, automated quality assurance, and
> intelligent lifecycle management for [Scoop](https://scoop.sh).

An alternative bucket for software that needs enhanced configurations: Widevine DRM integration,
persisted user profiles, custom install hooks, and bleeding-edge builds. A generated package
index is published to <https://danalec.github.io/scoop-alts/> via GitHub Pages.

It also carries the maintainer's own tools — [`rgx`](bucket/rgx.json), a ripgrep-compatible
full-text search engine for PDFs, Office documents, archives, email and GGUF/LLM model files,
with a Zen 4+ tuned build alongside the generic one.

Every manifest is refreshed continuously by a Python automation pipeline and a containerized
scheduler, so `scoop update` is normally enough.

---

## 🌟 Featured Applications

| Package | Category | Highlights & Special Features |
| :--- | :--- | :--- |
| **`rgx`** | Developer / Tooling | ripgrep-compatible full-text search across PDFs, Office docs, archives and GGUF models, plus a Zen 4+ build |
| **`ungoogled-chromium`** | Browser / Privacy | Widevine DRM for Spotify & Netflix, persisted user profile across updates |
| **`thorium-avx2`** | Browser / Performance | AVX2-accelerated Chromium fork tracking upstream, portable ZIP layout |
| **`agy`** | Developer / AI | Official Antigravity CLI by Google DeepMind, multi-architecture (64bit + arm64) |
| **`token-monitor`** | Developer / AI | Live dashboard for AI coding-tool token usage, desktop app on upstream releases |
| **`harmony`** | Communication / Social | Federated social app (ActivityPub) in Tauri, Discord-style servers and chat |
| **`taskexplorer`** | Utilities / System | Process monitor with thread, handle, network and memory analysis |
| **`windhawk`** | Customization | Modular Windows modification engine with persisted config and mods |
| **`kuna`** | Developer / Tooling | Agent-first decompiler in Rust, ported from Ghidra, with bundled processor specs |
| **`corecycler`** | Benchmarking | Per-core stress testing to fine-tune Curve Optimizer on Ryzen/Intel |

---

## 📦 Package Catalog (30)

| Manifest | Upstream Provider | Description | Persist |
| :--- | :--- | :--- | :---: |
| [`agy`](bucket/agy.json) | Google Cloud | Antigravity CLI — agentic AI coding assistant by Google DeepMind | — |
| [`atomic`](bucket/atomic.json) | GitHub Releases | High-performance alarm and event monitoring client | — |
| [`cache-relocator`](bucket/cache-relocator.json) | SoftPerfect | Move browser and application caches to RAM disk or secondary storage | — |
| [`chromium-crlset`](bucket/chromium-crlset.json) | Google Chrome | Latest CRLSet updates for Chromium | — |
| [`codecharta`](bucket/codecharta.json) | GitHub Releases | Code analysis and interactive 3D city visualization | — |
| [`corecycler`](bucket/corecycler.json) | GitHub Releases | Script-driven per-core stability tester (Prime95/Y-Cruncher) | — |
| [`depressurizer`](bucket/depressurizer.json) | GitHub Releases | Steam library categorization and auto-tagging utility | — |
| [`esptool`](bucket/esptool.json) | GitHub Releases | ROM bootloader utility for Espressif ESP8266 & ESP32 | — |
| [`hdd-lff-portable`](bucket/hdd-lff-portable.json) | HDDGuru | Low-level formatting tool for SATA, IDE, SAS, SCSI and SSD drives | — |
| [`harmony`](bucket/harmony.json) | GitHub Releases | Federated social app: Discord-style servers and chat with ActivityPub | — |
| [`kuna`](bucket/kuna.json) | GitHub Releases | Agent-first decompiler written in Rust, ported from Ghidra | — |
| [`ntoptimizer`](bucket/ntoptimizer.json) | NTDev | Lightweight Windows performance tuning and debloating utility | — |
| [`ripgrep-all`](bucket/ripgrep-all.json) | [danalec/ripgrep-all](https://github.com/danalec/ripgrep-all) | Ripgrep wrapper searching inside PDFs, e-books, Office files and archives | — |
| [`ripgrep-all-znver4`](bucket/ripgrep-all-znver4.json) | [danalec/ripgrep-all](https://github.com/danalec/ripgrep-all) | ripgrep-all build targeting AMD Zen 4 and newer | — |
| [`rgx`](bucket/rgx.json) | [danalec/rgx](https://github.com/danalec/rgx) | Full-text search across PDFs, Office docs, archives, email and GGUF models (ripgrep-compatible) | — |
| [`rgx-znver4`](bucket/rgx-znver4.json) | [danalec/rgx](https://github.com/danalec/rgx) | rgx build targeting AMD Zen 4 and newer | — |
| [`spotifast`](bucket/spotifast.json) | [crmne/spotifast](https://github.com/crmne/spotifast) | Native and fast Spotify client with local playback and Spotify Connect | — |
| [`taskexplorer`](bucket/taskexplorer.json) | GitHub Releases | Advanced task manager with driver-level inspection | — |
| [`thorium-avx2`](bucket/thorium-avx2.json) | GitHub Releases | Fastest Chromium fork with AVX2 compiler optimizations | `USER_DATA` |
| [`token-monitor`](bucket/token-monitor.json) | GitHub Releases | One live dashboard for every AI coding tool, synced across every machine | — |
| [`ungoogled-chromium`](bucket/ungoogled-chromium.json) | GitHub Releases | Google-free Chromium with Widevine DRM integration | `User Data` |
| [`unraid-usb-creator`](bucket/unraid-usb-creator.json) | LimeTech | Official Lime tool to prepare bootable Unraid flash drives | — |
| [`usb-safely-remove`](bucket/usb-safely-remove.json) | SafelyRemove | Enhanced USB device management and quick eject (Installer) | — |
| [`usb-safely-remove-portable`](bucket/usb-safely-remove-portable.json) | SafelyRemove | Portable edition with self-contained settings | — |
| [`veracrypt`](bucket/veracrypt.json) | IDRIX | Open-source on-the-fly disk encryption software | — |
| [`victoria`](bucket/victoria.json) | Direct Asset | HDD/SSD diagnostic, testing and surface analysis tool | — |
| [`widevinecdm`](bucket/widevinecdm.json) | Google Chrome | Widevine CDM for third-party Chromium builds | — |
| [`wifiscanner`](bucket/wifiscanner.json) | LizardSystems | 802.11a/b/g/n/ac/ax wireless scanner and spectrum analyzer | — |
| [`windhawk`](bucket/windhawk.json) | GitHub Releases | Customization engine using modular injectables | `AppData` |
| [`zapfast`](bucket/zapfast.json) | [crmne/zapfast](https://github.com/crmne/zapfast) | Fast, native WhatsApp client in Rust and egui | — |

---

## 🚀 Quick Start

```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts

scoop install danalec_scoop-alts/agy                  # Antigravity CLI
scoop install danalec_scoop-alts/rgx                  # full-text search in PDFs and Office docs
scoop install danalec_scoop-alts/token-monitor        # AI token usage dashboard
scoop install danalec_scoop-alts/ungoogled-chromium   # privacy browser + Widevine
scoop install danalec_scoop-alts/taskexplorer         # diagnostics
scoop install danalec_scoop-alts/windhawk             # customization engine

scoop update
```

### Persisted data

- `ungoogled-chromium` — profile at `%USERPROFILE%\scoop\persist\ungoogled-chromium\User Data`.
  Deploys `WidevineCdm` for Spotify/Netflix/Disney+. Purge everything on uninstall:
  `scoop uninstall ungoogled-chromium --purge`. Full details in
  [docs/ungoogled-chromium.md](docs/ungoogled-chromium.md).
- `windhawk` — mods at `%USERPROFILE%\scoop\persist\windhawk\windhawk\AppData`.
  Purge with `scoop uninstall windhawk --purge`.

---

## 🛠️ Automation

```text
upstream releases → version_detector.py → updater → manifest_manager.py
                                                              ↓
                                                      bucket/<pkg>.json
                                                              ↓
                                            git_helpers.py → commit → push main
```

Packages are updated by a single orchestrator, `scripts/update-all.py`, which runs each
updater in its own subprocess. Most are declared as data in `scripts/packages.json` and run
through one generic runner; the few needing bespoke logic keep their own script.

```bash
pip install -r scripts/requirements-automation.txt
python scripts/update-all.py --workers 6
docker compose up -d        # hourly scheduler, see docs/DOCKER-SETUP.md
```

- [AGENTS.md](AGENTS.md) — commands, conventions, and rules for agents and contributors
- [docs/AUTOMATION.md](docs/AUTOMATION.md) — engine reference and how to extend it
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution workflow

---

## 📄 License

[BSD-3-Clause](LICENSE). Installed packages remain under their own upstream licenses.

---

## ⭐ Star History

<a href="https://star-history.com/#danalec/scoop-alts">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=danalec/scoop-alts&type=date&legend=top-left&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=danalec/scoop-alts&type=date&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=danalec/scoop-alts&type=date&legend=top-left" />
  </picture>
</a>
