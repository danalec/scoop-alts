"""Tests for git_helpers module."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def load_git_helpers():
    """Load git_helpers module dynamically."""
    gh_path = Path(__file__).parent.parent / "scripts" / "git_helpers.py"
    spec = importlib.util.spec_from_file_location("git_helpers", str(gh_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


@pytest.fixture
def git_helpers():
    """Provide git_helpers module for testing."""
    return load_git_helpers()


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)

    # Create a test file and commit
    test_file = repo_dir / "test.txt"
    test_file.write_text("test content")
    subprocess.run(["git", "add", "test.txt"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    return repo_dir


@pytest.fixture
def temp_manifest(tmp_path):
    """Create a temporary manifest file for testing."""
    manifest_dir = tmp_path / "bucket"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "test-package.json"

    manifest_content = {
        "version": "1.2.3",
        "description": "Test package",
        "homepage": "https://example.com",
        "url": "https://example.com/test-1.2.3.exe",
        "hash": "sha256:abc123",
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_content, f)

    return manifest_path


class TestRunGitCommand:
    """Tests for run_git_command function."""

    def test_run_git_command_success(self, git_helpers):
        """Test successful git command execution."""
        returncode, stdout, stderr = git_helpers.run_git_command(["git", "--version"])

        assert returncode == 0
        assert "git version" in stdout.lower()

    def test_run_git_command_invalid(self, git_helpers):
        """Test git command with invalid arguments."""
        returncode, stdout, stderr = git_helpers.run_git_command(
            ["git", "invalid-command-that-does-not-exist"]
        )

        assert returncode != 0

    def test_run_git_command_with_cwd(self, git_helpers, tmp_path):
        """Test git command with custom working directory."""
        returncode, stdout, stderr = git_helpers.run_git_command(["git", "status"], cwd=tmp_path)

        # Should work even in non-git directory (returns error but doesn't crash)
        assert isinstance(returncode, int)
        assert isinstance(stdout, str)
        assert isinstance(stderr, str)


class TestDetectRepoRoot:
    """Tests for _detect_repo_root function."""

    def test_detect_repo_root_in_git_repo(self, git_helpers, temp_git_repo):
        """Test detecting repo root when inside a git repository."""
        # Patch the default root to point to our temp repo
        with patch.object(git_helpers, "_DEFAULT_REPO_ROOT", temp_git_repo):
            result = git_helpers._detect_repo_root()
            # Should return a path that exists
            assert result.exists()


class TestGetManifestVersionFromFile:
    """Tests for get_manifest_version_from_file function."""

    def test_get_version_success(self, git_helpers, temp_manifest):
        """Test reading version from a valid manifest."""
        version = git_helpers.get_manifest_version_from_file(temp_manifest)

        assert version == "1.2.3"

    def test_get_version_file_not_found(self, git_helpers, tmp_path):
        """Test reading version from non-existent file."""
        version = git_helpers.get_manifest_version_from_file(tmp_path / "nonexistent.json")

        assert version == ""

    def test_get_version_invalid_json(self, git_helpers, tmp_path):
        """Test reading version from invalid JSON file."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{ invalid json }")

        version = git_helpers.get_manifest_version_from_file(invalid_file)

        assert version == ""

    def test_get_version_missing_version_field(self, git_helpers, tmp_path):
        """Test reading version from manifest without version field."""
        manifest_path = tmp_path / "no-version.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"description": "No version here"}, f)

        version = git_helpers.get_manifest_version_from_file(manifest_path)

        assert version == ""


class TestCommitManifestChange:
    """Tests for commit_manifest_change function."""

    def test_commit_nonexistent_file(self, git_helpers, tmp_path):
        """Test committing a non-existent file."""
        result = git_helpers.commit_manifest_change(
            "test-package", str(tmp_path / "nonexistent.json"), push=False
        )

        assert result is False

    def test_commit_no_changes(self, git_helpers, temp_git_repo, temp_manifest):
        """Test committing when there are no changes."""
        with patch.object(git_helpers, "REPO_ROOT", temp_git_repo):
            # Add and commit the manifest inside the repo first
            repo_manifest = temp_git_repo / "test-package.json"
            repo_manifest.write_text(temp_manifest.read_text(encoding="utf-8"), encoding="utf-8")
            subprocess.run(["git", "add", "test-package.json"], cwd=temp_git_repo, check=True)
            subprocess.run(["git", "commit", "-m", "Add manifest"], cwd=temp_git_repo, check=True)

            # Try to commit again without changes
            result = git_helpers.commit_manifest_change(
                "test-package", str(repo_manifest), push=False
            )

            # Should return False because there are no changes
            assert result is False


class TestPushChanges:
    """Tests for push_changes function."""

    def test_push_no_remote(self, git_helpers, temp_git_repo, capsys):
        """Test pushing when there's no remote configured."""
        with patch.object(git_helpers, "REPO_ROOT", temp_git_repo):
            result = git_helpers.push_changes()
            captured = capsys.readouterr()
            # No remote configured, so the push fails gracefully
            assert result is False
            assert "failed" in captured.out.lower() or "error" in captured.out.lower()

    def test_push_skips_when_dry_run_enabled(self, git_helpers, monkeypatch, capsys):
        """Test push_changes honors the dry-run environment override."""
        monkeypatch.setenv("SCOOP_GIT_DRY_RUN", "1")

        result = git_helpers.push_changes()

        captured = capsys.readouterr()
        assert result is True
        assert "dry run" in captured.out.lower()


class TestRepoRootConstant:
    """Tests for REPO_ROOT constant."""

    def test_repo_root_exists(self, git_helpers):
        """Test that REPO_ROOT is set and exists."""
        assert git_helpers.REPO_ROOT is not None
        assert isinstance(git_helpers.REPO_ROOT, Path)

    def test_repo_root_is_directory(self, git_helpers):
        """Test that REPO_ROOT is a directory."""
        assert git_helpers.REPO_ROOT.is_dir()


def _bucket_repo(tmp_path):
    """Build a git repo whose bucket/ holds two committed manifests."""
    repo_dir = tmp_path / "bucket_repo"
    (repo_dir / "bucket").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo_dir, check=True)
    for name in ("keep.json", "gone.json"):
        (repo_dir / "bucket" / name).write_text('{"version": "1.0.0"}', encoding="utf-8")
    subprocess.run(["git", "add", "bucket"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo_dir, check=True)
    return repo_dir


class TestStagedBucketChanges:
    """A deletion staged by the git path must be visible to the commit step."""

    def test_reports_added_updated_and_deleted(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        bucket = repo_dir / "bucket"
        (bucket / "gone.json").unlink()
        (bucket / "keep.json").write_text('{"version": "2.0.0"}', encoding="utf-8")
        (bucket / "new.json").write_text('{"version": "9.9.9"}', encoding="utf-8")

        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            git_helpers.stage_bucket_changes()
            # A new manifest is staged explicitly, never as a side effect of
            # staging the bucket - an untracked manifest is only published when
            # its updater succeeded.
            assert git_helpers.stage_manifest(bucket / "new.json") is True
            added, updated, deleted = git_helpers.get_staged_bucket_changes()

        assert added == ["new"]
        assert updated == ["keep"]
        assert deleted == ["gone"]

    def test_stage_bucket_changes_does_not_stage_untracked_manifests(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        (repo_dir / "bucket" / "new.json").write_text('{"version": "1.0.0"}', encoding="utf-8")

        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            git_helpers.stage_bucket_changes()
            added, updated, deleted = git_helpers.get_staged_bucket_changes()

        assert added == []
        assert (updated, deleted) == ([], [])

    def test_rename_reports_the_new_name_as_added(self, git_helpers, tmp_path):
        # git reports a rename as "R100\told\tnew"; reporting only the old name
        # would attribute the change to a package that no longer exists.
        repo_dir = _bucket_repo(tmp_path)
        bucket = repo_dir / "bucket"
        (bucket / "gone.json").rename(bucket / "new.json")

        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            git_helpers.stage_bucket_changes()
            assert git_helpers.stage_manifest(bucket / "new.json") is True
            added, updated, deleted = git_helpers.get_staged_bucket_changes()

        assert added == ["new"]
        assert deleted == ["gone"]
        assert updated == []

    def test_empty_bucket_reports_nothing(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            added, updated, deleted = git_helpers.get_staged_bucket_changes()

        assert (added, updated, deleted) == ([], [], [])


class TestRemovedManifests:
    """A manifest dropped from the working tree must be reported and committable."""

    def test_detects_working_tree_removal(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        (repo_dir / "bucket" / "gone.json").unlink()

        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            assert git_helpers.get_removed_manifests() == ["gone"]

    def test_no_removal_reports_nothing(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            assert git_helpers.get_removed_manifests() == []

    def test_removal_can_be_staged_and_committed(self, git_helpers, tmp_path):
        repo_dir = _bucket_repo(tmp_path)
        manifest_path = repo_dir / "bucket" / "gone.json"
        manifest_path.unlink()

        with patch.object(git_helpers, "REPO_ROOT", repo_dir):
            removed = git_helpers.get_removed_manifests()
            assert removed == ["gone"]
            rc, out, err = git_helpers.run_git_command(
                ["git", "add", "-A", "--", str(manifest_path)]
            )
            assert rc == 0, err or out
            assert git_helpers.commit_with_message("gone: Remove manifest") is True

        # The removal is now part of HEAD, not just staged.
        tracked = subprocess.run(
            ["git", "ls-files", "bucket"], cwd=repo_dir, capture_output=True, text=True, check=True
        ).stdout
        assert "gone.json" not in tracked
        assert "keep.json" in tracked
