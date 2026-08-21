"""Minimal MCP stdio server (JSON-RPC) for SCAR recall/record/blast-radius."""

from __future__ import annotations

import io
import json
import sys
from typing import Any, BinaryIO, TextIO

from scar.serve import blast, connect_client, format_recall, recall_context, record_correction

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scar"
SERVER_VERSION = "0.1.0"

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "scar_recall",
        "description": (
            "Recall stored SCAR corrections for the current file, symbol, error, "
            "or task before editing. Obey active hits. If SCAR abstains, proceed normally."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_id": {"type": "string"},
                "file_path": {"type": "string"},
                "symbol": {"type": "string"},
                "error_text": {"type": "string"},
                "task_text": {"type": "string"},
            },
            "required": ["repo_id", "file_path"],
        },
    },
    {
        "name": "scar_record",
        "description": (
            "Record a human_instruction correction now (manual capture when the "
            "user just corrected the agent)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_id": {"type": "string"},
                "file_path": {"type": "string"},
                "correction_text": {"type": "string"},
                "error_text": {"type": "string"},
            },
            "required": ["repo_id", "file_path", "correction_text"],
        },
    },
    {
        "name": "scar_blast_radius",
        "description": (
            "Files that IMPORTS* a file which emitted the same error signature."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "error_id": {"type": "string"},
                "signature": {"type": "string"},
            },
        },
    },
]


def list_tools() -> list[dict[str, Any]]:
    return list(TOOL_SPECS)


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name: str, arguments: dict[str, Any] | None, client: Any) -> dict[str, Any]:
    args = arguments or {}
    if name == "scar_recall":
        repo_id = args.get("repo_id")
        file_path = args.get("file_path")
        if not repo_id or not file_path:
            return _text_result("repo_id and file_path are required", is_error=True)
        result = recall_context(
            client,
            str(repo_id),
            str(file_path),
            symbol=args.get("symbol"),
            error_text=args.get("error_text"),
            task_text=args.get("task_text"),
        )
        return _text_result(format_recall(result))
    if name == "scar_record":
        repo_id = args.get("repo_id")
        file_path = args.get("file_path")
        correction_text = args.get("correction_text")
        if not repo_id or not file_path or not correction_text:
            return _text_result(
                "repo_id, file_path, and correction_text are required",
                is_error=True,
            )
        result = record_correction(
            client,
            str(repo_id),
            str(file_path),
            str(correction_text),
            error_text=args.get("error_text"),
        )
        return _text_result(json.dumps(result))
    if name == "scar_blast_radius":
        result = blast(
            client,
            error_id=args.get("error_id"),
            signature=args.get("signature"),
        )
        return _text_result(json.dumps(result))
    return _text_result(f"unknown tool: {name}", is_error=True)


def handle_rpc(request: dict[str, Any], client: Any) -> dict[str, Any] | None:
    """Handle one JSON-RPC MCP message. Notifications return None."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}
    if method == "notifications/initialized" or req_id is None and str(method or "").startswith(
        "notifications/"
    ):
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": list_tools()}}
    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        result = call_tool(str(name), arguments, client)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_content_length_message(raw: bytes, stream: BinaryIO) -> dict[str, Any] | None:
    header_blob = raw
    while b"\r\n\r\n" not in header_blob and b"\n\n" not in header_blob:
        chunk = stream.read(1)
        if not chunk:
            return None
        header_blob += chunk
        if len(header_blob) > 65536:
            return None
    if b"\r\n\r\n" in header_blob:
        header, rest = header_blob.split(b"\r\n\r\n", 1)
    else:
        header, rest = header_blob.split(b"\n\n", 1)
    length = 0
    for line in header.decode("utf-8", errors="replace").splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    needed = length - len(rest)
    body = rest
    if needed > 0:
        body += stream.read(needed)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def read_message(stream: BinaryIO | TextIO) -> dict[str, Any] | None:
    """Read one MCP message (newline-delimited JSON or Content-Length framed)."""
    if isinstance(stream, io.TextIOBase):
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            return read_message(stream)
        return json.loads(line)

    first = stream.read(1)
    if not first:
        return None
    if first in b"{[":
        buf = first
        while True:
            ch = stream.read(1)
            if not ch or ch == b"\n":
                break
            buf += ch
        return json.loads(buf.decode("utf-8"))
    return _read_content_length_message(first, stream)


def write_message(stream: BinaryIO | TextIO, message: dict[str, Any]) -> None:
    encoded = json.dumps(message, ensure_ascii=False)
    if isinstance(stream, io.TextIOBase):
        stream.write(encoded + "\n")
        stream.flush()
        return
    stream.write(encoded.encode("utf-8") + b"\n")
    stream.flush()


def serve_stdio(
    client: Any | None = None,
    stdin: BinaryIO | TextIO | None = None,
    stdout: BinaryIO | TextIO | None = None,
) -> None:
    graph = client if client is not None else connect_client()
    incoming = stdin if stdin is not None else sys.stdin.buffer
    outgoing = stdout if stdout is not None else sys.stdout.buffer
    while True:
        try:
            request = read_message(incoming)
        except json.JSONDecodeError:
            continue
        if request is None:
            break
        response = handle_rpc(request, graph)
        if response is not None:
            write_message(outgoing, response)


def main() -> int:
    try:
        client = connect_client()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    serve_stdio(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
