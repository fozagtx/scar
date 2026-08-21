"""SCAR CLI: ingest, recall, record, abstain-check, plus HTTP/MCP entrypoints.

Usage:
    scar ingest sessions.jsonl --repo demo-repo
    scar recall --repo demo-repo --file src/timeutil.py --error "AttributeError utcnow"
    scar record --repo demo-repo --file src/timeutil.py --correction "never use utcnow"
    scar abstain-check --repo demo-repo --file /no/such.py
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from scar.serve import (
    connect_client,
    format_recall,
    ingest_jsonl,
    recall_context,
    record_correction,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scar",
        description="Stored Corrections And Recall — query before you edit, record after you are corrected.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Mine a JSONL transcript and upsert scars into the graph")
    ingest.add_argument("jsonl", help="Path to JSONL (or JSON) sessions")
    ingest.add_argument("--repo", required=True, help="Repo id to attach upserts to")

    recall = sub.add_parser("recall", help="Print stored corrections for a file context")
    recall.add_argument("--repo", required=True)
    recall.add_argument("--file", required=True)
    recall.add_argument("--symbol", default=None)
    recall.add_argument("--error", default=None, help="Error text to match against signatures")
    recall.add_argument("--task", default=None, help="Task text (ranking hint only)")

    record = sub.add_parser("record", help="Write a human_instruction correction now")
    record.add_argument("--repo", required=True)
    record.add_argument("--file", required=True)
    record.add_argument("--correction", required=True)
    record.add_argument("--error", default=None)

    abstain = sub.add_parser(
        "abstain-check",
        help="Exit 0 only if recall abstains (demo/test helper)",
    )
    abstain.add_argument("--repo", required=True)
    abstain.add_argument("--file", required=True)

    serve = sub.add_parser("serve", help="Run the stdlib HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    sub.add_parser("mcp", help="Run the MCP JSON-RPC server on stdio")
    return parser


def _client(explicit: Any | None) -> Any:
    if explicit is not None:
        return explicit
    return connect_client()


def main(argv: Sequence[str] | None = None, client: Any | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return _dispatch(args, client)
    except (RuntimeError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, client: Any | None) -> int:
    if args.command == "serve":
        from scar.serve.http_api import serve as serve_http

        graph = _client(client)
        print(f"SCAR HTTP listening on http://{args.host}:{args.port}", file=sys.stderr)
        serve_http(args.host, args.port, graph)
        return 0
    if args.command == "mcp":
        from scar.serve.mcp_server import serve_stdio

        serve_stdio(_client(client))
        return 0

    graph = _client(client)
    if args.command == "ingest":
        count = ingest_jsonl(graph, args.jsonl, args.repo)
        print(f"ingested {count} graph op(s) from {args.jsonl} into repo {args.repo}")
        return 0
    if args.command == "recall":
        result = recall_context(
            graph,
            args.repo,
            args.file,
            symbol=args.symbol,
            error_text=args.error,
            task_text=args.task,
        )
        print(format_recall(result))
        return 0
    if args.command == "record":
        payload = record_correction(
            graph,
            args.repo,
            args.file,
            args.correction,
            error_text=args.error,
        )
        print(payload["correction_id"])
        return 0
    if args.command == "abstain-check":
        result = recall_context(graph, args.repo, args.file)
        return 0 if result.get("abstain") else 1
    parser_fallback = build_parser()
    parser_fallback.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
