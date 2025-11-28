from pathlib import Path
import json
import importlib.util


def load_update_all():
    scripts = Path(__file__).resolve().parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", scripts)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_filter_resume_paths(tmp_path):
    mod = load_update_all()
    p1 = tmp_path / "scripts" / "update-a.py"
    p2 = tmp_path / "scripts" / "update-b.py"
    p1.parent.mkdir(parents=True)
    p1.write_text("", encoding="utf-8")
    p2.write_text("", encoding="utf-8")

    summary = {
        "results": [
            {"script": "update-a.py", "success": False},
            {"script": "update-b.py", "success": True},
        ]
    }
    resume_path = tmp_path / "sum.json"
    resume_path.write_text(json.dumps(summary), encoding="utf-8")

    filtered = mod.filter_resume_paths([p1, p2], resume_path)
    assert [p.name for p in filtered] == ["update-a.py"]


def test_parse_script_output_respects_structured_flag():
    mod = load_update_all()
    mod.PREFER_STRUCTURED_OUTPUT = True
    updated, no_update_needed = mod.parse_script_output("Updated successfully", "update-x.py")
    assert updated is False
    assert no_update_needed is False
    mod.PREFER_STRUCTURED_OUTPUT = False
    updated2, no_update_needed2 = mod.parse_script_output("Updated successfully", "update-x.py")
    assert updated2 is True
