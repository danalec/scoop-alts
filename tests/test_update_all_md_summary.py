import importlib.util
from pathlib import Path


def load_update_all_module():
    root = Path(__file__).parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", str(root))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_write_md_summary_basic(tmp_path):
    mod = load_update_all_module()
    UpdateResult = getattr(mod, "UpdateResult")
    r1 = UpdateResult("update-a.py", True, "", 1.23, True)
    r2 = UpdateResult("update-b.py", True, "", 0.75, False)

    class Args:
        md_summary = tmp_path / "summary.md"
        timeout = 120
        workers = 2
        parallel = True
        github_workers = 3
        microsoft_workers = 3
        google_workers = 4

    mod.write_md_summary([r1, r2], 2.0, Args(), "Parallel")
    content = (tmp_path / "summary.md").read_text("utf-8")
    assert "# Update Health Dashboard" in content
    assert "| Package | Version | Success | Updated | Duration (s) |" in content
