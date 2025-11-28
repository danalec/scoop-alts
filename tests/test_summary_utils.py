import importlib.util
from pathlib import Path


def load_summary_utils():
    su_path = Path(__file__).parent.parent / "scripts" / "summary_utils.py"
    spec = importlib.util.spec_from_file_location("summary_utils", str(su_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_format_webhook_body_slack_basic():
    payload = {
        "counts": {"total": 3, "successful": 2, "failed": 1, "updated": 2},
        "results": [
            {"package": "a", "version": "1.0.0", "updated": True},
            {"package": "b", "version": "2.0.0", "updated": False},
            {"package": "c", "version": "3.0.0", "updated": True},
        ],
    }
    su = load_summary_utils()
    body = su.format_webhook_body(payload, "slack")
    assert "Scoop Update Summary" in body.get("text", "")
    assert "Total: 3" in body.get("text", "")
    assert "Updated: 2" in body.get("text", "")


def test_format_webhook_body_discord_basic():
    payload = {
        "counts": {"total": 1, "successful": 1, "failed": 0, "updated": 1},
        "results": [
            {"package": "x", "version": "9.9.9", "updated": True},
        ],
    }
    su = load_summary_utils()
    body = su.format_webhook_body(payload, "discord")
    assert "Scoop Update Summary" in body.get("content", "")
    assert "Total: 1" in body.get("content", "")
