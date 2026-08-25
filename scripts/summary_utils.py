"""Helpers for formatting orchestrator summaries for outbound notifications."""

from __future__ import annotations

from typing import Any, Dict, List


def _build_summary_lines(payload: Dict[str, Any]) -> List[str]:
    """Return a compact text summary shared by Slack and Discord payloads."""
    counts = payload.get("counts", {})
    updated = [result for result in payload.get("results", []) if result.get("updated")]

    lines = [
        "Scoop Update Summary",
        (
            f"Total: {counts.get('total', 0)} | "
            f"Success: {counts.get('successful', 0)} | "
            f"Failed: {counts.get('failed', 0)} | "
            f"Updated: {counts.get('updated', 0)}"
        ),
    ]

    if updated:
        packages = [
            f"{item.get('package', '')} {item.get('version', '')}".strip()
            for item in updated[:10]
        ]
        lines.append(f"Updated: {', '.join(packages)}")

    return lines


def format_webhook_body(payload: Dict[str, Any], webhook_type: str) -> Dict[str, Any]:
    """Format webhook payloads for supported providers."""
    lines = _build_summary_lines(payload)
    if webhook_type == "slack":
        return {"text": "\n".join(lines)}
    if webhook_type == "discord":
        return {"content": "\n".join(lines)}
    return payload
