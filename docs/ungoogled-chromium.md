# Ungoogled Chromium Guide

This guide covers installation, persisted profile behavior, default‑browser setup, migration, and clean uninstall steps for Ungoogled Chromium in the danalec_scoop-alts bucket.

Quick links:
- [Install](#install)
- [Persist and Default Browser Setup](#persist-and-default-browser-setup)
- [Persist Migration (no reinstall required)](#persist-migration-no-reinstall-required)
- [Confirm the Manifest Source](#confirm-the-manifest-source)
- [Clean Uninstall (remove persisted profile)](#clean-uninstall-remove-persisted-profile)
- [Uninstall Verification Checklist](#uninstall-verification-checklist)

## Install

Add the bucket and install Ungoogled Chromium with Widevine support:

```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts
scoop install danalec_scoop-alts/ungoogled-chromium
```

## Persist and Default Browser Setup

- Persist: The manifest uses `persist: "User Data"` to preserve your profile across updates and standard uninstalls.
- Default browser setup: The manifest’s post_install is gated and non‑invasive by default:
  - Registers its own ProgID (ChromiumHTML) and StartMenuInternet capabilities.
  - Opens Windows Default Apps so you can confirm associations.
  - Does not override system `http/https` handlers unless you explicitly opt in.

Opt‑in environment variables:
- Set `SCOOP_SET_DEFAULT_BROWSER=1` before install to register without a prompt.
- Set `SCOOP_INTERACTIVE=1` before install to be prompted during post_install.
- Set `SCOOP_OVERRIDE_DEFAULT_COMMAND=1` before install to override `http/https` handlers. The installer backs up previous values to a file:
  - Backup file: `$dir\default-association-backup.json`
  - The uninstaller can restore from this backup with confirmation.

## Persist Migration (no reinstall required)

If you previously installed without persist, migrate your profile to Scoop’s persist:

```powershell
powershell -ExecutionPolicy Bypass -File .\bin\migrate-ungoogled-chromium-persist.ps1
```

Verify the junction:

```powershell
Get-Item "$env:USERPROFILE\scoop\apps\ungoogled-chromium\current\User Data" | Format-List *
```

LinkType should be `Junction` and Target should point to:

```
%USERPROFILE%\scoop\persist\ungoogled-chromium\User Data
```

## Confirm the Manifest Source

Ensure you’re using this bucket’s manifest:

```powershell
scoop info ungoogled-chromium
```

The Source should be `danalec_scoop-alts`. If you see another bucket (e.g., `extras`), reinstall explicitly from this bucket:

```powershell
scoop uninstall ungoogled-chromium
scoop install danalec_scoop-alts/ungoogled-chromium
```

## Clean Uninstall (remove persisted profile)

Scoop’s persist keeps your profile under:

```
%USERPROFILE%\scoop\persist\ungoogled-chromium\User Data
```

For a fully clean removal (including your profile), use the purge flag:

```powershell
scoop uninstall ungoogled-chromium --purge
```

Notes:
- This deletes the persisted `User Data` folder shown above.
- The manifest’s uninstaller prompts to clean related registry entries (default‑browser associations) safely. You’ll be asked to confirm each removal.
- If you had set `SCOOP_OVERRIDE_DEFAULT_COMMAND=1`, the uninstaller can restore `http/https` handlers from `$dir\default-association-backup.json` with confirmation.

## Uninstall Verification Checklist

- App files and shim removed:
  - App directory removed: `%USERPROFILE%\scoop\apps\ungoogled-chromium\current\`
  - Shim no longer resolves: `Get-Command chrome` (should report not found)
- Persisted data removed (when using `--purge`):
  - Directory removed: `%USERPROFILE%\scoop\persist\ungoogled-chromium\User Data\`
- Registry sanity checks:
  - `HKCU\Software\Clients\StartMenuInternet\Chromium` — removed
  - `HKCU\Software\Classes\ChromiumHTML` — removed
  - `HKCU\Software\RegisteredApplications` — value named `Chromium` — removed
  - `HKCU\Software\Classes\http\shell\open\command` — restored or no override to the Scoop path
  - `HKCU\Software\Classes\https\shell\open\command` — restored or no override to the Scoop path
  - If associations look broken, open Windows Default Apps and reselect your default browser.

---

[← Back to Docs Index](index.md)

