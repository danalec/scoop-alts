# ghydramcp

Scoop package for [GhydraMCP](https://github.com/danalec/GhydraMCP): a Ghidra
extension that serves a HATEOAS REST API for every open CodeBrowser, plus a
stdio MCP bridge and installer that wire that API into the most common AI agent
harnesses.

## What the package installs

Upstream publishes **one extension build per Ghidra version line** and refuses
to load a build whose declared `ghidraVersion` differs from the running Ghidra.
The package therefore ships both supported builds instead of guessing:

```text
%SCOOP%\apps\ghydramcp\current\
  bridge_mcp_hydra.py            # stdio MCP server (PEP 723 inline deps)
  ghidra11.4.3\Ghydra\           # extension for Ghidra 11.4.3
  ghidra11.4.3\Ghidra\ghidra_scripts\
  ghidra12.2\Ghydra\             # extension for Ghidra 12.2
  ghidra12.2\Ghidra\ghidra_scripts\
```

`GHYDRAMCP_HOME` is set to that directory. The release assets used are the plain
`Ghydra-v<version>-<stamp>-ghidra<line>.zip` builds (not the `Ghydra-Complete`
wrapper, which nests the same extension inside another zip), plus
`bridge_mcp_hydra.py` as a third asset.

## Install

```powershell
scoop bucket add danalec_scoop-alts https://github.com/danalec/scoop-alts
scoop install ghydramcp
```

Scoop verifies all three SHA-256 hashes and extracts each Ghidra variant into its
own subdirectory (`extract_to` is paired with archives by index in Scoop's
`lib/decompress.ps1`, so the bridge asset is not affected).

## Enable the extension

Installing the files is not enabling the plugin:

1. Copy `current\<variant>\Ghydra` into `<Ghidra>\Extensions\Ghidra\Ghydra`, or
   let `bin/Install-GhydraMCP.ps1` do it (it reads
   `<Ghidra>\Ghidra\application.properties` and refuses a variant mismatch).
2. Restart Ghidra, open a program in CodeBrowser.
3. `File` -> `Configure` -> `Developer`, tick **Ghydra**, confirm.

The first CodeBrowser binds port 8192; later instances take 8193 and up.

## Bridge

The bridge is a stdio MCP server and must be launched by the client, not by
hand:

```powershell
uv run --script $env:GHYDRAMCP_HOME\bridge_mcp_hydra.py
```

`uv` is required: the script carries its pinned dependencies in PEP 723 inline
metadata (`mcp==1.6.0`, `requests`, `pydantic<2.14`). `uv` lives at
`%SCOOP%\apps\python\current\Scripts\uv.exe` when Python is installed through
Scoop. GUI clients do not inherit `PATH`, so the installer writes the absolute
`uv` path into their configuration.

## Wire the harnesses

`bin\Install-GhydraMCP.ps1` is the harness installer. Run it from the bucket
checkout:

```powershell
$installer = "$env:SCOOP\buckets\danalec_scoop-alts\bin\Install-GhydraMCP.ps1"
pwsh $installer -DryRun     # show what would change; writes nothing
pwsh $installer             # merge the ghydra server into every detected harness
```

It auto-detects the Ghidra install(s) and the client configurations that exist on
the machine, merges **one** `ghydra` stdio server entry into each, leaves every
other server untouched, and never requires elevation. A missing client is
skipped, never created speculatively.

| Harness | Configuration file | Entry key |
| :--- | :--- | :--- |
| Claude Code | `%USERPROFILE%\.claude.json` (or `claude mcp add-json`) | `mcpServers` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` |
| Codex CLI | `%USERPROFILE%\.codex\config.toml` | `[mcp_servers.ghydra]` |
| Gemini CLI | `%USERPROFILE%\.gemini\settings.json` | `mcpServers` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` | `mcpServers` |
| Windsurf | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` | `mcpServers` |
| Cline | `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json` | `mcpServers` |
| Roo Code | `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json` | `mcpServers` |
| VS Code (Copilot) | `%APPDATA%\Code\User\mcp.json` | `servers` |
| Zed | `%APPDATA%\Zed\settings.json` | `context_servers` |
| opencode | `%USERPROFILE%\.config\opencode\opencode.json` | `mcp` |
| Continue | `%USERPROFILE%\.continue\config.json` | `mcpServers` |

Options: `-BridgePath`, `-GhidraPath`, `-Harness`, `-DryRun`, `-Json`,
`-Uninstall`, `-RemoveExtension`, `-FromScoop`, `-Force`, `-Help`.
`-Uninstall` removes only the `ghydra` entries; `-RemoveExtension` also removes
the extension directory the installer installed. `-Json` prints one machine
readable document (used by `tests/test_ghydramcp_installer.py`):
`{ dryRun, uninstall, bridge, uv, ghidra: [...], harnesses: [...], changed }`.
Each write is atomic (temporary file in the same directory) and the first change
to an existing file leaves a `<file>.bak` copy.

Files that are JSONC (comments allowed, such as Zed's `settings.json`) are
**never rewritten** - comments cannot be round-tripped safely - so the installer
reports the harness as `skipped` and emits the exact fragment to merge under a
`snippet` key (the human table prints it too).

## Keeping it current

`scripts/update-ghydramcp.py` reads the latest GitHub release, selects the two
Ghidra-variant zips and the bridge by asset name (the names embed a build
timestamp, so no Scoop `autoupdate` block can be used), takes the SHA-256 from
the release asset `digest` field, and rewrites only `version`/`url`/`hash`/
`extract_to`. Run it directly or let `scripts/update-all.py` pick it up:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python scripts\update-ghydramcp.py
```

## Troubleshooting

- **Ghidra does not list Ghydra** - the extension directory is in the wrong
  place or was not enabled in `Configure` -> `Developer`; the plugin only loads in
  CodeBrowser.
- **Version mismatch on load** - install the variant that matches
  `Ghidra\application.properties` exactly; the 11.4.3 build will not load in a
  12.x Ghidra and vice versa.
- **Client starts but no tools appear** - the client could not launch `uv`:
  check the absolute path in its configuration, and that
  `uv run --script <bridge>` works from a terminal.
- **Tools return connection errors** - no CodeBrowser is running with the
  plugin enabled, or the instance listens on a port other than 8192 (set
  `GHIDRA_HYDRA_HOST`/`GHYDRA_PORT` in the server `env`).
