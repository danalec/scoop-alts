"""Tests for ``bin/Install-GhydraMCP.ps1``, the GhydraMCP harness installer.

The script is the only supported way to put a GhydraMCP entry into the MCP
clients on a Windows host, so these tests drive the real PowerShell script
against a throw-away ``USERPROFILE``/``APPDATA`` tree: no test may read or write
the developer's actual harness configurations, and none may touch the network.

Covered: the script parses, ``-DryRun`` writes nothing, a real run merges one
entry without clobbering another server, a second run is a no-op, ``-Uninstall``
gives the original documents back, a missing bridge or ``uv`` fails loudly, the
Ghidra variant match installs only the exact version line, and ``-Harness``
narrows the target list.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "Install-GhydraMCP.ps1"
BRIDGE_NAME = "bridge_mcp_hydra.py"
EXTENSION_VERSION = "3.2.0"


def find_powershell():
    """Return the first usable PowerShell host, or None."""
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return path
    return None


POWERSHELL = find_powershell()
requires_powershell = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None,
    reason="the installer targets Windows and needs a PowerShell host",
)


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_ghidra(root, version):
    """Create a minimal Ghidra install whose application.properties declares version."""
    write_file(
        root / "Ghidra" / "application.properties",
        f"application.version={version}\napplication.release.name=PUBLIC\n",
    )
    return root


def make_payload(root):
    """Create the scoop payload layout: bridge plus one extension build per line."""
    write_file(root / BRIDGE_NAME, "# GhydraMCP bridge stub\n")
    for variant in ("ghidra11.4.3", "ghidra12.2"):
        extension = root / variant / "Ghydra"
        write_file(
            extension / "extension.properties",
            "name=Ghydra\nversion=3.2.0\nghidraVersion=%s\n" % variant.removeprefix("ghidra"),
        )
        write_file(extension / "lib" / "Ghydra.jar", "jar-bytes")
        write_file(extension / "Module.manifest", "")
        write_file(root / variant / "Ghidra" / "ghidra_scripts" / "GhidraHeadlessServer.java", "")
    return root


class Sandbox:
    """A throw-away Windows profile plus a fake Ghidra install and payload."""

    def __init__(self, root):
        self.root = root
        self.payload = make_payload(root / "payload")
        self.ghidra = make_ghidra(root / "ghidra_12.2_PUBLIC", "12.2")
        self.home = root / "home"
        self.appdata = root / "appdata"
        self.bin = root / "bin"
        self.empty_bin = root / "empty-bin"
        self.empty_bin.mkdir()
        self.temp = root / "temp"
        self.temp.mkdir()
        self.no_scoop = root / "no-scoop"
        self.claude = self.home / ".claude.json"
        self.cursor = self.home / ".cursor" / "mcp.json"
        self.codex = self.home / ".codex" / "config.toml"
        self.gemini = self.home / ".gemini" / "settings.json"
        self.vscode = self.appdata / "Code" / "User" / "mcp.json"
        write_file(
            self.claude,
            json.dumps({"mcpServers": {"other": {"command": "other.exe"}}, "numStartups": 3}),
        )
        write_file(
            self.cursor,
            json.dumps({"mcpServers": {"existing": {"command": "cursor-other"}}}),
        )
        write_file(self.codex, "[other]\nkey = 1\n")
        write_file(self.gemini, json.dumps({"theme": "dark"}, indent=2))
        write_file(
            self.vscode,
            json.dumps({"servers": {"vscode-other": {"type": "stdio", "command": "x"}}}),
        )
        # Zed settings are JSONC: the installer must never rewrite this file, and
        # must hand back a mergeable fragment instead of dropping the target.
        self.zed = self.appdata / "Zed" / "settings.json"
        write_file(self.zed, '// Zed settings\n{\n  "theme": "One Dark"\n}\n')
        write_file(self.bin / "uv.cmd", "@echo off\r\n")
        self.base_env = self._env(self.bin)

    def _env(self, bin_dir, extra=None):
        """Build a child environment that cannot see the real profile or scoop root."""
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        environment = {
            "SystemRoot": system_root,
            "ComSpec": os.environ.get("ComSpec", str(Path(system_root) / "System32" / "cmd.exe")),
            # Without PATHEXT a child PowerShell cannot resolve `uv.cmd` through
            # Get-Command, which would make every harness look unconfigurable.
            "PATHEXT": ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.PY;.PYW",
            "TEMP": str(self.temp),
            "TMP": str(self.temp),
            "USERPROFILE": str(self.home),
            "APPDATA": str(self.appdata),
            "LOCALAPPDATA": str(self.appdata),
            "SCOOP": str(self.no_scoop),
            "ProgramFiles": str(self.root / "no-program-files"),
            "ProgramFiles(x86)": str(self.root / "no-program-files-x86"),
            "PATH": os.pathsep.join([str(bin_dir), str(Path(system_root) / "System32")]),
        }
        if extra:
            environment.update(extra)
        return environment

    def run(self, *arguments, env=None, timeout=300):
        command = [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env or self.base_env,
            cwd=str(REPO_ROOT),
            timeout=timeout,
        )

    def run_json(self, *arguments, env=None):
        process = self.run(*arguments, "-Json", env=env)
        payload = None
        if process.stdout.strip():
            payload = json.loads(process.stdout)
        return process, payload

    def install_arguments(self):
        return ["-BridgePath", str(self.payload / BRIDGE_NAME), "-GhidraPath", str(self.ghidra)]

    def snapshot(self):
        """Every file the installer may touch, ignoring PowerShell's own profile cache."""
        ignored = self.home / "AppData"
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ignored not in path.parents
        }

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def sandbox(tmp_path):
    if POWERSHELL is None or os.name != "nt":
        pytest.skip("the installer test needs a Windows PowerShell host")
    return Sandbox(tmp_path)


@requires_powershell
def test_installer_help_lists_parameters(sandbox):
    process = sandbox.run("-Help")
    combined = process.stdout + process.stderr
    assert process.returncode == 0
    assert "BridgePath" in combined
    assert "GhidraPath" in combined


@requires_powershell
def test_dry_run_writes_nothing_and_reports_detected_targets(sandbox):
    before = sandbox.snapshot()

    process, payload = sandbox.run_json("-DryRun", *sandbox.install_arguments())

    assert process.returncode == 0, process.stderr
    assert payload["dryRun"] is True
    assert payload["bridge"].endswith(BRIDGE_NAME)
    assert payload["uv"].endswith("uv.cmd")
    ghidra = {entry["path"]: entry for entry in payload["ghidra"]}
    assert ghidra[str(sandbox.ghidra)]["version"] == "12.2"
    assert ghidra[str(sandbox.ghidra)]["payload"] == "12.2"
    states = {entry["name"]: entry["state"] for entry in payload["harnesses"]}
    assert states["Claude Code"] == "updated"
    assert states["Cursor"] == "updated"
    assert states["Codex CLI"] == "configured"
    assert states["Zed"] == "skipped"
    zed = next(entry for entry in payload["harnesses"] if entry["name"] == "Zed")
    fragment = json.loads(zed["snippet"])
    assert "ghydra" in fragment["context_servers"]
    assert sandbox.snapshot() == before


@requires_powershell
def test_real_run_merges_entries_without_clobbering_other_servers(sandbox):
    process, payload = sandbox.run_json(*sandbox.install_arguments())

    assert process.returncode == 0, process.stderr
    assert payload["changed"] is True

    claude = sandbox.read_json(sandbox.claude)
    assert claude["numStartups"] == 3
    assert claude["mcpServers"]["other"]["command"] == "other.exe"
    ghydra = claude["mcpServers"]["ghydra"]
    assert ghydra["type"] == "stdio"
    assert ghydra["args"] == ["run", "--script", str(sandbox.payload / BRIDGE_NAME)]
    assert ghydra["env"]["GHYDRA_HYDRA_HOST"] == "localhost"

    cursor = sandbox.read_json(sandbox.cursor)
    assert cursor["mcpServers"]["existing"]["command"] == "cursor-other"
    assert "ghydra" in cursor["mcpServers"]

    codex = sandbox.codex.read_text(encoding="utf-8")
    assert "[other]" in codex
    assert "[mcp_servers.ghydra]" in codex
    assert BRIDGE_NAME in codex

    gemini = sandbox.read_json(sandbox.gemini)
    assert gemini["theme"] == "dark"
    assert "ghydra" in gemini["mcpServers"]

    vscode = sandbox.read_json(sandbox.vscode)
    assert vscode["servers"]["vscode-other"]["command"] == "x"
    assert vscode["servers"]["ghydra"]["type"] == "stdio"

    assert sandbox.zed.read_text(encoding="utf-8").startswith("// Zed settings")

    extension = sandbox.ghidra / "Extensions" / "Ghydra" / "Ghydra" / "extension.properties"
    assert extension.is_file()
    assert f"version={EXTENSION_VERSION}" in extension.read_text(encoding="utf-8")


@requires_powershell
def test_second_run_changes_nothing(sandbox):
    first, _ = sandbox.run_json(*sandbox.install_arguments())
    assert first.returncode == 0, first.stderr
    after_first = sandbox.snapshot()

    second, payload = sandbox.run_json(*sandbox.install_arguments())

    assert second.returncode == 0, second.stderr
    assert payload["changed"] is False
    detected = [entry for entry in payload["harnesses"] if entry["state"] != "skipped"]
    assert detected
    assert all(entry["state"] == "unchanged" for entry in detected)
    assert sandbox.snapshot() == after_first


@requires_powershell
def test_uninstall_restores_original_documents(sandbox):
    original_claude = sandbox.read_json(sandbox.claude)
    original_cursor = sandbox.read_json(sandbox.cursor)
    original_gemini = sandbox.read_json(sandbox.gemini)
    original_vscode = sandbox.read_json(sandbox.vscode)
    original_codex = "".join(sandbox.codex.read_text(encoding="utf-8").split())

    install, _ = sandbox.run_json(*sandbox.install_arguments())
    assert install.returncode == 0, install.stderr

    uninstall, payload = sandbox.run_json("-Uninstall", *sandbox.install_arguments())

    assert uninstall.returncode == 0, uninstall.stderr
    assert payload["uninstall"] is True
    assert sandbox.read_json(sandbox.claude) == original_claude
    assert sandbox.read_json(sandbox.cursor) == original_cursor
    assert sandbox.read_json(sandbox.gemini) == original_gemini
    assert sandbox.read_json(sandbox.vscode) == original_vscode
    assert "".join(sandbox.codex.read_text(encoding="utf-8").split()) == original_codex

    extension = sandbox.ghidra / "Extensions" / "Ghydra" / "Ghydra"
    assert extension.is_dir()

    removed, removed_payload = sandbox.run_json(
        "-Uninstall", "-RemoveExtension", *sandbox.install_arguments()
    )
    assert removed.returncode == 0, removed.stderr
    assert not extension.exists()
    assert removed_payload["ghidra"][0]["detail"] == "removed"


@requires_powershell
def test_missing_bridge_fails_with_exit_code_one(sandbox):
    missing = sandbox.root / "does-not-exist" / BRIDGE_NAME

    process, payload = sandbox.run_json("-DryRun", "-BridgePath", str(missing))

    assert process.returncode == 1
    assert payload["bridge"] is None
    assert "does not exist" in (process.stdout + process.stderr)


@requires_powershell
def test_missing_uv_fails_with_exit_code_one(sandbox):
    environment = sandbox._env(sandbox.empty_bin)

    process, payload = sandbox.run_json("-DryRun", *sandbox.install_arguments(), env=environment)

    assert process.returncode == 1
    assert payload["uv"] is None
    states = {entry["name"]: entry["state"] for entry in payload["harnesses"]}
    assert states["Claude Code"] == "error"
    assert states["Cursor"] == "error"
    assert set(states.values()) <= {"error", "skipped"}
    assert all(
        "uv not found" in entry["detail"]
        for entry in payload["harnesses"]
        if entry["state"] == "error"
    )


@requires_powershell
def test_harness_filter_only_touches_named_harness(sandbox):
    before = sandbox.read_json(sandbox.claude)

    process, payload = sandbox.run_json("-Harness", "Cursor", *sandbox.install_arguments())

    assert process.returncode == 0, process.stderr
    assert [entry["name"] for entry in payload["harnesses"]] == ["Cursor"]
    assert payload["harnesses"][0]["state"] == "updated"
    assert sandbox.read_json(sandbox.claude) == before
    assert "ghydra" in sandbox.read_json(sandbox.cursor)["mcpServers"]


@requires_powershell
def test_mismatched_ghidra_line_is_reported_not_installed(sandbox):
    other = make_ghidra(sandbox.root / "ghidra_12.1.4_PUBLIC", "12.1.4")
    environment = sandbox._env(sandbox.bin, {"GHIDRA_HOME": str(other)})

    process, payload = sandbox.run_json(*sandbox.install_arguments(), env=environment)

    assert process.returncode == 0, process.stderr
    entries = {entry["path"]: entry for entry in payload["ghidra"]}
    assert entries[str(other)]["version"] == "12.1.4"
    assert entries[str(other)]["payload"] is None
    assert entries[str(other)]["installed"] is False
    assert not (other / "Extensions" / "Ghydra" / "Ghydra").exists()
    assert entries[str(sandbox.ghidra)]["installed"] is True
