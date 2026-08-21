#!/usr/bin/env python3
"""Load fixtures/demo_graph.json into HydraDB OSS through named graph operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scar.graph.client import GraphClient
from scar.graph.queries import (
    link_call,
    link_forbidden_in,
    link_import,
    link_instance_of,
    link_led_to,
    link_same_signature,
    upsert_antipattern,
    upsert_constraint,
    upsert_correction,
    upsert_error,
    upsert_file,
    upsert_repo,
    upsert_session,
    upsert_symbol,
    upsert_turn,
    supersede_correction,
)
from scar.graph.schema import apply_schema


def fixture_path() -> Path:
    return ROOT / "fixtures" / "demo_graph.json"


def seed_graph(client: Any, payload: dict[str, Any]) -> None:
    repo = payload["repo"]
    upsert_repo(
        client,
        id=repo["id"],
        root=repo["root"],
        language=repo["language"],
    )
    files = {item["id"]: item for item in payload.get("files") or []}
    for item in files.values():
        upsert_file(
            client,
            id=item["id"],
            path=item["path"],
            language=item.get("language") or repo.get("language") or "unknown",
            repo_id=repo["id"],
        )
    for item in payload.get("symbols") or []:
        upsert_symbol(
            client,
            id=item["id"],
            qualified_name=item["qualified_name"],
            kind=item.get("kind") or "unknown",
            file_id=item.get("file_id"),
        )
    for item in payload.get("sessions") or []:
        upsert_session(
            client,
            id=item["id"],
            source=item["source"],
            started_at=item["started_at"],
            repo_id=item.get("repo_id") or repo["id"],
        )
    for item in payload.get("turns") or []:
        upsert_turn(
            client,
            id=item["id"],
            role=item["role"],
            ts=item["ts"],
            text=item.get("text") or "",
            session_id=item.get("session_id"),
            file_id=item.get("file_id"),
            symbol_id=item.get("symbol_id"),
        )
    for item in payload.get("errors") or []:
        upsert_error(
            client,
            id=item["id"],
            signature=item["signature"],
            message=item.get("message") or "",
            tool=item.get("tool"),
            exit_code=item.get("exit_code"),
            file_id=item.get("file_id"),
            symbol_id=item.get("symbol_id"),
            turn_id=item.get("turn_id"),
            repo_id=item.get("repo_id") or repo["id"],
        )
    for item in payload.get("corrections") or []:
        upsert_correction(
            client,
            id=item["id"],
            kind=item["kind"],
            text=item["text"],
            created_at=item.get("created_at"),
            active=item.get("active", True),
            fixes_error_id=item.get("fixes_error_id"),
            stated_in_turn_id=item.get("stated_in_turn_id"),
        )
        older = item.get("supersedes_correction_id")
        if older:
            supersede_correction(client, newer_id=item["id"], older_id=older)
    for item in payload.get("antipatterns") or []:
        upsert_antipattern(
            client,
            id=item["id"],
            name=item["name"],
            description=item.get("description") or "",
        )
        link_forbidden_in(client, antipattern_id=item["id"], repo_id=repo["id"])
        for error_id in item.get("error_ids") or []:
            link_instance_of(client, error_id=error_id, antipattern_id=item["id"])
        constraint = item.get("constraint") or {}
        if constraint.get("id"):
            upsert_constraint(
                client,
                id=constraint["id"],
                rule=constraint.get("rule") or "",
                active=constraint.get("active", True),
            )
    rel_handlers = {
        "CALLS": lambda rel: link_call(client, from_id=rel["from"], to_id=rel["to"]),
        "IMPORTS": lambda rel: link_import(client, from_id=rel["from"], to_id=rel["to"]),
        "SAME_AS": lambda rel: link_same_signature(client, from_id=rel["from"], to_id=rel["to"]),
        "LED_TO": lambda rel: link_led_to(client, from_id=rel["from"], to_id=rel["to"]),
        "SUPERSEDES": lambda rel: supersede_correction(
            client, newer_id=rel["from"], older_id=rel["to"]
        ),
    }
    for rel in payload.get("relationships") or []:
        handler = rel_handlers.get(str(rel.get("type") or "").upper())
        if handler:
            handler(rel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=fixture_path(),
        help="Path to demo_graph.json",
    )
    args = parser.parse_args()
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    with GraphClient.from_env() as client:
        apply_schema(client)
        seed_graph(client, payload)
    print(f"seeded {args.fixture} into HydraDB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
