"""Tests for package registration -- the path the wizard now uses.

The wizard used to write one boilerplate ``update-<pkg>.py`` per manifest, a
125-line transcription of four values that the manifest already carries in its
``checkver`` and ``autoupdate`` blocks. It now writes an entry into
``scripts/packages.json`` instead, so the package has one definition rather than
two that can disagree.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "update-package.py"

BASE_MANIFEST = {
    "version": "1.0.0",
    "description": "A tool",
    "license": "MIT",
    "homepage": "https://example.com/tool",
    "checkver": {"url": "https://example.com/tool", "regex": r"v([0-9.]+)"},
    "autoupdate": {"url": "https://example.com/dl/tool-$version.zip"},
}


def load_runner():
    spec = importlib.util.spec_from_file_location("update_package", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner():
    return load_runner()


@pytest.fixture
def workspace(tmp_path):
    """A bucket plus an empty registry, so nothing real is ever written."""
    bucket = tmp_path / "bucket"
    scripts = tmp_path / "scripts"
    bucket.mkdir()
    scripts.mkdir()
    return bucket, scripts, scripts / "packages.json"


def write_manifest(bucket, name, manifest=None):
    path = bucket / f"{name}.json"
    path.write_text(json.dumps(manifest or BASE_MANIFEST, indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------- manifest_to_entry


def test_manifest_to_entry_uses_checkver(runner):
    entry = runner.manifest_to_entry(dict(BASE_MANIFEST))

    assert entry["homepage"] == "https://example.com/tool"
    assert entry["version_patterns"] == [r"v([0-9.]+)"]
    assert entry["download_url_template"] == "https://example.com/dl/tool-$version.zip"
    assert entry["description"] == "A tool"
    assert entry["license"] == "MIT"


def test_manifest_to_entry_falls_back_to_homepage(runner):
    manifest = dict(BASE_MANIFEST)
    manifest.pop("checkver")
    manifest["autoupdate"] = {"url": "https://example.com/dl/tool.zip"}

    entry = runner.manifest_to_entry(manifest)

    assert entry["homepage"] == "https://example.com/tool"
    assert entry["version_patterns"] == [runner.DEFAULT_VERSION_REGEX]


def test_manifest_to_entry_reads_architecture_autoupdate(runner):
    manifest = dict(BASE_MANIFEST)
    manifest["autoupdate"] = {"architecture": {"64bit": {"url": "https://x/a-$version.zip"}}}

    assert runner.manifest_to_entry(manifest)["download_url_template"] == "https://x/a-$version.zip"


def test_manifest_to_entry_marks_http_urls_for_upgrade(runner):
    manifest = dict(BASE_MANIFEST)
    manifest["autoupdate"] = {"url": "http://example.com/dl/tool-$version.zip"}

    assert runner.manifest_to_entry(manifest)["force_https"] is True


def test_manifest_to_entry_omits_force_https_for_https(runner):
    assert "force_https" not in runner.manifest_to_entry(dict(BASE_MANIFEST))


# ------------------------------------------------------------- register_package


def test_register_package_creates_entry(runner, workspace):
    bucket, scripts, registry = workspace
    write_manifest(bucket, "tool")

    assert runner.register_package("tool", bucket, registry, scripts) is True
    assert json.loads(registry.read_text(encoding="utf-8"))["tool"]["license"] == "MIT"


def test_register_package_is_idempotent(runner, workspace):
    bucket, scripts, registry = workspace
    write_manifest(bucket, "tool")

    runner.register_package("tool", bucket, registry, scripts)
    first = registry.read_text(encoding="utf-8")
    runner.register_package("tool", bucket, registry, scripts)

    assert registry.read_text(encoding="utf-8") == first


def test_register_package_preserves_other_entries(runner, workspace):
    bucket, scripts, registry = workspace
    registry.write_text(
        json.dumps({"existing": {"homepage": "https://x", "description": "d", "license": "L"}}),
        encoding="utf-8",
    )
    write_manifest(bucket, "tool")

    runner.register_package("tool", bucket, registry, scripts)

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert set(data) == {"existing", "tool"}


def test_register_package_sorts_entries(runner, workspace):
    bucket, scripts, registry = workspace
    write_manifest(bucket, "zeta")
    write_manifest(bucket, "alpha")

    runner.register_package("zeta", bucket, registry, scripts)
    runner.register_package("alpha", bucket, registry, scripts)

    keys = list(json.loads(registry.read_text(encoding="utf-8")))
    assert keys == sorted(keys)


def test_register_package_refuses_bespoke_updater(runner, workspace):
    # A bespoke script exists because a registry entry cannot express the
    # package; two definitions for one manifest is a conflict, not a fallback.
    bucket, scripts, registry = workspace
    write_manifest(bucket, "tool")
    (scripts / "update-tool.py").write_text("# bespoke\n", encoding="utf-8")

    assert runner.register_package("tool", bucket, registry, scripts) is False
    assert not registry.exists()


def test_register_package_refuses_missing_manifest(runner, workspace):
    bucket, scripts, registry = workspace

    assert runner.register_package("absent", bucket, registry, scripts) is False


def test_register_package_refuses_manifest_without_template(runner, workspace):
    # No autoupdate url means the detector would have nothing to download;
    # registering it would create a package that always fails at run time.
    bucket, scripts, registry = workspace
    manifest = dict(BASE_MANIFEST)
    manifest.pop("autoupdate")
    write_manifest(bucket, "tool", manifest)

    assert runner.register_package("tool", bucket, registry, scripts) is False


# --------------------------------------------------------------- real registry


def test_every_registry_package_has_a_manifest(runner):
    registry = runner.load_registry()
    bucket = REPO_ROOT / "bucket"

    missing = [name for name in registry if not (bucket / f"{name}.json").exists()]
    assert not missing, f"registry entries without a manifest: {missing}"


def test_no_bespoke_updater_is_also_a_registry_entry(runner):
    # The orchestrator unions both sources; a package present in both would be
    # resolved twice and whichever ran first would win.
    registry = runner.load_registry()
    bespoke = {
        path.stem.removeprefix("update-")
        for path in (REPO_ROOT / "scripts").glob("update-*.py")
        if path.name not in {"update-all.py", "update-package.py"}
    }

    assert not (bespoke & set(registry)), f"registered and bespoke: {bespoke & set(registry)}"
