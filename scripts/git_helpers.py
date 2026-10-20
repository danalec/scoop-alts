#!/usr/bin/env python3
"""Git helper utilities used by the Scoop automation scripts."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

if os.environ.get("AUTOMATION_LIB_SILENT") == "1":

    def _noop_print(*args, **kwargs):
        return None

    print = _noop_print

_DEFAULT_REPO_ROOT = Path(__file__).parent.parent


def _detect_repo_root() -> Path:
    """Detect the git repository root with a local fallback."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(_DEFAULT_REPO_ROOT),
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return _DEFAULT_REPO_ROOT

    if result.returncode == 0 and result.stdout.strip():
        repo_root = Path(result.stdout.strip())
        if repo_root.exists():
            return repo_root
    return _DEFAULT_REPO_ROOT


REPO_ROOT = _detect_repo_root()
BUCKET_DIR = REPO_ROOT / "bucket"
MANIFEST_EXTENSION = ".json"


def run_git_command(args: Sequence[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run a git command and return ``(returncode, stdout, stderr)``."""
    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            cwd=str(cwd or REPO_ROOT),
            encoding="utf-8",
            errors="replace",
        )
    except Exception as error:
        logger.error("Git command failed: %s", error)
        return 1, "", str(error)

    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_manifest_version_from_file(manifest_path: Path) -> str:
    """Read and return the version field from a manifest file."""
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError:
        logger.error("Manifest file not found: %s", manifest_path)
        return ""
    except json.JSONDecodeError as error:
        logger.error("Invalid JSON in manifest %s: %s", manifest_path, error)
        return ""
    except Exception as error:
        logger.error("Error reading manifest %s: %s", manifest_path, error)
        return ""

    version = str(manifest.get("version", "")).strip()
    logger.debug("Found version '%s' in %s", version, manifest_path)
    return version


def commit_with_message(message: str, paths: Optional[Sequence[str]] = None) -> bool:
    """Create a commit with the given message.

    ``paths`` scopes the commit to the given pathspec. Without it the commit
    takes the whole index, which swept in unrelated staged files and left a
    rejected commit's leftovers for the next package's commit.
    """
    args = ["git", "commit", "-m", message]
    if paths:
        args += ["--", *paths]

    rc, out, err = run_git_command(args)
    if rc != 0:
        reason = err or out
        if "nothing to commit" in reason.lower():
            print("ℹ️  No changes staged to commit.")
        else:
            print(f"⚠️  git commit failed: {reason}")
        return False

    print(out or "✅ Commit created")
    return True


def commit_manifest_change(app_name: str, manifest_path: str, push: bool = False) -> bool:
    """Stage and commit a single manifest if it contains changes."""
    path = Path(manifest_path)
    if not path.exists():
        print(f"⚠️  Auto-commit skipped: manifest not found: {manifest_path}")
        return False

    rc, out, err = run_git_command(["git", "add", str(path)])
    if rc != 0:
        print(f"⚠️  git add failed: {err or out}")
        return False

    rc, staged_out, staged_err = run_git_command(
        ["git", "diff", "--cached", "--name-status", "--", str(path)]
    )
    if rc != 0:
        print(f"⚠️  git diff --cached failed: {staged_err or staged_out}")
        return False
    if not staged_out.strip():
        print(f"ℹ️  No staged changes for {app_name}, skipping commit.")
        return False

    status_line = staged_out.strip().splitlines()[0]
    new_file = status_line.split("\t", 1)[0].startswith("A")
    version = get_manifest_version_from_file(path)
    if new_file:
        message = f"{app_name}: Add version {version}" if version else f"{app_name}: Add manifest"
    else:
        message = (
            f"{app_name}: Update to version {version}"
            if version
            else f"{app_name}: Update manifest"
        )

    if not commit_with_message(message, paths=[str(path)]):
        return False

    if push:
        return push_changes()
    return True


def push_changes() -> bool:
    """Push commits to the configured remote unless dry-run is enabled."""
    if os.environ.get("SCOOP_GIT_DRY_RUN") == "1":
        print("ℹ️  Git dry run enabled; skipping push.")
        return True

    command = ["git", "push"]
    remote = os.environ.get("SCOOP_GIT_REMOTE")
    branch = os.environ.get("SCOOP_GIT_BRANCH")
    if remote:
        command.append(remote)
        if branch:
            command.append(branch)
    elif branch:
        command.append("origin")
        command.append(branch)

    rc, out, err = run_git_command(command)
    if rc != 0:
        print(f"⚠️  git push failed: {err or out}")
        return False

    print(out or "⬆️  Pushed changes to remote")
    return True


def stage_bucket_changes() -> None:
    """Stage changes to *tracked* manifests inside ``bucket/``.

    Only tracked files are staged on purpose. ``git add bucket`` also stages
    untracked manifests, and an untracked manifest whose updater failed must
    not be published; the caller stages those explicitly, one by one, once
    their updater succeeded.
    """
    rc, out, err = run_git_command(["git", "add", "-u", "--", "bucket"])
    if rc != 0:
        print(f"⚠️  git add failed: {err or out}")


def stage_manifest(manifest_path: Path) -> bool:
    """Stage a single manifest, including a newly created one."""
    rc, out, err = run_git_command(["git", "add", "--", str(manifest_path)])
    if rc != 0:
        print(f"⚠️  git add {manifest_path} failed: {err or out}")
        return False
    return True


def get_staged_bucket_changes() -> Tuple[List[str], List[str], List[str]]:
    """Return ``(added_apps, updated_apps, deleted_apps)`` from staged bucket changes.

    Deletions are reported because ``git add bucket`` stages them too: a
    manifest removed from the bucket used to be invisible here, and the
    aggregate git path then concluded there was nothing to commit and left the
    removal staged but uncommitted.
    """
    rc, out, err = run_git_command(["git", "diff", "--cached", "--name-status"])
    if rc != 0:
        print(f"⚠️  git diff --cached failed: {err or out}")
        return [], [], []

    prefix = f"{BUCKET_DIR.name}/"
    added: List[str] = []
    updated: List[str] = []
    deleted: List[str] = []

    def _manifest_name(path_text: str) -> Optional[str]:
        normalized_path = path_text.replace("\\", "/")
        if not normalized_path.startswith(prefix) or not normalized_path.endswith(
            MANIFEST_EXTENSION
        ):
            return None
        return Path(normalized_path).stem

    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue

        status = parts[0]
        if status.startswith("R"):
            # A rename prints "R100\told\tnew": the old manifest is gone and
            # the new one is genuinely new. Reporting only the old name (as a
            # plain "R" would) attributes the change to a package that no
            # longer exists.
            if len(parts) < 3:
                continue
            old_name = _manifest_name(parts[1])
            new_name = _manifest_name(parts[2])
            if old_name:
                deleted.append(old_name)
            if new_name:
                added.append(new_name)
            continue

        name = _manifest_name(parts[1])
        if name is None:
            continue

        if status.startswith("A"):
            added.append(name)
        elif status.startswith("M"):
            updated.append(name)
        elif status.startswith("D"):
            deleted.append(name)

    return sorted(added), sorted(updated), sorted(deleted)


def get_removed_manifests() -> List[str]:
    """Return manifests deleted from the working tree but still tracked in HEAD.

    The per-package git path stages one manifest at a time and never stages the
    whole bucket, so a manifest dropped from the bucket would otherwise stay
    deleted on disk and uncommitted, silently drifting from HEAD.
    """
    rc, out, err = run_git_command(["git", "diff", "--name-status", "--", BUCKET_DIR.name])
    if rc != 0:
        print(f"⚠️  git diff failed: {err or out}")
        return []

    prefix = f"{BUCKET_DIR.name}/"
    removed: List[str] = []

    for line in out.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) != 2:
            continue

        status, path_text = parts
        if not status.startswith("D"):
            continue

        normalized_path = path_text.replace("\\", "/")
        if not normalized_path.startswith(prefix) or not normalized_path.endswith(
            MANIFEST_EXTENSION
        ):
            continue

        removed.append(Path(normalized_path).stem)

    return sorted(removed)


def list_untracked_manifests() -> List[Tuple[str, Path]]:
    """Return untracked manifest files inside ``bucket/``."""
    rc, out, err = run_git_command(
        ["git", "ls-files", "--others", "--exclude-standard", str(BUCKET_DIR)]
    )
    if rc != 0:
        print(f"⚠️  git ls-files failed: {err or out}")
        return []

    results: List[Tuple[str, Path]] = []
    bucket_prefix = f"{BUCKET_DIR.name}/"

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue

        path = Path(line)
        if path.is_absolute():
            if str(path).startswith(str(BUCKET_DIR)):
                results.append((path.stem, path))
            continue

        normalized = line.replace("\\", "/")
        if normalized.startswith(bucket_prefix):
            results.append((path.stem, REPO_ROOT / path))

    return results


def maybe_auto_commit(app_name: str, manifest_path: Path, argv: Sequence[str]) -> None:
    """Commit and push a manifest when auto-commit is requested.

    Extracted from the per-updater ``auto_commit`` block that every updater
    copied verbatim; the behaviour and the failure mode (warn, never abort the
    run) are unchanged.
    """
    requested = (
        "--auto-commit" in argv
        or os.environ.get("AUTO_COMMIT") == "1"
        or os.environ.get("SCOOP_AUTO_COMMIT") == "1"
    )
    if not requested:
        return

    try:
        commit_manifest_change(app_name, str(manifest_path), push=True)
    except Exception as error:
        print(f"⚠️  Auto-commit failed: {error}")
