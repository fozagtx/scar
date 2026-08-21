#!/usr/bin/env python3
"""Local SCAR demo server: static UI + fixture (or live) recall.

    python scripts/demo_api.py

Binds 127.0.0.1:7331 (override with SCAR_DEMO_HOST / SCAR_DEMO_PORT).

    GET  /              ui/index.html
    GET  /fixture       fixtures/demo_graph.json
    GET  /layout        fixtures/demo_ui_layout.json (404 if absent)
    GET  /health        {"ok": true, "mode": "fixture"|"live"}
    POST /v1/recall     {hits, abstain, reason}  — same shape as graph-core
    POST /v1/blast      {error_id, signature, origin_files, files}

Fixture mode is the default. Set SCAR_LIVE=1 to try scar.graph.recall_for_context
against HydraDB; any import/query failure falls back to the fixture.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI_DIR = ROOT / "ui"
FIXTURE_PATH = ROOT / "fixtures" / "demo_graph.json"
LAYOUT_PATH = ROOT / "fixtures" / "demo_ui_layout.json"

HOST = os.environ.get("SCAR_DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("SCAR_DEMO_PORT", "7331"))

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

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_FIXTURE_CACHE: dict[str, Any] | None = None
_FIXTURE_LOCK = threading.Lock()


def live_requested() -> bool:
    return os.environ.get("SCAR_LIVE", "").strip() in {"1", "true", "TRUE", "yes"}


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    global _FIXTURE_CACHE
    target = path or FIXTURE_PATH
    if path is None:
        with _FIXTURE_LOCK:
            if _FIXTURE_CACHE is None:
                _FIXTURE_CACHE = json.loads(target.read_text(encoding="utf-8"))
            return _FIXTURE_CACHE
    return json.loads(target.read_text(encoding="utf-8"))


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return False


def _tokens(text: str | None) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def signature_matches(signature: str | None, error_text: str | None) -> bool:
    try:
        from scar.graph.queries import signature_matches as live_match

        return bool(live_match(signature, error_text))
    except Exception:
        pass
    if not error_text or not str(error_text).strip() or not signature:
        return False
    if signature.lower() in error_text.lower():
        return True
    needles = _tokens(error_text) - _STOP
    hay = _tokens(signature)
    distinctive = {t for t in needles if t.endswith("error") or t.endswith("exception") or len(t) >= 4}
    return bool((distinctive or needles) & hay)


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


def _rels(graph: dict[str, Any], rel_type: str) -> list[dict[str, Any]]:
    wanted = rel_type.upper()
    out: list[dict[str, Any]] = []
    for rel in graph.get("relationships") or []:
        if str(rel.get("type") or "").upper() == wanted:
            out.append(rel)
    return out


def _file_by_path(graph: dict[str, Any], path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    for row in graph.get("files") or []:
        if row.get("path") == path:
            return row
    return None


def _file_by_id(graph: dict[str, Any], file_id: str | None) -> dict[str, Any] | None:
    if not file_id:
        return None
    for row in graph.get("files") or []:
        if row.get("id") == file_id:
            return row
    return None


def _symbol_by_qn(graph: dict[str, Any], qualified_name: str | None) -> dict[str, Any] | None:
    if not qualified_name:
        return None
    for row in graph.get("symbols") or []:
        if row.get("qualified_name") == qualified_name:
            return row
    return None


def _symbol_by_id(graph: dict[str, Any], symbol_id: str | None) -> dict[str, Any] | None:
    if not symbol_id:
        return None
    for row in graph.get("symbols") or []:
        if row.get("id") == symbol_id:
            return row
    return None


def _undirected_neighborhood(
    edges: list[tuple[str, str]],
    start: str,
    hops: int,
) -> set[str]:
    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen = {start}
    frontier = {start}
    for _ in range(hops):
        nxt: set[str] = set()
        for node in frontier:
            for nb in adj.get(node, ()):
                if nb not in seen:
                    seen.add(nb)
                    nxt.add(nb)
        frontier = nxt
        if not frontier:
            break
    seen.discard(start)
    return seen


def _import_neighborhood(graph: dict[str, Any], file_id: str) -> list[dict[str, Any]]:
    edges = [(str(r["from"]), str(r["to"])) for r in _rels(graph, "IMPORTS") if r.get("from") and r.get("to")]
    neighbor_ids = _undirected_neighborhood(edges, file_id, hops=2)
    files = {str(row["id"]): row for row in graph.get("files") or [] if row.get("id")}
    return [files[nid] for nid in neighbor_ids if nid in files]


def _call_neighborhood(graph: dict[str, Any], qualified_name: str | None) -> list[dict[str, Any]]:
    if not qualified_name:
        return []
    direct = _symbol_by_qn(graph, qualified_name)
    edges = [(str(r["from"]), str(r["to"])) for r in _rels(graph, "CALLS") if r.get("from") and r.get("to")]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if direct and direct.get("id"):
        out.append(direct)
        seen.add(str(direct["id"]))
        for nid in _undirected_neighborhood(edges, str(direct["id"]), hops=2):
            if nid in seen:
                continue
            row = _symbol_by_id(graph, nid)
            if row:
                seen.add(nid)
                out.append(row)
    return out


def _error_file_id(graph: dict[str, Any], error: dict[str, Any]) -> str | None:
    if error.get("file_id"):
        return str(error["file_id"])
    eid = error.get("id")
    for rel in _rels(graph, "IN_FILE"):
        if rel.get("from") == eid:
            return str(rel.get("to") or "") or None
    return None


def _error_symbol_id(graph: dict[str, Any], error: dict[str, Any]) -> str | None:
    if error.get("symbol_id"):
        return str(error["symbol_id"])
    eid = error.get("id")
    for rel in _rels(graph, "ON_SYMBOL"):
        if rel.get("from") == eid:
            return str(rel.get("to") or "") or None
    return None


def _errors_in_file(graph: dict[str, Any], file_id: str) -> list[dict[str, Any]]:
    linked: set[str] = set()
    for rel in _rels(graph, "IN_FILE"):
        if rel.get("to") == file_id and rel.get("from"):
            linked.add(str(rel["from"]))
    rows: list[dict[str, Any]] = []
    for error in graph.get("errors") or []:
        eid = str(error.get("id") or "")
        if eid in linked or error.get("file_id") == file_id:
            rows.append(error)
    return rows


def _errors_on_symbol(graph: dict[str, Any], symbol_id: str) -> list[dict[str, Any]]:
    linked: set[str] = set()
    for rel in _rels(graph, "ON_SYMBOL"):
        if rel.get("to") == symbol_id and rel.get("from"):
            linked.add(str(rel["from"]))
    rows: list[dict[str, Any]] = []
    for error in graph.get("errors") or []:
        eid = str(error.get("id") or "")
        if eid in linked or error.get("symbol_id") == symbol_id:
            rows.append(error)
    return rows


def _superseded_ids(graph: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for rel in _rels(graph, "SUPERSEDES"):
        older = rel.get("to")
        if older:
            ids.add(str(older))
    for row in graph.get("corrections") or []:
        older = row.get("supersedes_correction_id")
        if older:
            ids.add(str(older))
    return ids


def _corrections_for_error(graph: dict[str, Any], error_id: str) -> list[dict[str, Any]]:
    linked: set[str] = set()
    for rel in _rels(graph, "FIXES"):
        if rel.get("to") == error_id and rel.get("from"):
            linked.add(str(rel["from"]))
    rows: list[dict[str, Any]] = []
    for row in graph.get("corrections") or []:
        cid = str(row.get("id") or "")
        if cid in linked or row.get("fixes_error_id") == error_id:
            rows.append(row)
    return rows


def _error_file_path(graph: dict[str, Any], error: dict[str, Any]) -> str | None:
    file_row = _file_by_id(graph, _error_file_id(graph, error))
    return str(file_row["path"]) if file_row and file_row.get("path") else None


def _error_symbol_name(graph: dict[str, Any], error: dict[str, Any]) -> str | None:
    symbol = _symbol_by_id(graph, _error_symbol_id(graph, error))
    return str(symbol["qualified_name"]) if symbol and symbol.get("qualified_name") else None


def fixture_recall(
    graph: dict[str, Any],
    repo_id: str,
    file_path: str,
    symbol: str | None = None,
    error_text: str | None = None,
    task_text: str | None = None,
) -> dict[str, Any]:
    """Mirror scar.graph.queries.recall_for_context against demo_graph.json."""
    del task_text
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
        priority = {"signature": 3, "CALLS": 2, "IMPORTS": 1, "file": 0}
        if priority.get(via, 0) > priority.get(str(current.get("via")), 0):
            current["via"] = via

    current_file = _file_by_path(graph, file_path)
    file_ids: set[str] = set()
    if current_file and current_file.get("id"):
        file_ids.add(str(current_file["id"]))
    for file_id in list(file_ids):
        for row in _errors_in_file(graph, file_id):
            note_error(row, "file")
        for neighbor in _import_neighborhood(graph, file_id):
            nid = str(neighbor.get("id") or "")
            if not nid or nid in file_ids:
                continue
            file_ids.add(nid)
            for row in _errors_in_file(graph, nid):
                note_error(row, "IMPORTS")

    for symbol_row in _call_neighborhood(graph, symbol):
        sid = str(symbol_row.get("id") or "")
        if not sid:
            continue
        for row in _errors_on_symbol(graph, sid):
            via = "CALLS"
            if symbol_row.get("qualified_name") == symbol:
                if not matched.get(str(row.get("id"))):
                    via = "signature" if signature_matches(str(row.get("signature") or ""), error_text) else "CALLS"
            note_error(row, via)

    if error_text:
        for row in graph.get("errors") or []:
            if repo_id and row.get("repo_id") not in (repo_id, None):
                continue
            if signature_matches(str(row.get("signature") or ""), error_text):
                note_error(row, "signature")

    superseded = _superseded_ids(graph)
    hits: list[dict[str, Any]] = []
    for error in matched.values():
        error_id = str(error["id"])
        for correction in select_active_corrections(_corrections_for_error(graph, error_id), superseded):
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
                    "file_path": _error_file_path(graph, error),
                    "symbol": _error_symbol_name(graph, error),
                    "via": error.get("via") or "file",
                    "active": True,
                }
            )

    hits.sort(key=lambda h: str(h["correction"].get("created_at") or ""), reverse=True)
    if not hits:
        return {"hits": [], "abstain": True, "reason": ABSTAIN_REASON}
    return {"hits": hits, "abstain": False, "reason": ""}


def fixture_blast(graph: dict[str, Any], error_id: str) -> dict[str, Any]:
    """Mirror scar.graph.queries.blast_radius: IMPORTS* of same-signature origins."""
    errors = {str(row.get("id") or ""): row for row in graph.get("errors") or []}
    origin = errors.get(error_id)
    if origin is None or not origin.get("signature"):
        return {"error_id": error_id, "signature": None, "origin_files": [], "files": []}
    signature = str(origin["signature"])
    origin_ids: list[str] = []
    origin_paths: list[str] = []
    seen_origin: set[str] = set()
    for row in errors.values():
        if str(row.get("signature") or "") != signature:
            continue
        fid = _error_file_id(graph, row)
        if not fid or fid in seen_origin:
            continue
        seen_origin.add(fid)
        origin_ids.append(fid)
        file_row = _file_by_id(graph, fid)
        if file_row and file_row.get("path"):
            origin_paths.append(str(file_row["path"]))

    import_edges = [(str(r["from"]), str(r["to"])) for r in _rels(graph, "IMPORTS") if r.get("from") and r.get("to")]
    children: dict[str, set[str]] = {}
    for src, dst in import_edges:
        children.setdefault(dst, set()).add(src)

    importer_paths: list[str] = []
    for origin_id in origin_ids:
        stack = [(origin_id, 0)]
        visited = {origin_id}
        while stack:
            node, depth = stack.pop()
            if depth >= 8:
                continue
            for importer in children.get(node, ()):
                if importer in visited:
                    continue
                visited.add(importer)
                stack.append((importer, depth + 1))
                file_row = _file_by_id(graph, importer)
                if file_row and file_row.get("path"):
                    importer_paths.append(str(file_row["path"]))

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


def _parse_recall_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_id": str(payload.get("repo_id") or payload.get("repo") or "demo-repo"),
        "file_path": str(payload.get("file_path") or payload.get("file") or ""),
        "symbol": payload.get("symbol") or None,
        "error_text": payload.get("error_text") or payload.get("error") or None,
        "task_text": payload.get("task_text") or payload.get("task") or None,
    }


def _parse_blast_body(payload: dict[str, Any]) -> str:
    return str(payload.get("error_id") or payload.get("id") or "")


def try_live_recall(body: dict[str, Any]) -> dict[str, Any] | None:
    if not live_requested():
        return None
    try:
        from scar.graph.client import GraphClient
        from scar.graph.queries import recall_for_context
    except Exception:
        return None
    try:
        with GraphClient.from_env() as client:
            return recall_for_context(
                client,
                body["repo_id"],
                body["file_path"],
                symbol=body.get("symbol"),
                error_text=body.get("error_text"),
                task_text=body.get("task_text"),
            )
    except Exception:
        return None


def try_live_blast(error_id: str) -> dict[str, Any] | None:
    if not live_requested():
        return None
    try:
        from scar.graph.client import GraphClient
        from scar.graph.queries import blast_radius
    except Exception:
        return None
    try:
        with GraphClient.from_env() as client:
            return blast_radius(client, error_id)
    except Exception:
        return None


def recall(payload: dict[str, Any], graph: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    body = _parse_recall_body(payload)
    live = try_live_recall(body)
    if live is not None:
        return live, "live"
    return fixture_recall(
        graph or load_fixture(),
        body["repo_id"],
        body["file_path"],
        symbol=body.get("symbol"),
        error_text=body.get("error_text"),
        task_text=body.get("task_text"),
    ), "fixture"


def blast(payload: dict[str, Any], graph: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    error_id = _parse_blast_body(payload)
    live = try_live_blast(error_id)
    if live is not None:
        return live, "live"
    return fixture_blast(graph or load_fixture(), error_id), "fixture"


def _safe_ui(rel: str) -> Path | None:
    if not rel or rel.endswith("/"):
        rel = rel + "index.html" if rel else "index.html"
    rel = rel.lstrip("/")
    candidate = (UI_DIR / rel).resolve()
    try:
        candidate.relative_to(UI_DIR.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "SCARDemo/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _send_bytes(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        self._send_bytes(status, body, "application/json; charset=utf-8", extra)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("json object required")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route in {"/", "/index.html"}:
            page = _safe_ui("index.html")
            if page is None:
                self._send_json(500, {"error": "ui/index.html missing"})
                return
            self._send_bytes(200, page.read_bytes(), MIME[".html"])
            return
        if route == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "mode": "live" if live_requested() else "fixture",
                    "fixture": str(FIXTURE_PATH.relative_to(ROOT)),
                },
            )
            return
        if route == "/fixture":
            if not FIXTURE_PATH.is_file():
                self._send_json(404, {"error": "fixtures/demo_graph.json missing"})
                return
            self._send_bytes(200, FIXTURE_PATH.read_bytes(), MIME[".json"])
            return
        if route == "/layout":
            if not LAYOUT_PATH.is_file():
                self._send_json(404, {"error": "fixtures/demo_ui_layout.json missing"})
                return
            self._send_bytes(200, LAYOUT_PATH.read_bytes(), MIME[".json"])
            return
        rel = route.lstrip("/")
        page = _safe_ui(rel)
        if page is None:
            self._send_json(404, {"error": f"not found: {route}"})
            return
        content_type = MIME.get(page.suffix.lower(), "application/octet-stream")
        self._send_bytes(200, page.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if route == "/v1/recall":
            result, mode = recall(payload)
            self._send_json(200, result, extra={"X-SCAR-Mode": mode})
            return
        if route in {"/v1/blast", "/v1/blast-radius"}:
            result, mode = blast(payload)
            self._send_json(200, result, extra={"X-SCAR-Mode": mode})
            return
        self._send_json(404, {"error": f"not found: {route}"})


def serve(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), DemoHandler)
    return httpd


def main() -> int:
    if not UI_DIR.is_dir():
        print(f"missing UI directory: {UI_DIR}", file=sys.stderr)
        return 1
    if not FIXTURE_PATH.is_file():
        print(f"missing fixture: {FIXTURE_PATH}", file=sys.stderr)
        return 1
    httpd = serve(HOST, PORT)
    mode = "live (fallback fixture)" if live_requested() else "fixture"
    print(f"SCAR demo  http://{HOST}:{PORT}/  mode={mode}", flush=True)
    print(f"  GET  /fixture   {FIXTURE_PATH.relative_to(ROOT)}", flush=True)
    print("  POST /v1/recall  POST /v1/blast", flush=True)
    print("  graph renderer is hand-rolled SVG in ui/graph.js (no CDN)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
