"""Named HydraDB operations. Other packages call these names; they do not inline Cypher."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

from scar.models import CorrectionKind, recall_result_dict

ABSTAIN_REASON = (
    "SCAR has no stored correction for this context. Do not invent a house rule."
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_STOP = frozenset(
    {
        "the",
        "an",
        "a",
        "in",
        "on",
        "of",
        "and",
        "or",
        "to",
        "for",
        "is",
        "has",
        "no",
        "with",
        "this",
        "that",
        "from",
        "into",
        "type",
        "object",
        "attribute",
    }
)


class QueryClient(Protocol):
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


SEED_VERTEX = 0


def vertex_id(label: str, key: str) -> int:
    """HydraDB OSS requires integer node ids. Business ids stay on ``key``."""
    digest = hashlib.sha1(f"{label}\0{key}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
    return value or 1


def _q(client: QueryClient, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return client.query(cypher, params or {})


def _ensure(client: QueryClient, label: str, key: str, **props: Any) -> int:
    nid = vertex_id(label, key)
    _q(
        client,
        f"MERGE (s:_Seed {{id: $seed}})-[:HAS]->(n:{label} {{id: $id}})",
        {"seed": SEED_VERTEX, "id": nid},
    )
    assignments = ["n.key = $key"]
    params: dict[str, Any] = {"id": nid, "key": key}
    for name, value in props.items():
        if value is None:
            continue
        assignments.append(f"n.{name} = ${name}")
        params[name] = value
    _q(
        client,
        f"MATCH (n:{label} {{id: $id}}) SET {', '.join(assignments)}",
        params,
    )
    return nid


def _link(client: QueryClient, from_label: str, to_label: str, rel: str, from_id: str, to_id: str) -> None:
    _ensure(client, from_label, from_id)
    _ensure(client, to_label, to_id)
    _q(
        client,
        f"MERGE (a:{from_label} {{id: $from_id}})-[:{rel}]->(b:{to_label} {{id: $to_id}})",
        {
            "from_id": vertex_id(from_label, from_id),
            "to_id": vertex_id(to_label, to_id),
        },
    )


def upsert_repo(client: QueryClient, *, id: str, root: str, language: str, **_: Any) -> str:
    _ensure(client, "Repo", id, root=root, language=language)
    return id


def upsert_file(
    client: QueryClient,
    *,
    id: str,
    path: str,
    language: str = "unknown",
    repo_id: str | None = None,
    **_: Any,
) -> str:
    _ensure(
        client,
        "File",
        id,
        path=path,
        language=language or "unknown",
        repo_id=repo_id,
    )
    if repo_id:
        _link(client, "File", "Repo", "IN_REPO", id, repo_id)
    return id


def upsert_symbol(
    client: QueryClient,
    *,
    id: str,
    qualified_name: str,
    kind: str = "unknown",
    file_id: str | None = None,
    **_: Any,
) -> str:
    _ensure(
        client,
        "Symbol",
        id,
        qualified_name=qualified_name,
        kind=kind or "unknown",
    )
    if file_id:
        _link(client, "Symbol", "File", "IN_FILE", id, file_id)
    return id


def upsert_session(
    client: QueryClient,
    *,
    id: str,
    source: str,
    started_at: str,
    repo_id: str | None = None,
    **_: Any,
) -> str:
    _ensure(
        client,
        "Session",
        id,
        source=source,
        started_at=started_at,
    )
    if repo_id:
        _link(client, "Session", "Repo", "IN_REPO", id, repo_id)
    return id


def upsert_turn(
    client: QueryClient,
    *,
    id: str,
    role: str,
    ts: str,
    text: str,
    session_id: str | None = None,
    file_id: str | None = None,
    symbol_id: str | None = None,
    **_: Any,
) -> str:
    _ensure(client, "Turn", id, role=role, ts=ts, text=text)
    if session_id:
        _link(client, "Session", "Turn", "HAS_TURN", session_id, id)
    if file_id:
        _link(client, "Turn", "File", "TOUCHED", id, file_id)
    if symbol_id:
        _link(client, "Turn", "Symbol", "MENTIONS", id, symbol_id)
    return id


def upsert_error(
    client: QueryClient,
    *,
    id: str,
    signature: str,
    message: str = "",
    tool: str | None = None,
    exit_code: int | None = None,
    file_id: str | None = None,
    symbol_id: str | None = None,
    turn_id: str | None = None,
    session_id: str | None = None,
    file_path: str | None = None,
    symbol: str | None = None,
    repo_id: str | None = None,
    **_: Any,
) -> str:
    if file_path and not file_id:
        file_id = f"file:{file_path}"
        upsert_file(client, id=file_id, path=file_path, repo_id=repo_id)
    if symbol and not symbol_id:
        symbol_id = f"sym:{symbol}"
        upsert_symbol(client, id=symbol_id, qualified_name=symbol, file_id=file_id)
    _ensure(
        client,
        "Error",
        id,
        signature=signature,
        message=message or "",
        tool=tool,
        exit_code=exit_code,
        repo_id=repo_id,
    )
    if file_id:
        _link(client, "Error", "File", "IN_FILE", id, file_id)
    if symbol_id:
        _link(client, "Error", "Symbol", "ON_SYMBOL", id, symbol_id)
    if turn_id:
        _link(client, "Turn", "Error", "EMITTED", turn_id, id)
    if session_id:
        _link(client, "Session", "Error", "EMITTED", session_id, id)
    return id


def link_same_signature(client: QueryClient, *, from_id: str, to_id: str, **_: Any) -> None:
    _link(client, "Error", "Error", "SAME_AS", from_id, to_id)


def upsert_correction(
    client: QueryClient,
    *,
    id: str,
    kind: str,
    text: str,
    created_at: str | None = None,
    active: bool = True,
    fixes_error_id: str | None = None,
    stated_in_turn_id: str | None = None,
    **_: Any,
) -> str:
    try:
        kind_value = CorrectionKind(kind).value
    except ValueError:
        kind_value = kind
    _ensure(
        client,
        "Correction",
        id,
        kind=kind_value,
        text=text,
        created_at=created_at or "",
        active=bool(active),
    )
    if fixes_error_id:
        _link(client, "Correction", "Error", "FIXES", id, fixes_error_id)
    if stated_in_turn_id:
        _link(client, "Correction", "Turn", "STATED_IN", id, stated_in_turn_id)
    return id


def supersede_correction(client: QueryClient, *, newer_id: str, older_id: str, **_: Any) -> None:
    _link(client, "Correction", "Correction", "SUPERSEDES", newer_id, older_id)
    _q(
        client,
        "MATCH (older:Correction {id: $id}) SET older.active = false",
        {"id": vertex_id("Correction", older_id)},
    )
    _q(
        client,
        "MATCH (newer:Correction {id: $id}) SET newer.active = true",
        {"id": vertex_id("Correction", newer_id)},
    )


def link_call(client: QueryClient, *, from_id: str, to_id: str, **_: Any) -> None:
    _link(client, "Symbol", "Symbol", "CALLS", from_id, to_id)


def link_import(client: QueryClient, *, from_id: str, to_id: str, **_: Any) -> None:
    _link(client, "File", "File", "IMPORTS", from_id, to_id)


def link_led_to(client: QueryClient, *, from_id: str, to_id: str, **_: Any) -> None:
    _link(client, "Error", "Error", "LED_TO", from_id, to_id)


def upsert_antipattern(client: QueryClient, *, id: str, name: str, description: str, **_: Any) -> str:
    _ensure(client, "AntiPattern", id, name=name, description=description)
    return id


def upsert_constraint(client: QueryClient, *, id: str, rule: str, active: bool = True, **_: Any) -> str:
    _ensure(client, "Constraint", id, rule=rule, active=bool(active))
    return id


def link_instance_of(client: QueryClient, *, error_id: str, antipattern_id: str, **_: Any) -> None:
    _link(client, "Error", "AntiPattern", "INSTANCE_OF", error_id, antipattern_id)


def link_forbidden_in(client: QueryClient, *, antipattern_id: str, repo_id: str, **_: Any) -> None:
    _link(client, "AntiPattern", "Repo", "FORBIDDEN_IN", antipattern_id, repo_id)


def _tokens(text: str | None) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def signature_matches(signature: str | None, error_text: str | None) -> bool:
    if not error_text or not str(error_text).strip() or not signature:
        return False
    if signature.lower() in error_text.lower():
        return True
    needles = _tokens(error_text) - _STOP
    hay = _tokens(signature)
    distinctive = {t for t in needles if t.endswith("error") or t.endswith("exception") or len(t) >= 4}
    return bool((distinctive or needles) & hay)


def _superseded_ids(client: QueryClient) -> set[str]:
    rows = _q(
        client,
        "MATCH (newer:Correction)-[:SUPERSEDES]->(older:Correction) "
        "RETURN newer.key AS newer_id, older.key AS older_id",
    )
    return {str(row["older_id"]) for row in rows if row.get("older_id") is not None}


def _file_rows(client: QueryClient, repo_id: str | None, path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    rows = _q(
        client,
        "MATCH (f:File {path: $path}) RETURN f.key AS id, f.path AS path, f.repo_id AS repo_id",
        {"path": path},
    )
    if repo_id:
        scoped = [row for row in rows if row.get("repo_id") in (repo_id, None)]
        return scoped or rows
    return rows


def _import_neighborhood(client: QueryClient, file_id: str) -> list[dict[str, Any]]:
    start = vertex_id("File", file_id)
    found: dict[str, dict[str, Any]] = {}
    frontier = {start}
    seen = {start}
    for _ in range(2):
        nxt: set[int] = set()
        for vid in frontier:
            rows = _q(
                client,
                "MATCH (origin:File {id: $id})-[:IMPORTS]->(n:File) "
                "RETURN n.key AS id, n.path AS path, n.id AS vid",
                {"id": vid},
            ) + _q(
                client,
                "MATCH (origin:File {id: $id})<-[:IMPORTS]-(n:File) "
                "RETURN n.key AS id, n.path AS path, n.id AS vid",
                {"id": vid},
            )
            for row in rows:
                key = str(row.get("id") or "")
                other = row.get("vid")
                if key:
                    found[key] = {"id": key, "path": row.get("path")}
                if isinstance(other, int) and other not in seen:
                    seen.add(other)
                    nxt.add(other)
        frontier = nxt
        if not frontier:
            break
    found.pop(file_id, None)
    return list(found.values())


def _call_neighborhood(client: QueryClient, qualified_name: str | None) -> list[dict[str, Any]]:
    if not qualified_name:
        return []
    direct = _q(
        client,
        "MATCH (s:Symbol {qualified_name: $qualified_name}) "
        "RETURN s.key AS id, s.qualified_name AS qualified_name",
        {"qualified_name": qualified_name},
    )
    hops = _q(
        client,
        "MATCH (s:Symbol {qualified_name: $qualified_name})-[:CALLS]->(t:Symbol) "
        "RETURN t.key AS id, t.qualified_name AS qualified_name",
        {"qualified_name": qualified_name},
    )
    return direct + hops


def _errors_in_file(client: QueryClient, file_id: str) -> list[dict[str, Any]]:
    return _q(
        client,
        "MATCH (e:Error)-[:IN_FILE]->(f:File {key: $file_id}) "
        "RETURN e.key AS id, e.signature AS signature, e.message AS message, "
        "e.tool AS tool, e.exit_code AS exit_code, e.repo_id AS repo_id, "
        "f.path AS file_path",
        {"file_id": file_id},
    )


def _errors_on_symbol(client: QueryClient, symbol_id: str) -> list[dict[str, Any]]:
    return _q(
        client,
        "MATCH (e:Error)-[:ON_SYMBOL]->(s:Symbol {key: $symbol_id}) "
        "RETURN e.key AS id, e.signature AS signature, e.message AS message, "
        "e.tool AS tool, e.exit_code AS exit_code, e.repo_id AS repo_id, "
        "s.qualified_name AS symbol",
        {"symbol_id": symbol_id},
    )


def _errors_by_repo(client: QueryClient, repo_id: str | None) -> list[dict[str, Any]]:
    if repo_id:
        rows = _q(
            client,
            "MATCH (e:Error {repo_id: $repo_id}) "
            "RETURN e.key AS id, e.signature AS signature, e.message AS message, "
            "e.tool AS tool, e.exit_code AS exit_code, e.repo_id AS repo_id",
            {"repo_id": repo_id},
        )
        if rows:
            return rows
    return _q(
        client,
        "MATCH (e:Error) "
        "RETURN e.key AS id, e.signature AS signature, e.message AS message, "
        "e.tool AS tool, e.exit_code AS exit_code, e.repo_id AS repo_id",
    )


def _error_file_path(client: QueryClient, error_id: str) -> str | None:
    rows = _q(
        client,
        "MATCH (e:Error {key: $id})-[:IN_FILE]->(f:File) RETURN f.path AS path",
        {"id": error_id},
    )
    if rows and rows[0].get("path"):
        return str(rows[0]["path"])
    return None


def _error_symbol(client: QueryClient, error_id: str) -> str | None:
    rows = _q(
        client,
        "MATCH (e:Error {key: $id})-[:ON_SYMBOL]->(s:Symbol) RETURN s.qualified_name AS qualified_name",
        {"id": error_id},
    )
    if rows and rows[0].get("qualified_name"):
        return str(rows[0]["qualified_name"])
    return None


def _corrections_for_error(client: QueryClient, error_id: str) -> list[dict[str, Any]]:
    return _q(
        client,
        "MATCH (c:Correction)-[:FIXES]->(e:Error {key: $error_id}) "
        "RETURN c.key AS id, c.kind AS kind, c.text AS text, "
        "c.created_at AS created_at, c.active AS active",
        {"error_id": error_id},
    )


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return False


def select_active_corrections(
    corrections: list[dict[str, Any]],
    superseded: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in corrections:
        cid = str(row.get("id") or "")
        if not cid or cid in superseded:
            continue
        if not _truthy(row.get("active", True)):
            continue
        selected.append(row)
    return selected


def recall_for_context(
    client: QueryClient,
    repo_id: str,
    file_path: str,
    symbol: str | None = None,
    error_text: str | None = None,
    task_text: str | None = None,
) -> dict[str, Any]:
    """Return active, non-superseded scars. Abstain rather than invent."""
    del task_text  # ranking hint only; never used to invent a scar
    matched: dict[str, dict[str, Any]] = {}

    def note_error(row: dict[str, Any], via: str) -> None:
        error_id = str(row.get("id") or "")
        if not error_id:
            return
        if repo_id and row.get("repo_id") not in (repo_id, None):
            return
        current = matched.get(error_id)
        if current is None:
            payload = dict(row)
            payload["via"] = via
            matched[error_id] = payload
            return
        # Prefer a more specific via when we already have a neighborhood hit.
        priority = {"signature": 3, "CALLS": 2, "IMPORTS": 1, "file": 0}
        if priority.get(via, 0) > priority.get(str(current.get("via")), 0):
            current["via"] = via

    current_files = _file_rows(client, repo_id, file_path)
    file_ids = {str(row["id"]) for row in current_files if row.get("id")}
    for file_id in list(file_ids):
        for row in _errors_in_file(client, file_id):
            note_error(row, "file")
        for neighbor in _import_neighborhood(client, file_id):
            nid = str(neighbor.get("id") or "")
            if not nid or nid in file_ids:
                continue
            file_ids.add(nid)
            for row in _errors_in_file(client, nid):
                note_error(row, "IMPORTS")

    for symbol_row in _call_neighborhood(client, symbol):
        sid = str(symbol_row.get("id") or "")
        if not sid:
            continue
        for row in _errors_on_symbol(client, sid):
            via = "CALLS"
            if symbol_row.get("qualified_name") == symbol:
                via = "file" if any(r.get("id") == row.get("id") for r in matched.values()) else "CALLS"
                if not matched.get(str(row.get("id"))):
                    via = "signature" if signature_matches(str(row.get("signature") or ""), error_text) else "CALLS"
            note_error(row, via)

    if error_text:
        for row in _errors_by_repo(client, repo_id):
            if signature_matches(str(row.get("signature") or ""), error_text):
                note_error(row, "signature")

    superseded = _superseded_ids(client)
    hits: list[dict[str, Any]] = []
    for error in matched.values():
        error_id = str(error["id"])
        file_for_error = error.get("file_path") or _error_file_path(client, error_id)
        symbol_for_error = error.get("symbol") or _error_symbol(client, error_id)
        for correction in select_active_corrections(_corrections_for_error(client, error_id), superseded):
            hits.append(
                {
                    "correction": {
                        "id": correction.get("id"),
                        "kind": correction.get("kind"),
                        "text": correction.get("text"),
                        "created_at": correction.get("created_at") or "",
                        "active": True,
                    },
                    "error": {
                        "id": error.get("id"),
                        "signature": error.get("signature"),
                        "message": error.get("message") or "",
                        "tool": error.get("tool"),
                        "exit_code": error.get("exit_code"),
                    },
                    "file_path": file_for_error,
                    "symbol": symbol_for_error,
                    "via": error.get("via") or "file",
                    "active": True,
                }
            )

    hits.sort(key=lambda h: str(h["correction"].get("created_at") or ""), reverse=True)
    if not hits:
        return recall_result_dict([], abstain=True, reason=ABSTAIN_REASON)
    return recall_result_dict(hits, abstain=False, reason="")


def blast_radius(client: QueryClient, error_id: str) -> dict[str, Any]:
    """Files that IMPORTS* a file which emitted the same error signature."""
    sig_rows = _q(
        client,
        "MATCH (e:Error {key: $error_id}) RETURN e.signature AS signature",
        {"error_id": error_id},
    )
    if not sig_rows or not sig_rows[0].get("signature"):
        return {"error_id": error_id, "signature": None, "origin_files": [], "files": []}
    signature = str(sig_rows[0]["signature"])
    origins = _q(
        client,
        "MATCH (same:Error {signature: $signature})-[:IN_FILE]->(origin:File) "
        "RETURN origin.key AS key, origin.path AS path, origin.id AS vid",
        {"signature": signature},
    )
    origin_paths = [str(row["path"]) for row in origins if row.get("path")]
    importer_paths: list[str] = []
    for origin in origins:
        vid = origin.get("vid")
        if not isinstance(vid, int):
            continue
        frontier = {vid}
        seen = {vid}
        for _ in range(8):
            nxt: set[int] = set()
            for current in frontier:
                rows = _q(
                    client,
                    "MATCH (origin:File {id: $id})<-[:IMPORTS]-(importer:File) "
                    "RETURN importer.path AS path, importer.id AS vid",
                    {"id": current},
                )
                for row in rows:
                    path = row.get("path")
                    other = row.get("vid")
                    if path:
                        importer_paths.append(str(path))
                    if isinstance(other, int) and other not in seen:
                        seen.add(other)
                        nxt.add(other)
            frontier = nxt
            if not frontier:
                break
    files: list[str] = []
    seen: set[str] = set()
    for path in origin_paths + importer_paths:
        if path not in seen:
            seen.add(path)
            files.append(path)
    return {
        "error_id": error_id,
        "signature": signature,
        "origin_files": origin_paths,
        "files": files,
    }


_EXPORT_RELS: tuple[tuple[str, str, str], ...] = (
    ("File", "IMPORTS", "File"),
    ("File", "IN_REPO", "Repo"),
    ("Symbol", "CALLS", "Symbol"),
    ("Symbol", "IN_FILE", "File"),
    ("Error", "IN_FILE", "File"),
    ("Error", "ON_SYMBOL", "Symbol"),
    ("Error", "LED_TO", "Error"),
    ("Error", "SAME_AS", "Error"),
    ("Error", "INSTANCE_OF", "AntiPattern"),
    ("Correction", "FIXES", "Error"),
    ("Correction", "SUPERSEDES", "Correction"),
    ("Correction", "STATED_IN", "Turn"),
    ("Session", "HAS_TURN", "Turn"),
    ("Session", "IN_REPO", "Repo"),
    ("Turn", "TOUCHED", "File"),
    ("Turn", "EMITTED", "Error"),
    ("AntiPattern", "FORBIDDEN_IN", "Repo"),
)


def _rows_as_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {key: value for key, value in row.items() if value is not None}
        if item.get("id"):
            out.append(item)
    return out


def _pick_primary_repo(
    repos: list[dict[str, Any]], files: list[dict[str, Any]]
) -> dict[str, Any]:
    """Choose the demo masthead repo. Live pytest leaves test-repo-* vertices."""
    empty = {"id": "", "root": "", "language": ""}
    if not repos:
        return empty
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in repos:
        rid = str(row.get("id") or "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        unique.append(row)
    by_id = {str(row["id"]): row for row in unique}
    if "scar" in by_id:
        return by_id["scar"]
    file_counts: dict[str, int] = {}
    for row in files:
        rid = str(row.get("repo_id") or "")
        if rid:
            file_counts[rid] = file_counts.get(rid, 0) + 1
    product = [row for row in unique if not str(row.get("id")).startswith("test-repo-")]
    pool = product or unique
    if file_counts:
        best = max(pool, key=lambda row: file_counts.get(str(row.get("id")), 0))
        return best
    return pool[0]


def export_graph(client: QueryClient) -> dict[str, Any]:
    """Dump the live HydraDB neighborhood for the demo UI. Empty store is valid."""
    repos = _rows_as_dicts(
        _q(client, "MATCH (n:Repo) RETURN n.key AS id, n.root AS root, n.language AS language")
    )
    files = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:File) RETURN n.key AS id, n.path AS path, n.language AS language, n.repo_id AS repo_id",
        )
    )
    symbols = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:Symbol) RETURN n.key AS id, n.qualified_name AS qualified_name, n.kind AS kind",
        )
    )
    sessions = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:Session) RETURN n.key AS id, n.source AS source, n.started_at AS started_at",
        )
    )
    turns = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:Turn) RETURN n.key AS id, n.role AS role, n.ts AS ts, n.text AS text",
        )
    )
    errors = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:Error) RETURN n.key AS id, n.signature AS signature, n.message AS message, "
            "n.tool AS tool, n.exit_code AS exit_code, n.repo_id AS repo_id",
        )
    )
    corrections = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:Correction) RETURN n.key AS id, n.kind AS kind, n.text AS text, "
            "n.created_at AS created_at, n.active AS active",
        )
    )
    antipatterns = _rows_as_dicts(
        _q(
            client,
            "MATCH (n:AntiPattern) RETURN n.key AS id, n.name AS name, n.description AS description",
        )
    )
    relationships: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for from_label, rel, to_label in _EXPORT_RELS:
        rows = _q(
            client,
            f"MATCH (a:{from_label})-[:{rel}]->(b:{to_label}) "
            "RETURN a.key AS src, b.key AS dst",
        )
        for row in rows:
            src, dst = row.get("src"), row.get("dst")
            if not src or not dst:
                continue
            key = (rel, str(src), str(dst))
            if key in seen:
                continue
            seen.add(key)
            relationships.append({"type": rel, "from": str(src), "to": str(dst)})

    errors_by_id = {str(row["id"]): row for row in errors}
    symbols_by_id = {str(row["id"]): row for row in symbols}
    sessions_by_id = {str(row["id"]): row for row in sessions}
    turns_by_id = {str(row["id"]): row for row in turns}
    for rel in relationships:
        src, dst, kind = rel["from"], rel["to"], rel["type"]
        if kind == "IN_FILE" and src in errors_by_id:
            errors_by_id[src]["file_id"] = dst
        if kind == "ON_SYMBOL" and src in errors_by_id:
            errors_by_id[src]["symbol_id"] = dst
        if kind == "IN_FILE" and src in symbols_by_id:
            symbols_by_id[src]["file_id"] = dst
        if kind == "IN_REPO" and src in sessions_by_id:
            sessions_by_id[src]["repo_id"] = dst
        if kind == "TOUCHED" and src in turns_by_id:
            turns_by_id[src]["file_id"] = dst
        if kind == "FIXES":
            for row in corrections:
                if row.get("id") == src:
                    row["fixes_error_id"] = dst
        if kind == "SUPERSEDES":
            for row in corrections:
                if row.get("id") == src:
                    row["supersedes_correction_id"] = dst

    repo = _pick_primary_repo(repos, files)
    return {
        "repo": repo,
        "repos": repos,
        "files": files,
        "symbols": symbols,
        "sessions": sessions,
        "turns": turns,
        "errors": errors,
        "corrections": corrections,
        "antipatterns": antipatterns,
        "relationships": relationships,
    }
