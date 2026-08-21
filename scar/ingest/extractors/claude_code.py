"""Claude Code transcript extractor for SCAR.

Reads JSONL sessions under ~/.claude/projects into the frozen SCAR session schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scar.ingest.normalize import (
    files_from_mapping,
    looks_like_tool_error,
    normalize_session,
    parse_exit_code,
    stringify_content,
    to_iso,
)


def extract_claude_code(home: Path | None = None) -> list[dict[str, Any]]:
    """Return frozen-schema sessions. Missing install => [] and never raises."""
    try:
        root = Path(home) if home is not None else Path.home()
    except Exception:
        return []
    try:
        files = _session_files(root)
    except Exception:
        return []
    sessions: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in files:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            sessions.extend(_parse_jsonl(path))
        except Exception:
            continue
    return sessions


def _session_files(home: Path) -> list[Path]:
    found: list[Path] = []
    projects = home / ".claude" / "projects"
    if projects.is_dir():
        found.extend(projects.rglob("*.jsonl"))
    claude_code = home / ".claude-code"
    if claude_code.exists():
        if claude_code.is_dir():
            found.extend(claude_code.rglob("*.jsonl"))
        elif claude_code.suffix == ".jsonl":
            found.append(claude_code)
    return [
        path
        for path in found
        if path.is_file() and not path.name.startswith("agent-")
    ]


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        session_id = (
            obj.get("sessionId") or obj.get("session_id") or path.stem
        )
        grouped.setdefault(str(session_id), []).append(obj)

    sessions: list[dict[str, Any]] = []
    for session_id, events in grouped.items():
        raw = _events_to_session(session_id, events, path)
        if not raw["turns"]:
            continue
        try:
            sessions.append(normalize_session(raw))
        except (TypeError, ValueError):
            continue
    return sessions


def _events_to_session(
    session_id: str, events: list[dict[str, Any]], path: Path
) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    tool_files: dict[str, list[dict[str, Any]]] = {}
    project_path: str | None = None
    model: str | None = None
    started_at: str | None = None

    for obj in events:
        cwd = obj.get("cwd")
        if isinstance(cwd, str) and cwd and project_path is None:
            project_path = cwd
        ts = to_iso(obj.get("timestamp"))
        if ts and started_at is None:
            started_at = ts

        event_type = obj.get("type")
        if event_type in {
            "mode",
            "permission-mode",
            "file-history-snapshot",
            "file-history-delta",
            "attachment",
            "last-prompt",
            "system",
            "progress",
            "queue-operation",
        }:
            continue

        if event_type in {"user", "assistant"}:
            message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if event_type == "assistant":
                model = model or message.get("model") or obj.get("model")
            turns.extend(
                _turns_from_message(
                    role=event_type,
                    message=message,
                    ts=ts,
                    tool_names=tool_names,
                    tool_files=tool_files,
                    extra=obj,
                )
            )
            continue

        if event_type in {"tool_use", "tool_result"}:
            turns.extend(
                _turns_from_tool_event(
                    obj, ts=ts, tool_names=tool_names, tool_files=tool_files
                )
            )

    return {
        "session_id": session_id,
        "source": "claude-code",
        "started_at": started_at,
        "project_path": project_path,
        "model": model,
        "turns": turns,
        "_source_file": str(path),
    }


def _turns_from_message(
    *,
    role: str,
    message: dict[str, Any],
    ts: str | None,
    tool_names: dict[str, str],
    tool_files: dict[str, list[dict[str, Any]]],
    extra: dict[str, Any],
) -> list[dict[str, Any]]:
    content = message.get("content", extra.get("content"))
    if isinstance(content, str):
        if not content.strip():
            return []
        return [
            {
                "role": "user" if role == "user" else "assistant",
                "ts": ts,
                "text": content,
                "files": [],
                "tool_name": None,
                "tool_is_error": False,
                "exit_code": None,
                "diff_summary": None,
            }
        ]
    if not isinstance(content, list):
        return []

    turns: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            text_parts.append(stringify_content(item))
            continue
        item_type = item.get("type")
        if item_type == "text":
            text_parts.append(item.get("text") or "")
            continue
        if item_type == "thinking":
            continue
        if item_type == "tool_use":
            if text_parts:
                joined = "\n".join(p for p in text_parts if p).strip()
                if joined:
                    turns.append(
                        {
                            "role": "assistant",
                            "ts": ts,
                            "text": joined,
                            "files": [],
                            "tool_name": None,
                            "tool_is_error": False,
                            "exit_code": None,
                            "diff_summary": None,
                        }
                    )
                text_parts = []
            turns.append(_tool_use_turn(item, ts, tool_names, tool_files))
            continue
        if item_type == "tool_result":
            if text_parts:
                joined = "\n".join(p for p in text_parts if p).strip()
                if joined:
                    turns.append(
                        {
                            "role": "user" if role == "user" else "assistant",
                            "ts": ts,
                            "text": joined,
                            "files": [],
                            "tool_name": None,
                            "tool_is_error": False,
                            "exit_code": None,
                            "diff_summary": None,
                        }
                    )
                text_parts = []
            turns.append(_tool_result_turn(item, ts, tool_names, tool_files))
    joined = "\n".join(p for p in text_parts if p).strip()
    if joined:
        turns.append(
            {
                "role": "user" if role == "user" else "assistant",
                "ts": ts,
                "text": joined,
                "files": [],
                "tool_name": None,
                "tool_is_error": False,
                "exit_code": None,
                "diff_summary": None,
            }
        )
    return [turn for turn in turns if turn]


def _tool_use_turn(
    item: dict[str, Any],
    ts: str | None,
    tool_names: dict[str, str],
    tool_files: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    tool_id = str(item.get("id") or item.get("tool_use_id") or "")
    name = str(item.get("name") or item.get("tool") or "tool")
    if tool_id:
        tool_names[tool_id] = name
    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
    files = files_from_mapping(inp)
    if tool_id:
        tool_files[tool_id] = files
    summary_bits = []
    if inp.get("command"):
        summary_bits.append(str(inp["command"]))
    if inp.get("file_path") or inp.get("path"):
        summary_bits.append(str(inp.get("file_path") or inp.get("path")))
    if inp.get("old_string") or inp.get("new_string"):
        summary_bits.append("str_replace")
    text = stringify_content(inp) if inp else name
    diff_summary = None
    if name in {"Edit", "Write", "NotebookEdit", "StrReplace"} and files:
        diff_summary = f"{name} {files[0]['path']}"
    elif summary_bits:
        diff_summary = "; ".join(summary_bits)[:500]
    return {
        "role": "tool",
        "ts": ts,
        "text": text,
        "files": files,
        "tool_name": name,
        "tool_is_error": False,
        "exit_code": None,
        "diff_summary": diff_summary,
    }


def _tool_result_turn(
    item: dict[str, Any],
    ts: str | None,
    tool_names: dict[str, str],
    tool_files: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    tool_id = str(item.get("tool_use_id") or item.get("id") or "")
    name = item.get("name") or item.get("tool") or tool_names.get(tool_id)
    content = stringify_content(item.get("content") or item.get("output") or item.get("result"))
    is_error = item.get("is_error")
    if isinstance(is_error, str):
        is_error = is_error.lower() in {"true", "1", "yes"}
    exit_code = parse_exit_code(content, item.get("exit_code") or item.get("status_code"))
    files = files_from_mapping(item)
    if not files and isinstance(item.get("input"), dict):
        files = files_from_mapping(item["input"])
    if not files and tool_id:
        files = list(tool_files.get(tool_id) or [])
    return {
        "role": "tool",
        "ts": ts,
        "text": content,
        "files": files,
        "tool_name": name,
        "tool_is_error": looks_like_tool_error(
            content, exit_code=exit_code, is_error=bool(is_error) if is_error is not None else None
        ),
        "exit_code": exit_code,
        "diff_summary": None,
    }


def _turns_from_tool_event(
    obj: dict[str, Any],
    ts: str | None,
    tool_names: dict[str, str],
    tool_files: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    payload = obj.get("toolResult") or obj.get("tool_result") or obj
    if obj.get("type") == "tool_use":
        return [_tool_use_turn(obj.get("toolUse") or obj, ts, tool_names, tool_files)]
    if isinstance(payload, dict):
        return [_tool_result_turn(payload, ts, tool_names, tool_files)]
    return []
