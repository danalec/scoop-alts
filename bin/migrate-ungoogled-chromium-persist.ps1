<#
Quick migration script to move Ungoogled Chromium "User Data" into Scoop's persist location
and create a junction so your profile is preserved across updates.

Usage:
  1) Close Ungoogled Chromium
  2) Run: powershell -ExecutionPolicy Bypass -File .\bin\migrate-ungoogled-chromium-persist.ps1

This script tries to use Scoop's paths via `scoop prefix` and `scoop config root`.
If Scoop is not available in PATH, it falls back to %USERPROFILE%\scoop.
#>

$ErrorActionPreference = 'Stop'

function Get-ScoopRoot {
  try {
    $root = (& scoop config root) 2>$null
    if ($root -and (Test-Path $root)) { return $root }
  } catch {}
  return Join-Path $env:USERPROFILE 'scoop'
}

function Get-ChromiumPrefix {
  try {
    $prefix = (& scoop prefix 'ungoogled-chromium') 2>$null
    if ($prefix -and (Test-Path $prefix)) { return $prefix }
  } catch {}
  return Join-Path $env:USERPROFILE 'scoop\apps\ungoogled-chromium\current'
}

Write-Host '🔧 Ungoogled Chromium persist migration starting...' -ForegroundColor Cyan

# Ensure browser is not running
foreach ($procName in @('chrome', 'ungoogled-chromium')) {
  Get-Process -Name $procName -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "⏹️  Stopping process: $($_.ProcessName) (PID $($_.Id))" -ForegroundColor Yellow
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
  }
}

$scoopRoot = Get-ScoopRoot
$prefix = Get-ChromiumPrefix
if (-not (Test-Path $prefix)) {
  Write-Host "❌ Ungoogled Chromium installation not found at: $prefix" -ForegroundColor Red
  Write-Host '   Tip: Ensure Ungoogled Chromium is installed via Scoop, then re-run this script.' -ForegroundColor Yellow
  exit 1
}

$currentUserData = Join-Path $prefix 'User Data'
$persistDir = Join-Path $scoopRoot 'persist\ungoogled-chromium'
$persistUserData = Join-Path $persistDir 'User Data'

Write-Host "📁 Current install path: $prefix"
Write-Host "📦 Persist path:        $persistUserData"

# Create persist base directory
if (-not (Test-Path $persistDir)) {
  Write-Host "📂 Creating persist directory: $persistDir" -ForegroundColor Cyan
  New-Item -ItemType Directory -Path $persistDir -Force | Out-Null
}

# Detect if current User Data is already a junction
$isJunction = $false
if (Test-Path $currentUserData) {
  try {
    $item = Get-Item $currentUserData -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $isJunction = $true }
  } catch {}
}

if ($isJunction) {
  Write-Host '✅ "User Data" already points to a reparse target. No migration needed.' -ForegroundColor Green
  Write-Host '   If you still want to re-link to the persist location, delete the junction and re-run this script.' -ForegroundColor Yellow
  exit 0
}

# Move or merge data into persist location
if (Test-Path $currentUserData) {
  if (-not (Test-Path $persistUserData)) {
    Write-Host '➡️  Moving existing User Data into persist location...' -ForegroundColor Cyan
    Move-Item -Path $currentUserData -Destination $persistUserData -Force
  } else {
    Write-Host '🔁 Persist User Data already exists; merging current data into persist...' -ForegroundColor Yellow
    Copy-Item -Path (Join-Path $currentUserData '*') -Destination $persistUserData -Recurse -Force -ErrorAction SilentlyContinue
    try { Remove-Item -Path $currentUserData -Recurse -Force -ErrorAction SilentlyContinue } catch {}
  }
}

# Ensure target exists
if (-not (Test-Path $persistUserData)) {
  Write-Host '📂 Creating empty persist User Data folder...' -ForegroundColor Cyan
  New-Item -ItemType Directory -Path $persistUserData -Force | Out-Null
}

# Create junction at current install path
if (-not (Test-Path $currentUserData)) {
  Write-Host '🔗 Creating junction from install path to persist...' -ForegroundColor Cyan
  New-Item -ItemType Junction -Path $currentUserData -Target $persistUserData | Out-Null
} else {
  # If path exists but is a directory, recreate as junction
  try {
    $item = Get-Item $currentUserData -ErrorAction SilentlyContinue
    if ($item -and -not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
      Write-Host '🔧 Replacing directory with junction...' -ForegroundColor Cyan
      Remove-Item -Path $currentUserData -Recurse -Force
      New-Item -ItemType Junction -Path $currentUserData -Target $persistUserData | Out-Null
    }
  } catch {}
}

Write-Host '✅ Migration complete. Your Ungoogled Chromium profile will now persist across updates.' -ForegroundColor Green
Write-Host '   You can verify with: Get-Item "$env:USERPROFILE\\scoop\\apps\\ungoogled-chromium\\current\\User Data" | Format-List *' -ForegroundColor Yellow