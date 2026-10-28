#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/generate-dashboard.py <summary.json> <output.md>")
        sys.exit(1)
    summary_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    if not summary_path.exists():
        print(f"Summary not found: {summary_path}")
        sys.exit(1)
    data = json.loads(summary_path.read_text("utf-8"))
    lines = []
    lines.append("# Update Health Dashboard")
    lines.append("")
    counts = data.get("counts", {})
    lines.append(f"- Total: {counts.get('total', 0)}")
    lines.append(f"- Successful: {counts.get('successful', 0)}")
    lines.append(f"- Failed: {counts.get('failed', 0)}")
    lines.append(f"- Updated: {counts.get('updated', 0)}")
    lines.append("")
    lines.append("| Package | Version | Success | Updated | Duration (s) |")
    lines.append("|---|---|---|---|---|")
    for r in data.get("results", []):
        pkg = r.get("package", "")
        version = r.get("version", "")
        success = str(r.get("success", False))
        updated = str(r.get("updated", False))
        dur = r.get("duration_seconds", 0)
        lines.append(f"| {pkg} | {version} | {success} | {updated} | {dur} |")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
