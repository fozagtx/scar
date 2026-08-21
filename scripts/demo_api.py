#!/usr/bin/env python3
"""Local SCAR demo UI over a live HydraDB graph-node.

    python scripts/demo_api.py

Requires HydraDB on 127.0.0.1 (Bolt 7687 / admin 9090). Extract local
Cursor / Claude Code / Codex sessions and `scar ingest` them first.
The UI does not serve fixture JSON and does not fall back to mock recall.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI_DIR = ROOT / "ui"
HOST = os.environ.get("SCAR_DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("SCAR_DEMO_PORT", "7331"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_BOUND_CLIENT: Any = None


def bind_client(client: Any | None) -> None:
    """Tests inject a FakeClient. Production always uses GraphClient.from_env()."""
    global _BOUND_CLIENT
    _BOUND_CLIENT = client


def _client() -> Any:
    if _BOUND_CLIENT is not None:
        return _BOUND_CLIENT
    from scar.serve import connect_client

    return connect_client()


def _parse_recall_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_id": str(payload.get("repo_id") or payload.get("repo") or ""),
        "file_path": str(payload.get("file_path") or payload.get("file") or ""),
        "symbol": payload.get("symbol") or None,
        "error_text": payload.get("error_text") or payload.get("error") or None,
        "task_text": payload.get("task_text") or payload.get("task") or None,
    }


def live_graph() -> dict[str, Any]:
    from scar.graph.queries import export_graph

    return export_graph(_client())


def live_recall(payload: dict[str, Any]) -> dict[str, Any]:
    from scar.serve import recall_context

    body = _parse_recall_body(payload)
    return recall_context(
        _client(),
        body["repo_id"],
        body["file_path"],
        symbol=body.get("symbol"),
        error_text=body.get("error_text"),
        task_text=body.get("task_text"),
    )


def live_blast(payload: dict[str, Any]) -> dict[str, Any]:
    from scar.serve import blast

    error_id = str(payload.get("error_id") or payload.get("id") or "")
    return blast(_client(), error_id=error_id or None)


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
        headers = {"X-SCAR-Mode": "live"}
        if extra:
            headers.update(extra)
        self._send_bytes(status, body, "application/json; charset=utf-8", headers)

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
            from scar.graph.client import hydra_is_ready

            ready = True if _BOUND_CLIENT is not None else hydra_is_ready()
            self._send_json(200 if ready else 503, {"ok": ready, "mode": "live"})
            return
        if route == "/graph":
            try:
                self._send_json(200, live_graph())
            except Exception as exc:
                self._send_json(503, {"error": f"HydraDB unavailable: {exc}"})
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
        try:
            if route == "/v1/recall":
                self._send_json(200, live_recall(payload))
                return
            if route in {"/v1/blast", "/v1/blast-radius"}:
                self._send_json(200, live_blast(payload))
                return
        except Exception as exc:
            self._send_json(503, {"error": f"HydraDB unavailable: {exc}"})
            return
        self._send_json(404, {"error": f"not found: {route}"})


def serve(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), DemoHandler)


def main() -> int:
    from scar.graph.client import hydra_is_ready

    if not UI_DIR.is_dir():
        print(f"missing UI directory: {UI_DIR}", file=sys.stderr)
        return 1
    if _BOUND_CLIENT is None and not hydra_is_ready():
        print(
            "HydraDB graph-node is not up on 127.0.0.1:9090.\n"
            "  ./scripts/init-hydradb-data.sh\n"
            "  UID=$(id -u) GID=$(id -g) docker compose up\n"
            "Then extract local sessions and ingest them:\n"
            "  .venv/bin/python -m scar.ingest extracted.jsonl --source all\n"
            "  .venv/bin/scar ingest extracted.jsonl --repo $(basename \"$PWD\")",
            file=sys.stderr,
        )
        return 1
    httpd = serve(HOST, PORT)
    print(f"SCAR demo  http://{HOST}:{PORT}/  mode=live (HydraDB)", flush=True)
    print("  GET  /graph     dump from graph-node", flush=True)
    print("  POST /v1/recall  POST /v1/blast", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
