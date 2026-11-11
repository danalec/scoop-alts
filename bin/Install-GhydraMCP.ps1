#requires -Version 5.1
<#
.SYNOPSIS
    Installs the GhydraMCP Ghidra extension and wires its stdio MCP bridge into
    the most common AI agent harnesses.

.DESCRIPTION
    The scoop package `ghydramcp` only drops files on disk: one Ghidra extension
    build per Ghidra version line plus the stdio bridge. This script turns those
    files into a working setup:

      1. finds the bridge and the extension payloads (scoop app dir or explicit
         -BridgePath),
      2. copies the payload whose declared `ghidraVersion` matches each detected
         Ghidra install exactly (Ghidra refuses a mismatched extension),
      3. merges one `ghydra` server entry into every detected MCP harness
         configuration, leaving all other servers untouched.

    It is idempotent: a second run reports `unchanged` and writes nothing. Every
    write is preceded by a `<file>.bak` backup of the original file (first change
    only) and is done through a temporary file in the same directory.

    Run with -DryRun first to see what would change.

.PARAMETER BridgePath
    Absolute path to bridge_mcp_hydra.py. Defaults to $env:GHYDRAMCP_HOME, the
    scoop app directory, or the directory this script lives in.

.PARAMETER GhidraPath
    One or more Ghidra installation roots (the directory that contains
    `Ghidra\application.properties`). Defaults to $env:GHIDRA_HOME,
    $env:GHIDRA_INSTALL_DIR, the scoop Ghidra app, and the usual
    `%USERPROFILE%\tools\ghidra_*_PUBLIC` / `%ProgramFiles%\ghidra_*` locations.

.PARAMETER Harness
    Only configure these harnesses (names from -Help). Defaults to every detected
    harness.

.PARAMETER DryRun
    Report what would change. Never writes a configuration file, never copies an
    extension.

.PARAMETER Json
    Print one JSON document instead of the human table. Console noise is
    suppressed so the output can be piped.

.PARAMETER Uninstall
    Remove only the `ghydra` entries this script added. Other servers and the
    rest of each file are left intact.

.PARAMETER RemoveExtension
    With -Uninstall, also remove the `Ghydra` extension directory from the
    detected Ghidra installs.

.PARAMETER FromScoop
    Accepted for the `scoop install` post-install call; payload discovery from
    the scoop app directory is already the default.

.PARAMETER Force
    Rewrite entries/extensions even when they already match.

.PARAMETER Help
    Show usage and exit.

.EXAMPLE
    pwsh -File bin\Install-GhydraMCP.ps1 -DryRun
    Show the detected Ghidra installs and harnesses without writing anything.

.EXAMPLE
    pwsh -File bin\Install-GhydraMCP.ps1 -Harness 'Claude Code','Cursor'
    Configure only the two named harnesses.

.OUTPUTS
    Console table, or JSON with -Json:
    { dryRun, bridge, ghidra: [...], harnesses: [...], changed }

.NOTES
    Exit codes: 0 success, 1 a required step failed, 2 invalid usage.
#>
[CmdletBinding()]
param(
    [string]$BridgePath,
    [string[]]$GhidraPath,
    [string[]]$Harness,
    [switch]$DryRun,
    [switch]$Json,
    [switch]$Uninstall,
    [switch]$RemoveExtension,
    [switch]$FromScoop,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$script:Quiet = [bool]$Json

function Write-Info {
    param([string]$Message)
    if (-not $script:Quiet) { Write-Host $Message }
}

function Write-Notice {
    param([string]$Message)
    if ($script:Quiet) {
        # Keep stdout parseable as one JSON document, but never swallow a
        # diagnostic: it goes to stderr, where -Json consumers can still see it.
        [Console]::Error.WriteLine($Message)
    } else {
        Write-Host $Message -ForegroundColor Yellow
    }
}

function Show-Help {
    $text = @"
Install-GhydraMCP.ps1 - install the GhydraMCP Ghidra extension and wire its
stdio MCP bridge into the detected AI agent harnesses.

USAGE
  pwsh -File bin\Install-GhydraMCP.ps1 [-BridgePath <path>] [-GhidraPath <path[]>]
       [-Harness <name[]>] [-DryRun] [-Json] [-Uninstall] [-RemoveExtension]
       [-FromScoop] [-Force] [-Help]

PARAMETERS
  -BridgePath      bridge_mcp_hydra.py (default: GHYDRAMCP_HOME, then the
                   scoop ghydramcp app directory)
  -GhidraPath      one or more Ghidra install roots (default: GHIDRA_HOME,
                   GHIDRA_INSTALL_DIR, the scoop ghidra app, %USERPROFILE%\tools,
                   %ProgramFiles%)
  -Harness         only these harnesses instead of every detected one
  -DryRun          report what would change; never writes
  -Json            one JSON document on stdout (diagnostics go to stderr)
  -Uninstall       remove only the ghydra entries this script added
  -RemoveExtension with -Uninstall, also remove the installed extension directory
  -FromScoop       accepted for the scoop post-install call (discovery default)
  -Force           rewrite entries/extensions even when they already match
  -Help            this text

HARNESSES (auto-detected, skipped when absent)
  Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Cursor, Windsurf, Cline,
  Roo Code, VS Code, Zed, opencode, Continue

EXIT CODES
  0 success, 1 a required step failed, 2 invalid usage
"@
    Write-Host $text
}

if ($Help) {
    Show-Help
    exit 0
}

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

function Get-ScoopRoot {
    if ($env:SCOOP) { return $env:SCOOP }
    $candidate = Join-Path $env:USERPROFILE 'scoop'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

function Resolve-Bridge {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($BridgePath) {
        if (-not (Test-Path -LiteralPath $BridgePath -PathType Leaf)) {
            throw "BridgePath '$BridgePath' does not exist."
        }
        $candidates.Add($BridgePath)
    }
    if ($env:GHYDRAMCP_HOME) {
        $candidates.Add((Join-Path $env:GHYDRAMCP_HOME 'bridge_mcp_hydra.py'))
    }
    $scoopRoot = Get-ScoopRoot
    if ($scoopRoot) {
        $candidates.Add((Join-Path $scoopRoot 'apps\ghydramcp\current\bridge_mcp_hydra.py'))
    }
    $candidates.Add((Join-Path $PSScriptRoot '..\bridge_mcp_hydra.py'))
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Resolve-Uv {
    $command = Get-Command -Name 'uv' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Source }
    $scoopRoot = Get-ScoopRoot
    if ($scoopRoot) {
        $candidate = Join-Path $scoopRoot 'apps\python\current\Scripts\uv.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Get-IniValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*?)\s*$'
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match $pattern) { return $Matches[1] }
    }
    return $null
}

function Test-GhidraInstall {
    param([string]$Path)
    if (-not $Path) { return $false }
    return (Test-Path -LiteralPath (Join-Path $Path 'Ghidra\application.properties'))
}

function Get-GhidraCandidates {
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($path in $GhidraPath) {
        if ($path) { $found.Add($path) }
    }
    foreach ($name in @('GHIDRA_HOME', 'GHIDRA_INSTALL_DIR')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $found.Add($value) }
    }
    $scoopRoot = Get-ScoopRoot
    if ($scoopRoot) {
        $found.Add((Join-Path $scoopRoot 'apps\ghidra\current'))
    }
    $searchRoots = @(
        (Join-Path $env:USERPROFILE 'tools'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    )
    foreach ($root in $searchRoots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        foreach ($directory in Get-ChildItem -LiteralPath $root -Directory -Filter 'ghidra_*' -ErrorAction SilentlyContinue) {
            $found.Add($directory.FullName)
        }
    }
    $unique = @{}
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in $found) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        $full = [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')
        if (-not $unique.ContainsKey($full.ToLowerInvariant())) {
            $unique[$full.ToLowerInvariant()] = $true
            $result.Add($full)
        }
    }
    return $result
}

function Get-ExtensionPayloads {
    param([string]$Bridge)
    $payloads = New-Object System.Collections.Generic.List[psobject]
    $root = Split-Path -Parent $Bridge
    if (-not $root -or -not (Test-Path -LiteralPath $root)) { return $payloads }
    $directories = Get-ChildItem -LiteralPath $root -Directory -Filter 'ghidra*' -ErrorAction SilentlyContinue
    foreach ($directory in $directories) {
        $properties = Join-Path $directory.FullName 'Ghydra\extension.properties'
        if (-not (Test-Path -LiteralPath $properties)) { continue }
        $payloads.Add([pscustomobject]@{
                Directory     = $directory.FullName
                ExtensionDir  = (Join-Path $directory.FullName 'Ghydra')
                GhidraVersion = (Get-IniValue -Path $properties -Key 'ghidraVersion')
                Version       = (Get-IniValue -Path $properties -Key 'version')
            })
    }
    return $payloads
}

# ---------------------------------------------------------------------------
# Extension installation
# ---------------------------------------------------------------------------

function Install-Extension {
    param([string]$Ghidra, $Payload, [bool]$Remove)
    $result = [ordered]@{
        path      = $Ghidra
        version   = (Get-IniValue -Path (Join-Path $Ghidra 'Ghidra\application.properties') -Key 'application.version')
        payload   = if ($Payload) { $Payload.GhidraVersion } else { $null }
        installed = $false
        changed   = $false
        detail    = $null
    }
    $target = Join-Path $Ghidra 'Extensions\Ghydra\Ghydra'
    if ($Remove) {
        if (Test-Path -LiteralPath $target) {
            $result.installed = $true
            $result.detail = 'removed'
            if (-not $DryRun) { Remove-Item -LiteralPath $target -Recurse -Force }
            $result.changed = $true
        } else {
            $result.detail = 'not installed'
        }
        return $result
    }
    if (-not $Payload) {
        $result.detail = 'no extension payload matches this Ghidra version'
        return $result
    }
    $currentVersion = Get-IniValue -Path (Join-Path $target 'extension.properties') -Key 'version'
    if ($currentVersion -eq $Payload.Version -and -not $Force) {
        $result.installed = $true
        $result.detail = "up to date ($currentVersion)"
        return $result
    }
    $result.installed = $true
    $result.changed = $true
    $result.detail = if ($currentVersion) { "replaced $currentVersion with $($Payload.Version)" } else { "installed $($Payload.Version)" }
    if (-not $DryRun) {
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
        Copy-Item -LiteralPath $Payload.ExtensionDir -Destination $target -Recurse -Force
    }
    return $result
}

# ---------------------------------------------------------------------------
# Harness definitions
# ---------------------------------------------------------------------------

function New-ClassicEntry {
    param([string]$Uv, [string]$Bridge)
    return [ordered]@{
        command = $Uv
        args    = @('run', '--script', $Bridge)
        env     = [ordered]@{ GHYDRA_HYDRA_HOST = 'localhost' }
    }
}

function Get-HarnessDefinitions {
    param([string]$Uv, [string]$Bridge)
    $classic = New-ClassicEntry -Uv $Uv -Bridge $Bridge
    $userHome = $env:USERPROFILE
    $appData = $env:APPDATA
    $codeUser = Join-Path $appData 'Code\User'
    $definitions = @(
        [pscustomobject]@{
            Name   = 'Claude Code'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.claude.json')
            Root   = 'mcpServers'
            Entry  = [ordered]@{ type = 'stdio'; command = $Uv; args = @('run', '--script', $Bridge); env = [ordered]@{ GHYDRA_HYDRA_HOST = 'localhost' } }
            Detect = { param($p) Test-Path -LiteralPath $p }
        },
        [pscustomobject]@{
            Name   = 'Claude Desktop'
            Kind   = 'json'
            Path   = (Join-Path $appData 'Claude\claude_desktop_config.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) Test-Path -LiteralPath (Split-Path -Parent $p) }
        },
        [pscustomobject]@{
            Name   = 'Codex CLI'
            Kind   = 'toml'
            Path   = (Join-Path $userHome '.codex\config.toml')
            Root   = 'mcp_servers'
            Entry  = $classic
            Detect = { param($p) Test-Path -LiteralPath (Split-Path -Parent $p) }
        },
        [pscustomobject]@{
            Name   = 'Gemini CLI'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.gemini\settings.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'Cursor'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.cursor\mcp.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'Windsurf'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.codeium\windsurf\mcp_config.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'Cline'
            Kind   = 'json'
            Path   = (Join-Path $codeUser 'globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) Test-Path -LiteralPath (Split-Path -Parent $p) }
        },
        [pscustomobject]@{
            Name   = 'Roo Code'
            Kind   = 'json'
            Path   = (Join-Path $codeUser 'globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) Test-Path -LiteralPath (Split-Path -Parent $p) }
        },
        [pscustomobject]@{
            Name   = 'VS Code'
            Kind   = 'json'
            Path   = (Join-Path $codeUser 'mcp.json')
            Root   = 'servers'
            Entry  = [ordered]@{ type = 'stdio'; command = $Uv; args = @('run', '--script', $Bridge); env = [ordered]@{ GHYDRA_HYDRA_HOST = 'localhost' } }
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'Zed'
            Kind   = 'json'
            Path   = (Join-Path $appData 'Zed\settings.json')
            Root   = 'context_servers'
            Entry  = [ordered]@{ command = [ordered]@{ path = $Uv; args = @('run', '--script', $Bridge); env = [ordered]@{ GHYDRA_HYDRA_HOST = 'localhost' } } }
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'opencode'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.config\opencode\opencode.json')
            Root   = 'mcp'
            Entry  = [ordered]@{ type = 'local'; command = @($Uv, 'run', '--script', $Bridge); enabled = $true; environment = [ordered]@{ GHYDRA_HYDRA_HOST = 'localhost' } }
            Detect = { param($p) (Test-Path -LiteralPath $p) -or (Test-Path -LiteralPath (Split-Path -Parent $p)) }
        },
        [pscustomobject]@{
            Name   = 'Continue'
            Kind   = 'json'
            Path   = (Join-Path $userHome '.continue\config.json')
            Root   = 'mcpServers'
            Entry  = $classic
            Detect = { param($p) Test-Path -LiteralPath $p }
        }
    )
    if ($Harness) {
        $wanted = @($Harness | ForEach-Object { $_.ToLowerInvariant() })
        $definitions = @($definitions | Where-Object { $wanted -contains $_.Name.ToLowerInvariant() })
        if ($definitions.Count -eq 0) {
            throw "No known harness matches: $($Harness -join ', '). Use -Help for the list."
        }
    }
    return $definitions
}

# ---------------------------------------------------------------------------
# JSON harness configuration
# ---------------------------------------------------------------------------

function Test-Jsonc {
    param([string]$Text)
    return ($Text -match '(?m)^\s*//' -or $Text -match '/\*')
}

function Read-JsonObject {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return ([pscustomobject]@{}) }
    $text = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($text)) { return ([pscustomobject]@{}) }
    return ($text | ConvertFrom-Json)
}

function Write-TextAtomic {
    param([string]$Path, [string]$Text)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = Join-Path $parent ('.' + (Split-Path -Leaf $Path) + '.tmp-' + [guid]::NewGuid().ToString('N'))
    [System.IO.File]::WriteAllText($temporary, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Backup-Config {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $backup = $Path + '.bak'
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup -Force
    }
}

function Set-JsonHarness {
    param($Definition, [bool]$Remove)
    $path = $Definition.Path
    $state = 'skipped'
    $detail = $null
    $changed = $false
    if (-not (Test-Path -LiteralPath $path) -and $Remove) {
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'skipped'; detail = 'not configured'; changed = $false }
    }
    if (-not (& $Definition.Detect $path)) {
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'skipped'; detail = "harness not detected at $(Split-Path -Parent $path)"; changed = $false }
    }
    try {
        $raw = ''
        if (Test-Path -LiteralPath $path) {
            $raw = Get-Content -LiteralPath $path -Raw
        }
        if ($raw -and (Test-Jsonc -Text $raw)) {
            # Comment-bearing JSONC cannot be round-tripped without destroying the
            # comments, so never rewrite it: hand the exact fragment to the user.
            $fragment = [ordered]@{}
            $fragment[$Definition.Root] = [ordered]@{ ghydra = $Definition.Entry }
            $snippet = $fragment | ConvertTo-Json -Depth 100 -Compress
            return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'skipped'; detail = 'JSONC with comments; merge the snippet by hand'; changed = $false; snippet = $snippet }
        }
        $root = Read-JsonObject -Path $path
        $rootKey = $Definition.Root
        $existing = $null
        if ($root -is [System.Collections.IDictionary] -or $root -is [psobject]) {
            $property = $root.PSObject.Properties[$rootKey]
            if ($property) { $existing = $property.Value }
        }
        if ($Remove) {
            if (-not $existing -or -not $existing.PSObject.Properties['ghydra']) {
                return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'unchanged'; detail = 'no ghydra entry'; changed = $false }
            }
            if (-not $DryRun) {
                Backup-Config -Path $path
                $existing.PSObject.Properties.Remove('ghydra')
                # Give back the document the harness had before: an empty
                # container this script created is not part of the original file.
                if (@($existing.PSObject.Properties).Count -eq 0) {
                    $root.PSObject.Properties.Remove($rootKey)
                }
                Write-TextAtomic -Path $path -Text ($root | ConvertTo-Json -Depth 100)
            }
            return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'updated'; detail = 'ghydra entry removed'; changed = $true }
        }
        $entry = $Definition.Entry
        if ($existing -and $existing.PSObject.Properties['ghydra'] -and -not $Force) {
            $currentJson = ($existing.ghydra | ConvertTo-Json -Depth 100 -Compress)
            $wantedJson = ($entry | ConvertTo-Json -Depth 100 -Compress)
            if ($currentJson -eq $wantedJson) {
                return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'unchanged'; detail = 'ghydra entry already current'; changed = $false }
            }
        }
        if (-not $existing -and -not (Test-Path -LiteralPath $path)) {
            $state = 'configured'
        } else {
            $state = 'updated'
        }
        if (-not $DryRun) {
            Backup-Config -Path $path
            if (-not $root.PSObject.Properties[$rootKey]) {
                $root | Add-Member -MemberType NoteProperty -Name $rootKey -Value ([ordered]@{}) -Force
            }
            $container = $root.$rootKey
            if ($container -is [System.Collections.IDictionary]) {
                $container['ghydra'] = $entry
            } else {
                $container | Add-Member -MemberType NoteProperty -Name 'ghydra' -Value $entry -Force
            }
            Write-TextAtomic -Path $path -Text ($root | ConvertTo-Json -Depth 100)
        }
        $detail = if ($DryRun) { "dry run: $state" } else { $state }
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = $state; detail = $detail; changed = $true }
    } catch {
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'error'; detail = $_.Exception.Message; changed = $false }
    }
}

# ---------------------------------------------------------------------------
# TOML (Codex CLI) configuration
# ---------------------------------------------------------------------------

function New-TomlBlock {
    param([string]$Uv, [string]$Bridge)
    $escapedUv = $Uv.Replace('\', '\\')
    $escapedBridge = $Bridge.Replace('\', '\\')
    return @(
        '[mcp_servers.ghydra]',
        "command = `"$escapedUv`"",
        "args = [`"run`", `"--script`", `"$escapedBridge`"]",
        'env = { GHYDRA_HYDRA_HOST = "localhost" }'
    )
}

function Set-TomlHarness {
    param($Definition, [bool]$Remove, [string]$Uv, [string]$Bridge)
    $path = $Definition.Path
    if (-not (& $Definition.Detect $path)) {
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'skipped'; detail = "harness not detected at $(Split-Path -Parent $path)"; changed = $false }
    }
    try {
        $lines = @()
        if (Test-Path -LiteralPath $path) {
            $lines = @(Get-Content -LiteralPath $path)
        }
        $header = '[mcp_servers.ghydra]'
        $start = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i].Trim() -eq $header) { $start = $i; break }
        }
        if ($Remove) {
            if ($start -lt 0) {
                return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'unchanged'; detail = 'no ghydra block'; changed = $false }
            }
            $end = $lines.Count
            for ($i = $start + 1; $i -lt $lines.Count; $i++) {
                if ($lines[$i] -match '^\s*\[') { $end = $i; break }
            }
            $newLines = @()
            if ($start -gt 0) { $newLines += $lines[0..($start - 1)] }
            if ($end -lt $lines.Count) { $newLines += $lines[$end..($lines.Count - 1)] }
            while ($newLines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($newLines[-1])) {
                if ($newLines.Count -le 1) { $newLines = @(); break }
                $newLines = @($newLines[0..($newLines.Count - 2)])
            }
            if (-not $DryRun) {
                Backup-Config -Path $path
                Write-TextAtomic -Path $path -Text (($newLines -join [Environment]::NewLine) + [Environment]::NewLine)
            }
            return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'updated'; detail = 'ghydra block removed'; changed = $true }
        }
        $block = New-TomlBlock -Uv $Uv -Bridge $Bridge
        if ($start -ge 0 -and -not $Force) {
            $end = $lines.Count
            for ($i = $start + 1; $i -lt $lines.Count; $i++) {
                if ($lines[$i] -match '^\s*\[') { $end = $i; break }
            }
            $current = @($lines[$start..($end - 1)])
            if ((($current -join "`n").Trim()) -eq (($block -join "`n").Trim())) {
                return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'unchanged'; detail = 'ghydra block already current'; changed = $false }
            }
        }
        $newLines = @()
        if ($start -ge 0) {
            $end = $lines.Count
            for ($i = $start + 1; $i -lt $lines.Count; $i++) {
                if ($lines[$i] -match '^\s*\[') { $end = $i; break }
            }
            if ($start -gt 0) { $newLines += $lines[0..($start - 1)] }
            $newLines += $block
            if ($end -lt $lines.Count) { $newLines += '' ; $newLines += $lines[$end..($lines.Count - 1)] }
            $state = 'updated'
        } else {
            if ($lines.Count -gt 0) {
                $newLines += $lines
                if (-not [string]::IsNullOrWhiteSpace($lines[-1])) { $newLines += '' }
            }
            $newLines += $block
            $state = 'configured'
        }
        if (-not $DryRun) {
            Backup-Config -Path $path
            Write-TextAtomic -Path $path -Text (($newLines -join [Environment]::NewLine) + [Environment]::NewLine)
        }
        $detail = if ($DryRun) { "dry run: $state" } else { $state }
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = $state; detail = $detail; changed = $true }
    } catch {
        return [pscustomobject]@{ name = $Definition.Name; configPath = $path; state = 'error'; detail = $_.Exception.Message; changed = $false }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if ($RemoveExtension -and -not $Uninstall) {
    Write-Notice '-RemoveExtension only has an effect together with -Uninstall.'
}

$exitCode = 0
$bridge = $null
try {
    $bridge = Resolve-Bridge
} catch {
    Write-Notice $_.Exception.Message
    $exitCode = 1
}

$uv = Resolve-Uv
if (-not $uv) {
    Write-Notice 'uv was not found. Install it (scoop install uv) - the bridge runs through uv.'
}

$ghidraResults = @()
$changed = $false
if ($bridge) {
    $payloads = Get-ExtensionPayloads -Bridge $bridge
    $ghidraInstalls = Get-GhidraCandidates
    foreach ($ghidra in $ghidraInstalls) {
        if (-not (Test-GhidraInstall -Path $ghidra)) {
            Write-Notice "Skipping '$ghidra': no Ghidra\application.properties."
            continue
        }
        $version = Get-IniValue -Path (Join-Path $ghidra 'Ghidra\application.properties') -Key 'application.version'
        $payload = $payloads | Where-Object { $_.GhidraVersion -eq $version } | Select-Object -First 1
        $result = Install-Extension -Ghidra $ghidra -Payload $payload -Remove:($Uninstall -and $RemoveExtension)
        $ghidraResults += $result
        if ($result.changed) { $changed = $true }
    }
    if ($ghidraResults.Count -eq 0) {
        Write-Notice 'No Ghidra installation found. Pass -GhidraPath or set GHIDRA_HOME; the extension was not installed.'
    }
} else {
    Write-Notice 'bridge_mcp_hydra.py was not found. Install the scoop package (scoop install ghydramcp) or pass -BridgePath.'
    $exitCode = 1
}

$harnessResults = @()
if ($bridge) {
    if (-not $uv) {
        $definitions = Get-HarnessDefinitions -Uv $uv -Bridge $bridge
        foreach ($definition in $definitions) {
            if (-not (& $definition.Detect $definition.Path)) {
                $harnessResults += [pscustomobject]@{ name = $definition.Name; configPath = $definition.Path; state = 'skipped'; detail = "harness not detected at $(Split-Path -Parent $definition.Path)"; changed = $false }
            } else {
                $harnessResults += [pscustomobject]@{ name = $definition.Name; configPath = $definition.Path; state = 'error'; detail = 'uv not found; cannot build the server command'; changed = $false }
            }
        }
        $exitCode = 1
    } else {
        $definitions = Get-HarnessDefinitions -Uv $uv -Bridge $bridge
        foreach ($definition in $definitions) {
            if ($definition.Kind -eq 'toml') {
                $result = Set-TomlHarness -Definition $definition -Remove:$Uninstall -Uv $uv -Bridge $bridge
            } else {
                $result = Set-JsonHarness -Definition $definition -Remove:$Uninstall
            }
            $harnessResults += $result
            if ($result.changed) { $changed = $true }
            if ($result.state -eq 'error') { $exitCode = 1 }
        }
    }
}

if ($Json) {
    $document = [ordered]@{
        dryRun    = [bool]$DryRun
        uninstall = [bool]$Uninstall
        bridge    = $bridge
        uv        = $uv
        ghidra    = @($ghidraResults)
        harnesses = @($harnessResults)
        changed   = [bool]$changed
    }
    $document | ConvertTo-Json -Depth 20
} else {
    Write-Info ''
    if ($Uninstall) { Write-Info 'GhydraMCP uninstall' } else { Write-Info 'GhydraMCP setup' }
    Write-Info "  bridge : $(if ($bridge) { $bridge } else { '(not found)' })"
    Write-Info "  uv     : $(if ($uv) { $uv } else { '(not found)' })"
    Write-Info ''
    if ($ghidraResults.Count -gt 0) {
        Write-Info 'Ghidra extensions'
        $ghidraResults | ForEach-Object {
            Write-Info ("  {0}  ({1})  {2}" -f $_.path, $_.version, $_.detail)
        }
        Write-Info ''
    }
    if ($harnessResults.Count -gt 0) {
        Write-Info 'Harness configuration'
        $harnessResults | ForEach-Object {
            Write-Info ("  {0,-16} {1,-12} {2}" -f $_.name, $_.state, $_.detail)
        }
        $manual = @($harnessResults | Where-Object { $_.snippet })
        if ($manual.Count -gt 0) {
            Write-Info ''
            Write-Info 'Merge these fragments by hand (the files carry comments, so they are not rewritten):'
            foreach ($entry in $manual) {
                Write-Info ("  {0}: {1}" -f $entry.name, $entry.snippet)
            }
        }
        Write-Info ''
    }
    if ($DryRun) {
        Write-Info 'Dry run: nothing was written. Re-run without -DryRun to apply.'
    } elseif ($changed) {
        Write-Info 'Done. Restart the configured clients (and Ghidra) to pick up the changes.'
    } else {
        Write-Info 'Nothing to do: every detected target was already current.'
    }
}

exit $exitCode
