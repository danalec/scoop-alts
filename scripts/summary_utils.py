from typing import Dict, Any

def format_webhook_body(payload: Dict[str, Any], webhook_type: str) -> Dict[str, Any]:
    if webhook_type == "slack":
        counts = payload.get("counts", {})
        updated = [r for r in payload.get("results", []) if r.get("updated")]
        lines = [
            "Scoop Update Summary",
            f"Total: {counts.get('total', 0)} | Success: {counts.get('successful', 0)} | Failed: {counts.get('failed', 0)} | Updated: {counts.get('updated', 0)}",
        ]
        if updated:
            first = ", ".join([f"{u.get('package','')} {u.get('version','')}".strip() for u in updated[:10]])
            lines.append(f"Updated: {first}")
        return {"text": "\n".join(lines)}
    if webhook_type == "discord":
        counts = payload.get("counts", {})
        updated = [r for r in payload.get("results", []) if r.get("updated")]
        lines = [
            "Scoop Update Summary",
            f"Total: {counts.get('total', 0)} | Success: {counts.get('successful', 0)} | Failed: {counts.get('failed', 0)} | Updated: {counts.get('updated', 0)}",
        ]
        if updated:
            first = ", ".join([f"{u.get('package','')} {u.get('version','')}".strip() for u in updated[:10]])
            lines.append(f"Updated: {first}")
        return {"content": "\n".join(lines)}
    return payload
