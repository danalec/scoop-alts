from pathlib import Path


def test_scripts_have_structured_only_and_json_output():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    targets = [p for p in scripts_dir.glob("update-*.py") if p.name not in ["update-all.py", "update-script-generator.py"]]
    assert targets, "no update scripts found"
    for p in targets:
        text = p.read_text("utf-8", errors="ignore")
        assert "STRUCTURED_ONLY" in text, f"missing STRUCTURED_ONLY handling in {p.name}"
        assert "json.dumps({\"updated\"" in text, f"missing structured JSON output in {p.name}"
