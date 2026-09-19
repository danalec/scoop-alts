from pathlib import Path


def test_scripts_have_structured_only_and_json_output():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    targets = [
        p
        for p in scripts_dir.glob("update-*.py")
        if p.name not in ["update-all.py", "update-script-generator.py"]
    ]
    assert targets, "no update scripts found"
    for p in targets:
        text = p.read_text("utf-8", errors="ignore")
        has_inline_handling = "STRUCTURED_ONLY" in text and "json.dumps" in text
        uses_shared_helper = "ManifestUpdater" in text or "emit_result" in text
        assert (
            has_inline_handling or uses_shared_helper
        ), f"missing structured-only handling in {p.name}"
