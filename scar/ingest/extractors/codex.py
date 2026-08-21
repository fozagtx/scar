"""Codex transcript extractor for SCAR.

Reads local Codex rollout JSONL (`session_meta` / `user_message` / `agent_message`)
into the frozen SCAR session schema.
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


def extract_codex(home: Path | None = None) -> list[dict[str, Any]]:
    """Return frozen-schema sessions. Missing install => [] and never raises."""
    try:
        root = Path(home) if home is not None else Path.home()
    except Exception:
        return []
    try:
        files = _rollout_files(root)
    except Exception:
        return []
    sessions: list[dict[str, Any]] = []
    for path in files:
        try:
            session = _parse_rollout(path)
        except Exception:
            continue
        if session is not None:
            sessions.append(session)
    return sessions


def _rollout_files(home: Path) -> list[Path]:
    found: list[Path] = []
    for dirname in (".codex", ".codex-local"):
        base = home / dirname
        if not base.exists():
            continue
        try:
            found.extend(base.rglob("rollout-*.jsonl"))
        except OSError:
            continue
    return [path for path in found if path.is_file()]


def _parse_rollout(path: Path) -> dict[str, Any] | None:
    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    events: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    if not events:
        return None

    has_event_chat = any(
        obj.get("type") == "event_msg"
        and isinstance(obj.get("payload"), dict)
        and obj["payload"].get("type") in {"user_message", "agent_message"}
        for obj in events
    )

    session_id = path.stem
    project_path: str | None = None
    model: str | None = None
    started_at: str | None = None
    turns: list[dict[str, Any]] = []
    pending_tools: dict[str, str] = {}

    for obj in events:
        ts = to_iso(obj.get("timestamp"))
        if ts and started_at is None:
            started_at = ts
        event_type = obj.get("type")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

        if event_type == "session_meta":
            session_id = str(
                payload.get("id") or payload.get("session_id") or obj.get("id") or session_id
            )
            project_path = project_path or payload.get("cwd")
            started_at = to_iso(payload.get("timestamp")) or started_at
            model = model or payload.get("model")
            continue

        if event_type == "turn_context":
            project_path = project_path or payload.get("cwd")
            model = model or payload.get("model")
            continue

        payload_type = payload.get("type") if payload else event_type

        if event_type == "event_msg" or event_type in {
            "user_message",
            "agent_message",
            "tool_result",
        }:
            kind = payload_type or event_type
            body = payload if payload else obj
            if kind == "user_message":
                text = stringify_content(body.get("message") or body.get("text"))
                if text.strip():
                    turns.append(_chat_turn("user", text, ts, body))
            elif kind == "agent_message":
                text = stringify_content(body.get("message") or body.get("text"))
                if text.strip():
                    turns.append(_chat_turn("assistant", text, ts, body))
                model = model or body.get("model")
            elif kind == "tool_result":
                turns.append(_tool_result_from_payload(body, ts, pending_tools))
            elif kind == "patch_apply_end":
                turns.append(_patch_turn(body, ts))
            continue

        if event_type == "response_item":
            kind = payload_type
            if kind == "message" and not has_event_chat:
                role = payload.get("role")
                mapped = {"user": "user", "assistant": "assistant"}.get(role)
                if mapped:
                    text = stringify_content(payload.get("content"))
                    if text.strip():
                        turns.append(_chat_turn(mapped, text, ts, payload))
            elif kind in {"function_call", "custom_tool_call"}:
                call_id = str(payload.get("call_id") or payload.get("id") or "")
                name = str(payload.get("name") or payload.get("tool") or "tool")
                if call_id:
                    pending_tools[call_id] = name
                args = payload.get("arguments") or payload.get("input")
                parsed = _maybe_json(args)
                files = files_from_mapping(parsed) if isinstance(parsed, dict) else []
                turns.append(
                    {
                        "role": "tool",
                        "ts": ts,
                        "text": stringify_content(parsed if parsed is not None else args),
                        "files": files,
                        "tool_name": name,
                        "tool_is_error": False,
                        "exit_code": None,
                        "diff_summary": f"{name} {files[0]['path']}" if files else None,
                    }
                )
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                turns.append(_tool_result_from_payload(payload, ts, pending_tools))
            continue

        if event_type == "tool_result":
            turns.append(_tool_result_from_payload(payload or obj, ts, pending_tools))

    if not turns:
        return None
    raw = {
        "session_id": session_id,
        "source": "codex",
        "started_at": started_at,
        "project_path": project_path,
        "model": model,
        "turns": turns,
    }
    try:
        return normalize_session(raw)
    except (TypeError, ValueError):
        return None


def _chat_turn(role: str, text: str, ts: str | None, body: dict[str, Any]) -> dict[str, Any]:
    files = files_from_mapping(body)
    context = body.get("context")
    if isinstance(context, dict):
        files = files + files_from_mapping(context)
    return {
        "role": role,
        "ts": ts,
        "text": text,
        "files": files,
        "tool_name": None,
        "tool_is_error": False,
        "exit_code": None,
        "diff_summary": None,
    }


def _tool_result_from_payload(
    body: dict[str, Any], ts: str | None, pending_tools: dict[str, str]
) -> dict[str, Any]:
    call_id = str(body.get("call_id") or body.get("id") or "")
    name = body.get("tool") or body.get("name") or pending_tools.get(call_id)
    output = body.get("output") or body.get("result") or body.get("content")
    parsed = _maybe_json(output)
    text = stringify_content(parsed if parsed is not None else output)
    exit_code = body.get("exit_code")
    if exit_code is None and isinstance(parsed, dict):
        exit_code = parsed.get("exit_code") or parsed.get("exitCode")
        if not text or text == stringify_content(parsed):
            inner = parsed.get("output") or parsed.get("content") or parsed.get("stdout")
            if inner:
                text = stringify_content(inner)
    exit_code = parse_exit_code(text, exit_code)
    files = files_from_mapping(body)
    if isinstance(parsed, dict):
        files = files + files_from_mapping(parsed)
    success = body.get("success")
    is_error_flag = None
    if success is False:
        is_error_flag = True
    return {
        "role": "tool",
        "ts": ts,
        "text": text,
        "files": files,
        "tool_name": str(name) if name else None,
        "tool_is_error": looks_like_tool_error(
            text, exit_code=exit_code, is_error=is_error_flag
        ),
        "exit_code": exit_code,
        "diff_summary": None,
    }


def _patch_turn(body: dict[str, Any], ts: str | None) -> dict[str, Any]:
    success = body.get("success")
    text = stringify_content(body.get("stdout") or body.get("stderr") or body)
    files = []
    changes = body.get("changes")
    if isinstance(changes, dict):
        files = [{"path": str(p), "language": None} for p in changes.keys()]
    elif isinstance(changes, list):
        files = files_from_mapping({"files": changes})
        for item in changes:
            files.extend(files_from_mapping(item) if isinstance(item, dict) else [])
    return {
        "role": "tool",
        "ts": ts,
        "text": text or ("patch ok" if success else "patch failed"),
        "files": files,
        "tool_name": "patch_apply",
        "tool_is_error": looks_like_tool_error(
            text, is_error=True if success is False else None
        ),
        "exit_code": None if success is None else (0 if success else 1),
        "diff_summary": "patch_apply",
    }


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
