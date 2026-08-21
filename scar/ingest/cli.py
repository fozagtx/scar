"""CLI: extract Cursor / Claude Code / Codex transcripts to frozen JSONL.

Usage:
    python -m scar.ingest OUT.jsonl --source all|cursor|claude-code|codex
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from scar.ingest.extractors.claude_code import extract_claude_code
from scar.ingest.extractors.codex import extract_codex
from scar.ingest.extractors.cursor import extract_cursor
from scar.ingest.normalize import normalize_session

SOURCES = ("cursor", "claude-code", "codex")


def collect_sessions(
    source: str = "all", home: Path | None = None
) -> list[dict[str, Any]]:
    """Run the requested extractors. Never raises on missing installs."""
    wanted = set(SOURCES) if source == "all" else {source}
    sessions: list[dict[str, Any]] = []
    if "cursor" in wanted:
        sessions.extend(extract_cursor(home=home))
    if "claude-code" in wanted:
        sessions.extend(extract_claude_code(home=home))
    if "codex" in wanted:
        sessions.extend(extract_codex(home=home))
    normalized: list[dict[str, Any]] = []
    for raw in sessions:
        try:
            normalized.append(normalize_session(raw))
        except (TypeError, ValueError):
            continue
    return normalized


def write_jsonl(path: Path, sessions: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for session in sessions:
            handle.write(json.dumps(session, ensure_ascii=False) + "\n")
            count += 1
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scar.ingest",
        description=(
            "Extract Cursor, Claude Code, and Codex transcripts into one "
            "frozen JSONL schema. Does not talk to HydraDB."
        ),
    )
    parser.add_argument("output", help="Destination JSONL path (one session per line)")
    parser.add_argument(
        "--source",
        choices=("all", "cursor", "claude-code", "codex"),
        default="all",
        help="Which assistant transcripts to extract (default: all)",
    )
    parser.add_argument(
        "--home",
        default=None,
        help="Override home directory used to locate local transcript stores",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    home = Path(args.home) if args.home else None
    sessions = collect_sessions(args.source, home=home)
    count = write_jsonl(Path(args.output), sessions)
    print(f"wrote {count} session(s) to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
