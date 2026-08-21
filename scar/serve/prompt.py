"""Format recall results for injection into an agent prompt.

Never dump transcripts. Active corrections only. Abstain instead of inventing.
"""

from __future__ import annotations

from typing import Any

ABSTAIN_MESSAGE = (
    "SCAR has no stored correction for this context. Do not invent a house rule."
)


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return False


def _is_active_hit(hit: dict[str, Any]) -> bool:
    if not _truthy(hit.get("active", True)):
        return False
    correction = hit.get("correction") or {}
    return _truthy(correction.get("active", True))


def format_recall(result: dict[str, Any] | None) -> str:
    """Render a recall payload as system/user injection text."""
    payload = result or {}
    hits = [hit for hit in (payload.get("hits") or []) if isinstance(hit, dict) and _is_active_hit(hit)]
    if payload.get("abstain") or not hits:
        return ABSTAIN_MESSAGE

    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        correction = hit.get("correction") or {}
        error = hit.get("error") or {}
        text = str(correction.get("text") or "").strip()
        signature = str(error.get("signature") or "").strip()
        file_path = str(hit.get("file_path") or "").strip()
        symbol = str(hit.get("symbol") or "").strip()
        via = str(hit.get("via") or "file").strip() or "file"
        lines.append(f"{index}. {text}")
        lines.append(f"   signature: {signature}")
        location = f"   file: {file_path}" if file_path else "   file:"
        if symbol:
            location += f"  symbol: {symbol}"
        lines.append(location)
        lines.append(f"   via: {via}")
    return "\n".join(lines)
