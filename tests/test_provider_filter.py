import importlib.util
from pathlib import Path


def load_update_all_module():
    root = Path(__file__).parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", str(root))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_filter_by_providers_only_and_skip(tmp_path):
    mod = load_update_all_module()
    # Create temporary dummy script files with provider hints
    s_github = tmp_path / "update-foo.py"
    s_google = tmp_path / "update-bar.py"
    s_other = tmp_path / "update-baz.py"
    s_github.write_text("https://api.github.com/repos/example/releases", encoding="utf-8")
    s_google.write_text("https://dl.google.com/something", encoding="utf-8")
    s_other.write_text("print('hello')", encoding="utf-8")

    scripts = [s_github, s_google, s_other]
    provider_map = {}

    only_res = mod.filter_by_providers(scripts, provider_map, only=["github"], skip=None)
    assert [p.name for p in only_res] == ["update-foo.py"]

    skip_res = mod.filter_by_providers(scripts, provider_map, only=None, skip=["google"]) 
    assert set([p.name for p in skip_res]) == {"update-foo.py", "update-baz.py"}
