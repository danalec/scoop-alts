"""Tests for the registry-driven updater path.

`update-all.py` resolves every package to a runnable target: registry entries go
through the single `update-package.py` runner, bespoke packages run their own
script. Both must keep the same logical `update-<package>.py` name, because
provider filtering, `--scripts`, resume and the summaries all key off it.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
REGISTRY_PATH = SCRIPTS_DIR / "packages.json"
PROVIDERS_PATH = SCRIPTS_DIR / "providers.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def update_all():
    return load_module("update_all", SCRIPTS_DIR / "update-all.py")


@pytest.fixture(scope="module")
def runner():
    return load_module("update_package", SCRIPTS_DIR / "update-package.py")


@pytest.fixture(scope="module")
def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_is_non_empty_object(registry):
    assert isinstance(registry, dict) and registry


def test_registry_entries_declare_the_fields_the_runner_passes_through(registry):
    for name, entry in registry.items():
        assert "name" not in entry, f"{name}: the runner supplies the name"
        assert entry.get("download_url_template"), f"{name}: needs a download url"
        assert entry.get("homepage"), f"{name}: needs a homepage for version discovery"


def test_registry_has_no_package_with_a_bespoke_script(registry):
    for name in registry:
        assert not (
            SCRIPTS_DIR / f"update-{name}.py"
        ).exists(), f"{name} is both a registry entry and a bespoke script"


def test_load_package_registry_reads_every_entry(update_all, registry):
    assert set(update_all.load_package_registry()) == set(registry)


def test_load_package_registry_tolerates_missing_file(update_all, tmp_path):
    missing = tmp_path / "packages.json"
    original = update_all.REGISTRY_PATH
    try:
        update_all.REGISTRY_PATH = missing
        assert update_all.load_package_registry() == {}
    finally:
        update_all.REGISTRY_PATH = original


def test_resolve_script_ref_prefers_a_real_file(update_all):
    ref = update_all.resolve_script_ref("update-kuna.py", {})
    assert ref is not None
    assert ref.name == "update-kuna.py"
    assert ref.path == SCRIPTS_DIR / "update-kuna.py"
    assert ref.args == ()


def test_resolve_script_ref_routes_registry_entries_to_the_runner(update_all, registry):
    name = next(iter(registry))
    ref = update_all.resolve_script_ref(f"update-{name}.py", registry)
    assert ref is not None
    assert ref.name == f"update-{name}.py"
    assert ref.path == update_all.REGISTRY_RUNNER
    assert ref.args == (name,)


def test_resolve_script_ref_returns_none_for_unknown_package(update_all):
    assert update_all.resolve_script_ref("update-does-not-exist.py", {}) is None


def test_discover_covers_every_package_with_a_manifest(update_all, registry):
    discovered = set(update_all.discover_update_scripts())
    manifests = {f"update-{path.stem}.py" for path in (REPO_ROOT / "bucket").glob("*.json")}
    assert manifests <= discovered, manifests - discovered


def test_discover_never_treats_the_orchestrator_as_a_package(update_all):
    discovered = update_all.discover_update_scripts()
    assert "update-all.py" not in discovered
    assert "update-package.py" not in discovered


def test_every_discovered_package_has_a_provider(update_all):
    providers = json.loads(PROVIDERS_PATH.read_text(encoding="utf-8"))
    discovered = update_all.discover_update_scripts()
    assert set(discovered) <= set(providers), set(discovered) - set(providers)


def test_build_config_passes_registry_fields_through(runner, registry):
    from version_detector import SoftwareVersionConfig

    name, entry = next(iter(registry.items()))
    config = runner.build_config(name, entry)
    assert isinstance(config, SoftwareVersionConfig)
    assert config.name == name
    assert config.homepage == entry["homepage"]
    assert config.download_url_template == entry["download_url_template"]


def test_runner_rejects_an_unknown_package(runner, capsys):
    assert runner.update_manifest("no-such-package", {}) is False
    assert "Unknown package" in capsys.readouterr().out


def test_runner_usage_error_exits_two(runner):
    with pytest.raises(SystemExit) as excinfo:
        runner.main([])
    assert excinfo.value.code == 2
