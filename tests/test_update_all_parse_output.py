import importlib.util
from pathlib import Path


def load_update_all_module():
    root = Path(__file__).parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", str(root))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_parse_script_output_structured_json_and_cache():
    mod = load_update_all_module()
    out = '{"updated": true, "name": "a", "version": "1.2.3"}'
    updated, no_update = mod.parse_script_output(out, "update-a.py")
    assert updated is True
    assert no_update is False
    assert mod.get_manifest_version("a") == "1.2.3"


def test_parse_script_output_text_heuristics():
    mod = load_update_all_module()
    out = "Update completed successfully"
    updated, no_update = mod.parse_script_output(out, "update-b.py")
    assert updated is True
