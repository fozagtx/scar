"""HydraDB schema helpers. Nodes are uniquely keyed by ``id`` via MERGE."""

from __future__ import annotations

from typing import Any

CONSTRAINT_STATEMENTS = (
    "CREATE CONSTRAINT FOR (n:Repo) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:File) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Symbol) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Session) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Turn) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Error) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Correction) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:AntiPattern) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT FOR (n:Constraint) REQUIRE n.id IS UNIQUE",
)

MERGE_KEY_CONVENTION = (
    "Every SCAR node is MERGEd on the property `id`. HydraDB OSS OpenCypher "
    "may not accept Neo4j uniqueness constraints; if CREATE CONSTRAINT fails, "
    "callers still upsert by id and must not mint duplicate ids."
)


def apply_schema(client: Any) -> dict[str, Any]:
    """Best-effort uniqueness constraints. Always safe to skip on OpenCypher gaps."""
    applied: list[str] = []
    errors: list[str] = []
    for statement in CONSTRAINT_STATEMENTS:
        try:
            client.query(statement, {})
            applied.append(statement)
        except Exception as exc:  # Hydra subset often rejects CONSTRAINT
            errors.append(f"{statement}: {exc}")
            break
    return {
        "constraints": bool(applied) and not errors,
        "applied": applied,
        "errors": errors,
        "convention": MERGE_KEY_CONVENTION,
    }
