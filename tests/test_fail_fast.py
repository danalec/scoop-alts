import importlib.util
from pathlib import Path


def load_update_all():
    scripts = Path(__file__).resolve().parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", scripts)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sequential_fail_fast(tmp_path):
    mod = load_update_all()
    calls = []

    def fake_run_update_script_with_retry(p, timeout, retries):
        name = p.name
        calls.append(name)
        if name == "update-fail.py":
            return mod.UpdateResult(name, False, "error", 0.1, False)
        return mod.UpdateResult(name, True, "ok", 0.1, False)

    mod.run_update_script_with_retry = fake_run_update_script_with_retry
    p_ok = tmp_path / "update-ok.py"
    p_fail = tmp_path / "update-fail.py"
    p_after = tmp_path / "update-after.py"
    for p in [p_ok, p_fail, p_after]:
        p.write_text("", encoding="utf-8")

    results = mod.run_sequential([p_ok, p_fail, p_after], 1, 0.0, 0, fail_fast=True, max_fail=0)
    assert len(results) == 2
    assert calls == ["update-ok.py", "update-fail.py"]
