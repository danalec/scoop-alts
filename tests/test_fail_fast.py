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


def _script_refs(mod, tmp_path, names):
    refs = []
    for name in names:
        path = tmp_path / name
        path.write_text("", encoding="utf-8")
        refs.append(mod.ScriptRef(name=name, path=path))
    return refs


def test_parallel_fail_fast_stops_the_run(tmp_path):
    # The parallel path is the default one, and it used to ignore --fail-fast
    # and --max-falt entirely.
    mod = load_update_all()
    started = []

    def fake_run(script_ref, timeout, retries):
        started.append(script_ref.name)
        if "fail" in script_ref.name:
            return mod.UpdateResult(script_ref.name, False, "error", 0.1, False)
        return mod.UpdateResult(script_ref.name, True, "ok", 0.1, False)

    mod.run_update_script_with_retry = fake_run
    refs = _script_refs(mod, tmp_path, ["update-a.py", "update-fail.py", "update-z.py"])

    results = mod.run_parallel(refs, 5, 1, fail_fast=True, max_fail=0)

    # The scripts before the failure still ran; nothing after it was started.
    assert [r.script_name for r in results] == ["update-a.py", "update-fail.py"]
    assert "update-z.py" not in started


def test_parallel_max_fail_stops_after_n_failures(tmp_path):
    mod = load_update_all()

    def fake_run(script_ref, timeout, retries):
        if "fail" in script_ref.name:
            return mod.UpdateResult(script_ref.name, False, "error", 0.1, False)
        return mod.UpdateResult(script_ref.name, True, "ok", 0.1, False)

    mod.run_update_script_with_retry = fake_run
    refs = _script_refs(
        mod, tmp_path, ["update-fail1.py", "update-fail2.py", "update-ok.py", "update-last.py"]
    )

    results = mod.run_parallel(refs, 5, 1, fail_fast=False, max_fail=1)

    names = [r.script_name for r in results]
    assert names == ["update-fail1.py"]
    assert "update-ok.py" not in names


def test_parallel_without_fail_fast_runs_everything(tmp_path):
    mod = load_update_all()

    def fake_run(script_ref, timeout, retries):
        if "fail" in script_ref.name:
            return mod.UpdateResult(script_ref.name, False, "error", 0.1, False)
        return mod.UpdateResult(script_ref.name, True, "ok", 0.1, False)

    mod.run_update_script_with_retry = fake_run
    refs = _script_refs(mod, tmp_path, ["update-fail.py", "update-ok.py", "update-last.py"])

    results = mod.run_parallel(refs, 5, 1, fail_fast=False, max_fail=0)

    assert len(results) == 3
