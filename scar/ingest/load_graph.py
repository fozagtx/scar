"""Adapter from miner output to graph-core named upsert calls.

Pure data. This module must not import hydra, neo4j, or scar.graph —
agent-serve executes the returned ops after merge.
"""

from __future__ import annotations

from typing import Any

from scar.ingest.signatures import normalize_path


def to_upsert_calls(mine_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Translate a ``mine_session`` dict into ``{"op", "kwargs"}`` calls.

    Op names match ``scar.graph.queries`` from graph-core:
    ``upsert_file``, ``upsert_error``, ``link_same_signature``,
    ``link_led_to``, ``upsert_correction``, ``supersede_correction``.
    """
    result = mine_result or {}
    calls: list[dict[str, Any]] = []
    seen_files: set[str] = set()

    def _file_call(path: str | None) -> None:
        npath = normalize_path(path, None)
        if not npath or npath in seen_files:
            return
        seen_files.add(npath)
        calls.append(
            {
                "op": "upsert_file",
                "kwargs": {"id": f"file:{npath}", "path": npath},
            }
        )

    for err in result.get("errors") or []:
        _file_call(err.get("file_path"))
        calls.append(
            {
                "op": "upsert_error",
                "kwargs": {
                    "id": err.get("id"),
                    "signature": err.get("signature"),
                    "message": err.get("message"),
                    "tool": err.get("tool"),
                    "exit_code": err.get("exit_code"),
                    "session_id": err.get("session_id"),
                    "turn_id": err.get("turn_id"),
                    "file_path": err.get("file_path"),
                    "symbol": err.get("symbol"),
                },
            }
        )

    for link in result.get("error_links") or []:
        link_type = (link.get("type") or "").upper()
        kwargs = {"from_id": link.get("from_id"), "to_id": link.get("to_id")}
        if link_type == "SAME_AS":
            calls.append({"op": "link_same_signature", "kwargs": kwargs})
        elif link_type == "LED_TO":
            calls.append({"op": "link_led_to", "kwargs": kwargs})

    superseded_ids = {
        cor.get("supersedes_correction_id")
        for cor in (result.get("corrections") or [])
        if cor.get("supersedes_correction_id")
    }

    for cor in result.get("corrections") or []:
        calls.append(
            {
                "op": "upsert_correction",
                "kwargs": {
                    "id": cor.get("id"),
                    "kind": cor.get("kind"),
                    "text": cor.get("text"),
                    "created_at": cor.get("created_at"),
                    "active": cor.get("id") not in superseded_ids,
                    "fixes_error_id": cor.get("fixes_error_id"),
                    "stated_in_turn_id": cor.get("stated_in_turn_id"),
                },
            }
        )
        older = cor.get("supersedes_correction_id")
        if older:
            calls.append(
                {
                    "op": "supersede_correction",
                    "kwargs": {"older_id": older, "newer_id": cor.get("id")},
                }
            )

    return calls
