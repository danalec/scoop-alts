import json
from pathlib import Path
import importlib.util


def load_update_all():
    scripts = Path(__file__).resolve().parent.parent / "scripts" / "update-all.py"
    spec = importlib.util.spec_from_file_location("update_all", scripts)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_json_summary(tmp_path):
    mod = load_update_all()
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    with open(bucket / "demo.json", "w", encoding="utf-8") as f:
        f.write("{""version"": ""1.2.3""}")

    mod.BUCKET_DIR = bucket

    res = [mod.UpdateResult("update-demo.py", True, "", 1.23, True)]

    class Args:
        json_summary = tmp_path / "sum.json"
        timeout = 120
        workers = 3
        parallel = True
        github_workers = 3
        microsoft_workers = 3
        google_workers = 4

    mod.write_json_summary(res, 2.5, Args, "Parallel")
    data = json.loads((tmp_path / "sum.json").read_text("utf-8"))
    assert data["counts"]["updated"] == 1
    assert data["results"][0]["version"] == "1.2.3"
