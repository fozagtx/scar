"""Agent-facing SCAR operations: recall, record, ingest, blast radius."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scar.serve.prompt import ABSTAIN_MESSAGE, format_recall

__all__ = [
    "ABSTAIN_MESSAGE",
    "blast",
    "connect_client",
    "execute_upsert_ops",
    "format_recall",
    "ingest_jsonl",
    "recall_context",
    "record_correction",
]

_EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
}


def connect_client():
    """Build a GraphClient from the environment. Clear error if graph-core is missing."""
    try:
        from scar.graph.client import GraphClient
    except ImportError as exc:
        raise RuntimeError(
            "SCAR graph client is missing. Install/merge graph-core (scar.graph.client)."
        ) from exc
    return GraphClient.from_env()


def _language_for(path: str) -> str:
    return _EXT_LANG.get(Path(path).suffix.lower(), "unknown")


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def execute_upsert_ops(
    client: Any,
    ops: list[dict[str, Any]],
    repo_id: str | None = None,
) -> int:
    """Run miner adapter ops via ``getattr(queries, op)(client, **kwargs)``."""
    try:
        from scar.graph import queries
    except ImportError as exc:
        raise RuntimeError(
            "SCAR graph queries are missing. Install/merge graph-core (scar.graph.queries)."
        ) from exc

    if repo_id:
        getattr(queries, "upsert_repo")(
            client, id=repo_id, root=repo_id, language="unknown"
        )

    executed = 0
    for call in ops:
        op = call.get("op")
        if not op:
            continue
        fn = getattr(queries, op, None)
        if fn is None:
            raise RuntimeError(f"Unknown graph op {op!r}; is graph-core installed?")
        kwargs = dict(call.get("kwargs") or {})
        if repo_id and op in {"upsert_file", "upsert_error"} and not kwargs.get("repo_id"):
            kwargs["repo_id"] = repo_id
        fn(client, **kwargs)
        executed += 1
    return executed


def ingest_jsonl(client: Any, path: str | Path, repo_id: str) -> int:
    """Mine a JSONL/JSON transcript file and upsert the resulting ops."""
    try:
        from scar.ingest.load_graph import to_upsert_calls
        from scar.ingest.mine import mine_jsonl
    except ImportError as exc:
        raise RuntimeError(
            "SCAR miner is missing. Install/merge correction-miner "
            "(scar.ingest.mine / scar.ingest.load_graph)."
        ) from exc

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"JSONL not found: {target}")

    total = 0
    for result in mine_jsonl(target):
        total += execute_upsert_ops(client, to_upsert_calls(result), repo_id=repo_id)
    return total


def recall_context(
    client: Any,
    repo_id: str,
    file_path: str,
    symbol: str | None = None,
    error_text: str | None = None,
    task_text: str | None = None,
) -> dict[str, Any]:
    try:
        from scar.graph import queries
    except ImportError as exc:
        raise RuntimeError(
            "SCAR graph queries are missing. Install/merge graph-core (scar.graph.queries)."
        ) from exc
    return queries.recall_for_context(
        client,
        repo_id,
        file_path,
        symbol=symbol,
        error_text=error_text,
        task_text=task_text,
    )


def record_correction(
    client: Any,
    repo_id: str,
    file_path: str,
    correction_text: str,
    error_text: str | None = None,
) -> dict[str, Any]:
    """Write a ``human_instruction`` correction captured from a live session."""
    try:
        from scar.graph import queries
    except ImportError as exc:
        raise RuntimeError(
            "SCAR graph queries are missing. Install/merge graph-core (scar.graph.queries)."
        ) from exc

    language = _language_for(file_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    getattr(queries, "upsert_repo")(
        client, id=repo_id, root=repo_id, language=language
    )
    file_id = f"file:{file_path}"
    getattr(queries, "upsert_file")(
        client,
        id=file_id,
        path=file_path,
        language=language,
        repo_id=repo_id,
    )

    try:
        from scar.ingest.signatures import error_signature

        signature = error_signature(error_text or correction_text, file_path, language)
    except ImportError:
        signature = error_text or f"manual|{file_path}"

    error_id = _stable_id("err", repo_id, file_path, error_text or "manual")
    getattr(queries, "upsert_error")(
        client,
        id=error_id,
        signature=signature,
        message=error_text or "",
        file_path=file_path,
        repo_id=repo_id,
    )
    correction_id = _stable_id("cor", repo_id, file_path, correction_text)
    getattr(queries, "upsert_correction")(
        client,
        id=correction_id,
        kind="human_instruction",
        text=correction_text,
        created_at=now,
        active=True,
        fixes_error_id=error_id,
    )
    return {
        "ok": True,
        "correction_id": correction_id,
        "error_id": error_id,
        "kind": "human_instruction",
    }


def blast(
    client: Any,
    error_id: str | None = None,
    signature: str | None = None,
) -> dict[str, Any]:
    try:
        from scar.graph import queries
    except ImportError as exc:
        raise RuntimeError(
            "SCAR graph queries are missing. Install/merge graph-core (scar.graph.queries)."
        ) from exc
    key = error_id or signature
    if not key:
        return {"error_id": None, "signature": signature, "origin_files": [], "files": []}
    result = queries.blast_radius(client, key)
    if result.get("signature") is None and signature:
        return {**result, "signature": signature}
    return result
