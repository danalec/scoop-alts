"""Regression tests for the orchestrator's git integration.

The scheduler is the only automatic writer of the bucket, and it resets the
working tree to origin/main before every run. A commit or push that fails
must therefore fail the run: a zero exit is recorded as success, no alert is
sent, and the next run discards the unpublished change.
"""

import importlib.util
from pathlib import Path

import pytest


def _load(name, relative):
    path = Path(__file__).resolve().parent.parent / "scripts" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def update_all():
    return _load("update_all", "update-all.py")


@pytest.fixture
def git_helpers():
    return _load("git_helpers_probe", "git_helpers.py")


def _args(**overrides):
    class Args:
        skip_git = False
        git_per_package = False
        git_aggregate = False

    args = Args()
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _result(name, success, updated=False):
    class Result:
        def __init__(self):
            self.script_name = name
            self.success = success
            self.updated = updated
            self.output = ""
            self.duration = 0.1

    return Result()


@pytest.fixture
def neutral_git(update_all, monkeypatch, tmp_path):
    """Replace every git-touching helper so no test can touch the real repo."""
    monkeypatch.setattr(update_all, "BUCKET_DIR", tmp_path)
    monkeypatch.setattr(update_all, "stage_bucket_changes", lambda: None)
    monkeypatch.setattr(update_all, "get_staged_bucket_changes", lambda: ([], [], []))
    monkeypatch.setattr(update_all, "list_untracked_manifests", lambda: [])
    monkeypatch.setattr(update_all, "get_removed_manifests", lambda: [])
    monkeypatch.setattr(update_all, "stage_manifest", lambda p: True)
    monkeypatch.setattr(update_all, "commit_with_message", lambda *a, **k: True)
    monkeypatch.setattr(update_all, "push_changes", lambda: True)
    monkeypatch.setattr(update_all, "run_git_command", lambda *a, **k: (0, "", ""))
    return update_all


class TestHandleGitIntegration:
    def test_failed_push_is_reported(self, neutral_git, monkeypatch):
        monkeypatch.setattr(neutral_git, "push_changes", lambda: False)

        assert neutral_git.handle_git_integration(_args(), []) is False

    def test_failed_commit_is_reported(self, neutral_git, monkeypatch):
        # The per-package path is the default one (--git-aggregate switches off
        # it), so a failed per-package commit has to surface.
        monkeypatch.setattr(neutral_git, "stage_and_commit_per_package", lambda results: False)

        results = [_result("update-x.py", success=True, updated=True)]
        assert neutral_git.handle_git_integration(_args(), results) is False

    def test_failed_aggregate_commit_is_reported(self, neutral_git, monkeypatch):
        monkeypatch.setattr(neutral_git, "get_staged_bucket_changes", lambda: (["new"], [], []))
        monkeypatch.setattr(neutral_git, "commit_with_message", lambda *a, **k: False)

        assert neutral_git.handle_git_integration(_args(git_aggregate=True), []) is False

    def test_successful_push_is_reported(self, neutral_git):
        assert neutral_git.handle_git_integration(_args(), []) is True

    def test_skip_git_is_not_a_failure(self, update_all):
        assert update_all.handle_git_integration(_args(skip_git=True), []) is True

    def test_untracked_manifest_of_failed_updater_is_not_published(
        self, neutral_git, tmp_path, monkeypatch
    ):
        manifest = tmp_path / "newpkg.json"
        manifest.write_text('{"version": "0.0.1"}', encoding="utf-8")
        staged = []
        monkeypatch.setattr(neutral_git, "list_untracked_manifests", lambda: [("newpkg", manifest)])
        monkeypatch.setattr(neutral_git, "stage_manifest", lambda p: staged.append(p) or True)

        neutral_git.handle_git_integration(_args(), [_result("update-newpkg.py", success=False)])

        assert staged == []

    def test_untracked_manifest_of_successful_updater_is_published(
        self, neutral_git, tmp_path, monkeypatch
    ):
        manifest = tmp_path / "newpkg.json"
        manifest.write_text('{"version": "0.0.1"}', encoding="utf-8")
        staged = []
        committed = []
        monkeypatch.setattr(neutral_git, "list_untracked_manifests", lambda: [("newpkg", manifest)])
        monkeypatch.setattr(neutral_git, "stage_manifest", lambda p: staged.append(p) or True)
        monkeypatch.setattr(
            neutral_git,
            "commit_with_message",
            lambda msg, **k: committed.append(msg) or True,
        )

        neutral_git.handle_git_integration(_args(), [_result("update-newpkg.py", success=True)])

        assert staged == [manifest]
        assert committed and committed[0].startswith("newpkg: Add version")

    def test_removed_manifest_is_committed(self, neutral_git, monkeypatch):
        committed = []
        monkeypatch.setattr(neutral_git, "get_removed_manifests", lambda: ["gone"])
        monkeypatch.setattr(
            neutral_git,
            "commit_with_message",
            lambda msg, **k: committed.append(msg) or True,
        )

        neutral_git.handle_git_integration(_args(), [])

        assert committed == ["gone: Remove manifest"]

    def test_manifest_left_half_written_by_a_failed_updater_is_not_staged(
        self, neutral_git, tmp_path, monkeypatch
    ):
        # An updater that timed out may have left a truncated manifest on disk.
        # A bulk "git add -u" would stage it and publish a broken manifest, so
        # the staging is restricted to the packages whose updater succeeded.
        staged = []
        monkeypatch.setattr(
            neutral_git, "stage_bucket_changes", lambda allowed=None: staged.append(allowed)
        )
        monkeypatch.setattr(neutral_git, "get_removed_manifests", lambda: [])

        results = [
            _result("update-ok.py", success=True, updated=True),
            _result("update-timeout.py", success=False),
        ]
        neutral_git.handle_git_integration(_args(git_aggregate=True), results)

        assert staged == [{"ok"}]


class TestCommitScope:
    def test_commit_uses_a_restricted_index(self, git_helpers, monkeypatch):
        # A pathspec on "git commit" would commit the *working tree* state of
        # those paths and ignore the index, publishing changes that were never
        # staged. The commit runs against a temporary index instead.
        calls = []
        monkeypatch.setattr(
            git_helpers,
            "run_git_command",
            lambda args, cwd=None, env=None: (calls.append((args, env)), (0, "", ""))[1],
        )

        git_helpers.commit_with_message("msg", paths=["bucket/app.json"])

        args, env = calls[-1]
        assert args == ["git", "commit", "-m", "msg"]
        assert env is not None
        assert "GIT_INDEX_FILE" in env

    def test_commit_without_paths_uses_the_whole_index(self, git_helpers, monkeypatch):
        calls = []
        monkeypatch.setattr(
            git_helpers,
            "run_git_command",
            lambda args, cwd=None, env=None: (calls.append((args, env)), (0, "", ""))[1],
        )

        git_helpers.commit_with_message("msg")

        args, env = calls[-1]
        assert args == ["git", "commit", "-m", "msg"]
        assert env is None

    def test_commit_manifest_change_reports_a_failed_push(self, git_helpers, tmp_path, monkeypatch):
        manifest = tmp_path / "app.json"
        manifest.write_text('{"version": "1.0.0"}', encoding="utf-8")
        monkeypatch.setattr(git_helpers, "run_git_command", lambda *a, **k: (0, "A\tapp.json", ""))
        monkeypatch.setattr(git_helpers, "commit_with_message", lambda *a, **k: True)
        monkeypatch.setattr(git_helpers, "push_changes", lambda: False)

        assert git_helpers.commit_manifest_change("app", str(manifest), push=True) is False


class TestSuccessfulPackages:
    def test_only_successful_updaters_count(self, update_all):
        results = [
            _result("update-ok.py", success=True),
            _result("update-bad.py", success=False),
        ]

        assert update_all.successful_packages(results) == {"ok"}
