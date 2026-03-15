#!/usr/bin/env python3
"""
Git helper utilities for Scoop update scripts
Provides per-script staging, commit, and optional push functionality so
individual update scripts can auto-commit their manifest changes.
"""

import subprocess
from pathlib import Path
import json
import logging
from typing import List, Tuple, Optional

# Set up logging
logger = logging.getLogger(__name__)

import os
if os.environ.get('AUTOMATION_LIB_SILENT') == '1':
    def _noop_print(*args, **kwargs):
        return None
    print = _noop_print

# Default fallback for REPO_ROOT (used before git detection)
_DEFAULT_REPO_ROOT = Path(__file__).parent.parent


def _detect_repo_root() -> Path:
    """Detect repository root using git, with fallback to default."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(_DEFAULT_REPO_ROOT),
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            p = Path(result.stdout.strip())
            if p.exists():
                return p
    except Exception:
        pass
    return _DEFAULT_REPO_ROOT


REPO_ROOT = _detect_repo_root()
BUCKET_DIR = REPO_ROOT / 'bucket'
MANIFEST_EXTENSION = '.json'

def run_git_command(args, cwd: Path = None):
    """Run a git command and return (returncode, stdout, stderr)."""
    if cwd is None:
        cwd = REPO_ROOT
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            encoding="utf-8",
            errors="replace"  # Handle encoding errors gracefully
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        logger.error(f"Git command failed: {e}")
        return 1, "", str(e)

def get_manifest_version_from_file(manifest_path: Path) -> str:
    """Read version field from a manifest JSON file."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            version = str(manifest.get("version", "")).strip()
            logger.debug(f"Found version '{version}' in {manifest_path}")
            return version
    except FileNotFoundError:
        logger.error(f"Manifest file not found: {manifest_path}")
        return ""
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in manifest {manifest_path}: {e}")
        return ""
    except Exception as e:
        logger.error(f"Error reading manifest {manifest_path}: {e}")
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

def stage_bucket_changes() -> None:
    """Stage changes inside the bucket directory."""
    rc, out, err = run_git_command(["git", "add", "bucket"])
    if rc != 0:
        print(f"⚠️  git add failed: {err or out}")

def get_staged_bucket_changes() -> Tuple[List[str], List[str]]:
    """Return (added_apps, updated_apps) from staged changes under bucket/."""
    rc, out, err = run_git_command(["git", "diff", "--cached", "--name-status"])
    if rc != 0:
        print(f"⚠️  git diff --cached failed: {err or out}")
        return [], []

    # Parse lines and filter for bucket manifests
    added, updated = [], []
    prefix = f"{BUCKET_DIR.name}/"
    
    for line in out.splitlines():
        if (parts := line.strip().split("\t", 1)) and len(parts) == 2:
            status, path = parts
            # Normalize path separators just in case
            path = path.replace('\\', '/')
            if path.startswith(prefix) and path.endswith(MANIFEST_EXTENSION):
                stem = Path(path).stem
                if status.startswith("A"):
                    added.append(stem)
                elif status.startswith(("M", "R")):
                    updated.append(stem)

    return sorted(added), sorted(updated)

def list_untracked_manifests() -> List[Tuple[str, Path]]:
    """Return a list of (app_name, path) for untracked manifests under bucket/."""
    # We use REPO_ROOT as cwd for ls-files, so paths are relative to root
    rc, out, err = run_git_command(["git", "ls-files", "--others", "--exclude-standard", str(BUCKET_DIR)])
    if rc != 0:
        print(f"⚠️  git ls-files failed: {err or out}")
        return []
    
    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line: continue
        
        # If output is absolute, convert to relative or just check ends
        p = Path(line)
        if p.is_absolute():
             # If absolute, check if it starts with BUCKET_DIR
             if str(p).startswith(str(BUCKET_DIR)):
                 results.append((p.stem, p))
        else:
             # If relative, check if it starts with bucket/
             if line.replace('\\', '/').startswith(f"{BUCKET_DIR.name}/"):
                 results.append((p.stem, REPO_ROOT / p))
                 
    return results

def commit_with_message(message: str) -> bool:
    """Create a commit with the given message. Returns True if commit succeeded."""
    rc, out, err = run_git_command(["git", "commit", "-m", message])
    if rc != 0:
        reason = err or out
        if "nothing to commit" in reason.lower():
            print("ℹ️  No changes staged to commit.")
        else:
            print(f"⚠️  git commit failed: {reason}")
        return False
    print(out or "✅ Commit created")
    return True
