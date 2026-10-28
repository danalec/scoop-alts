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
        json.dump({"version": "1.2.3"}, f)

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


def _run_main(monkeypatch, argv):
    """Invoke update-all.py's main() with a synthetic argv.

    `--dry-run` returns before any updater runs, so this never touches the network.
    """
    mod = load_update_all()
    monkeypatch.setattr("sys.argv", ["update-all.py", *argv])
    # Keep the test hermetic if the host happens to export these overrides.
    monkeypatch.delenv("AUTOMATION_JSON_SUMMARY", raising=False)
    monkeypatch.delenv("AUTOMATION_MD_SUMMARY", raising=False)
    # On Windows this detaches and replaces sys.stdout, which tears down capsys.
    monkeypatch.setattr(mod, "ensure_utf8_console", lambda: None)
    mod.main()
    return mod


def test_dry_run_with_json_summary_warns_and_writes_nothing(monkeypatch, tmp_path, capsys):
    target = tmp_path / "update-summary.json"
    _run_main(monkeypatch, ["--dry-run", "--json-summary", str(target)])

    assert "--dry-run writes no summary" in capsys.readouterr().out
    assert not target.exists()


def test_dry_run_with_md_summary_warns(monkeypatch, tmp_path, capsys):
    target = tmp_path / "update-summary.md"
    _run_main(monkeypatch, ["--dry-run", "--md-summary", str(target)])

    assert "--dry-run writes no summary" in capsys.readouterr().out
    assert not target.exists()


def test_dry_run_without_summary_flags_does_not_warn(monkeypatch, capsys):
    _run_main(monkeypatch, ["--dry-run"])

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "--dry-run writes no summary" not in out


def test_summary_separates_upstream_failures_from_code_failures(tmp_path):
    mod = load_update_all()

    class Args:
        json_summary = tmp_path / "sum.json"
        timeout = 120
        workers = 3
        parallel = True
        github_workers = 3
        microsoft_workers = 3
        google_workers = 4

    results = [
        mod.UpdateResult("update-ok.py", True, "", 1.0, True),
        mod.UpdateResult(
            "update-net.py", False, "NewConnectionError: Connection refused", 2.0, False
        ),
        mod.UpdateResult("update-bug.py", False, "KeyError: 'version'", 0.5, False),
    ]

    mod.write_json_summary(results, 3.5, Args, "Parallel")
    data = json.loads((tmp_path / "sum.json").read_text("utf-8"))

    assert data["counts"]["failed"] == 2
    assert data["counts"]["failed_upstream"] == 1
    assert data["counts"]["failed_code"] == 1
    assert data["failures"] == [
        {"package": "net", "kind": "upstream"},
        {"package": "bug", "kind": "code"},
    ]
    kinds = {r["package"]: r["failure_kind"] for r in data["results"]}
    assert kinds["net"] == "upstream"
    assert kinds["bug"] == "code"


def test_webhook_body_names_the_upstream_packages():
    mod = load_update_all()
    payload = {
        "counts": {"total": 3, "successful": 2, "failed": 1, "updated": 1},
        "results": [{"package": "ok", "version": "1.0.0", "updated": True}],
        "failures": [{"package": "vendor-pkg", "kind": "upstream"}],
    }

    body = mod.format_webhook_body(payload, "slack")

    assert "Upstream/network failures: vendor-pkg" in body["text"]
    assert "Failures in our code" not in body["text"]
