#!/usr/bin/env python3
"""
Git helper utilities for Scoop update scripts
Provides per-script staging, commit, and optional push functionality so
individual update scripts can auto-commit their manifest changes.
"""

import subprocess
from pathlib import Path
import json

REPO_ROOT = Path(__file__).parent.parent

def run_git_command(args, cwd: Path = REPO_ROOT):
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            encoding="utf-8",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def get_manifest_version_from_file(manifest_path: Path) -> str:
    """Read version field from a manifest JSON file."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            return str(manifest.get("version", "")).strip()
    except Exception:
        return ""

def commit_manifest_change(app_name: str, manifest_path: str, push: bool = False) -> bool:
    """Stage and commit a single manifest if it has changes. Optionally push.

    Returns True if a commit was created, False otherwise.
    """
    p = Path(manifest_path)
    if not p.exists():
        print(f"⚠️  Auto-commit skipped: manifest not found: {manifest_path}")
        return False

    # Stage the manifest file
    rc, out, err = run_git_command(["git", "add", str(p)])
    if rc != 0:
        print(f"⚠️  git add failed: {err or out}")
        return False

    # Check if there are staged changes for this path
    rc, ns_out, ns_err = run_git_command(["git", "diff", "--cached", "--name-status", "--", str(p)])
    if rc != 0:
        print(f"⚠️  git diff --cached failed: {ns_err or ns_out}")
        return False

    if not ns_out.strip():
        print(f"ℹ️  No staged changes for {app_name}, skipping commit.")
        return False

    status_line = ns_out.strip().splitlines()[0]
    status_code = status_line.split("\t", 1)[0] if "\t" in status_line else ""
    new_file = status_code.startswith("A")

    version_str = get_manifest_version_from_file(p)
    if new_file:
        msg = f"{app_name}: Add version {version_str}" if version_str else f"{app_name}: Add manifest"
    else:
        msg = f"{app_name}: Update to version {version_str}" if version_str else f"{app_name}: Update manifest"

    rc, out, err = run_git_command(["git", "commit", "-m", msg])
    if rc != 0:
        reason = err or out
        if "nothing to commit" in reason.lower():
            print("ℹ️  No changes staged to commit.")
        else:
            print(f"⚠️  git commit failed: {reason}")
        return False

    print(out or "✅ Commit created")

    if push:
        push_changes()

    return True

def push_changes():
    """Push committed changes to the remote."""
    rc, out, err = run_git_command(["git", "push"])
    if rc != 0:
        print(f"⚠️  git push failed: {err or out}")
    else:
        print(out or "⬆️  Pushed changes to remote")