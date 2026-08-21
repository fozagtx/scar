"""Stdlib HTTP API for recall and record. No FastAPI dependency."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from scar.serve import connect_client, recall_context, record_correction

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


def handle_request(
    method: str,
    path: str,
    body: bytes | str | None,
    client: Any,
) -> tuple[int, str, bytes]:
    """Dispatch one HTTP call. Returns ``(status, content_type, body)``."""
    parsed = urlparse(path)
    route = parsed.path.rstrip("/") or "/"
    verb = method.upper()

    if verb == "GET" and route == "/healthz":
        return 200, "application/json", _json_bytes({"ok": True})

    if verb == "POST" and route == "/v1/recall":
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            return 400, "application/json", _json_bytes({"error": f"invalid JSON: {exc}"})
        if not isinstance(payload, dict):
            return 400, "application/json", _json_bytes({"error": "JSON object required"})
        repo_id = payload.get("repo_id")
        file_path = payload.get("file_path")
        if not repo_id or not file_path:
            return 400, "application/json", _json_bytes(
                {"error": "repo_id and file_path are required"}
            )
        result = recall_context(
            client,
            str(repo_id),
            str(file_path),
            symbol=payload.get("symbol"),
            error_text=payload.get("error_text"),
            task_text=payload.get("task_text"),
        )
        return 200, "application/json", _json_bytes(result)

    if verb == "POST" and route == "/v1/record":
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            return 400, "application/json", _json_bytes({"error": f"invalid JSON: {exc}"})
        if not isinstance(payload, dict):
            return 400, "application/json", _json_bytes({"error": "JSON object required"})
        repo_id = payload.get("repo_id")
        file_path = payload.get("file_path")
        correction_text = payload.get("correction_text")
        if not repo_id or not file_path or not correction_text:
            return 400, "application/json", _json_bytes(
                {"error": "repo_id, file_path, and correction_text are required"}
            )
        result = record_correction(
            client,
            str(repo_id),
            str(file_path),
            str(correction_text),
            error_text=payload.get("error_text"),
        )
        return 200, "application/json", _json_bytes(result)

    if verb in {"GET", "POST"}:
        return 404, "application/json", _json_bytes({"error": f"not found: {route}"})
    return 405, "application/json", _json_bytes({"error": f"method not allowed: {verb}"})


class ScarHTTPRequestHandler(BaseHTTPRequestHandler):
    graph_client: Any = None

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        status, content_type, body = handle_request(
            "GET", self.path, None, self.graph_client
        )
        self._write(status, content_type, body)

    def do_POST(self) -> None:  # noqa: N802
        status, content_type, body = handle_request(
            "POST", self.path, self._body(), self.graph_client
        )
        self._write(status, content_type, body)


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    client: Any | None = None,
) -> HTTPServer:
    bound = type(
        "BoundScarHandler",
        (ScarHTTPRequestHandler,),
        {"graph_client": client if client is not None else connect_client()},
    )
    return HTTPServer((host, port), bound)


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    client: Any | None = None,
) -> None:
    httpd = make_server(host, port, client)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scar.serve.http_api")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    try:
        client = connect_client()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"SCAR HTTP listening on http://{args.host}:{args.port}", file=sys.stderr)
    serve(args.host, args.port, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
