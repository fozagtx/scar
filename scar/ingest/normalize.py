"""Normalize raw extractor output into the frozen SCAR session schema."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = frozenset({"cursor", "claude-code", "codex"})
ROLES = frozenset({"user", "assistant", "tool"})

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".vue": "vue",
    ".svelte": "svelte",
}

PATH_KEYS = (
    "path",
    "file_path",
    "filePath",
    "filepath",
    "file",
    "filename",
    "file_name",
    "target_file",
    "targetFile",
    "relative_workspace_path",
    "relativeWorkspacePath",
    "fsPath",
)

_TRACEBACK_RE = re.compile(r"(?i)\btraceback\b")
_FAILED_RE = re.compile(r"\bFAILED\b")
_ERROR_EXC_RE = re.compile(
    r"(?i)\b(?:[A-Za-z_][\w]*(?:Error|Exception)|Error|Exception)\b"
)
_COMPILER_RE = re.compile(
    r"\b(?:TS\d{3,5}|E\d{3,4}|error C\d{4}|error\[E\d{4}\])\b"
)
_EXIT_RE = re.compile(
    r"(?i)\b(?:exit(?:ed|_code)?|status|return(?:ed)?(?:\s+code)?)\s*[:=]?\s*(-?\d+)\b"
)
_HOME_POSIX_RE = re.compile(r"^/(?:Users|home)/[^/]+")
_HOME_WIN_RE = re.compile(r"(?i)^[A-Z]:\\Users\\[^\\]+")


def language_from_path(path: str | None) -> str | None:
    if not path:
        return None
    suffix = Path(str(path).split("?")[0]).suffix.lower()
    return LANGUAGE_BY_SUFFIX.get(suffix)


def redact_path(path: str | None) -> str | None:
    """Replace home-directory prefixes with `~`. Never raise."""
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return ""
    if text.startswith("file://"):
        text = text[len("file://") :]
        if text.startswith("localhost/"):
            text = text[len("localhost") :]
    homes: list[str] = []
    try:
        homes.append(str(Path.home()))
    except Exception:
        pass
    for env_key in ("HOME", "USERPROFILE"):
        value = os.environ.get(env_key)
        if value:
            homes.append(value)
    for home in homes:
        home = home.rstrip("/\\")
        if not home:
            continue
        if text == home or text.startswith(home + "/") or text.startswith(home + "\\"):
            return "~" + text[len(home) :].replace("\\", "/")
    text = _HOME_POSIX_RE.sub("~", text)
    text = _HOME_WIN_RE.sub("~", text)
    return text.replace("\\", "/")


def to_iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        elif 1e11 < ts <= 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        try:
            return to_iso(float(text))
        except ValueError:
            return text
    return text.replace("+00:00", "Z")


def looks_like_tool_error(
    text: str | None,
    *,
    exit_code: int | None = None,
    is_error: bool | None = None,
) -> bool:
    """True for nonzero exit, traceback, FAILED, Error/Exception, compiler codes."""
    if is_error is True:
        return True
    if exit_code is not None:
        try:
            if int(exit_code) != 0:
                return True
        except (TypeError, ValueError):
            pass
    blob = text or ""
    if not blob:
        return False
    if _TRACEBACK_RE.search(blob):
        return True
    if _FAILED_RE.search(blob):
        return True
    if _ERROR_EXC_RE.search(blob):
        return True
    if _COMPILER_RE.search(blob):
        return True
    match = _EXIT_RE.search(blob)
    if match:
        try:
            return int(match.group(1)) != 0
        except ValueError:
            return False
    return False


def parse_exit_code(text: str | None, explicit: Any = None) -> int | None:
    if explicit is not None and explicit != "":
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass
    if not text:
        return None
    match = _EXIT_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts = [stringify_content(item) for item in content]
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "message", "output", "result", "stdout"):
            if key in content and content[key] not in (None, ""):
                return stringify_content(content[key])
        try:
            return json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def files_from_paths(paths: Any, language: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _flatten_paths(paths):
        redacted = redact_path(raw) or ""
        if not redacted or redacted in seen:
            continue
        seen.add(redacted)
        out.append(
            {
                "path": redacted,
                "language": language or language_from_path(redacted),
            }
        )
    return out


def files_from_mapping(obj: Any) -> list[dict[str, Any]]:
    if not isinstance(obj, dict):
        return []
    paths: list[Any] = []
    for key in PATH_KEYS:
        value = obj.get(key)
        if value:
            paths.append(value)
    uri = obj.get("uri")
    if isinstance(uri, dict):
        if uri.get("fsPath"):
            paths.append(uri["fsPath"])
        if uri.get("path"):
            paths.append(uri["path"])
    return files_from_paths(paths)


def _flatten_paths(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_paths(item))
        return out
    if isinstance(value, dict):
        return _flatten_paths(
            value.get("path")
            or value.get("fsPath")
            or value.get("file")
            or value.get("file_path")
        )
    text = str(value).strip()
    return [text] if text else []


def _is_empty_turn(turn: dict[str, Any]) -> bool:
    text = (turn.get("text") or "").strip()
    files = turn.get("files") or []
    tool_name = turn.get("tool_name")
    diff = turn.get("diff_summary")
    return not text and not files and not tool_name and not diff


def normalize_turn(raw: Any, session_id: str, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    if role not in ROLES:
        return None

    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in raw.get("files") or []:
        extracted: list[dict[str, Any]]
        if isinstance(item, str):
            extracted = files_from_paths([item])
        elif isinstance(item, dict):
            path = item.get("path") or item.get("file") or item.get("fsPath")
            if path:
                extracted = [
                    {
                        "path": redact_path(str(path)) or str(path),
                        "language": item.get("language") or language_from_path(str(path)),
                    }
                ]
            else:
                extracted = files_from_mapping(item)
        else:
            continue
        for entry in extracted:
            key = entry["path"]
            if key in seen_paths:
                continue
            seen_paths.add(key)
            files.append(entry)

    text = stringify_content(raw.get("text"))
    exit_code = parse_exit_code(text, raw.get("exit_code"))
    tool_is_error = raw.get("tool_is_error")
    if tool_is_error is None:
        tool_is_error = (
            looks_like_tool_error(text, exit_code=exit_code) if role == "tool" else False
        )
    else:
        tool_is_error = bool(tool_is_error)

    turn_id = raw.get("turn_id") or raw.get("id")
    if not turn_id:
        turn_id = f"{session_id}:t{index:04d}"

    tool_name = raw.get("tool_name")
    if tool_name == "":
        tool_name = None
    elif tool_name is not None:
        tool_name = str(tool_name)

    diff_summary = raw.get("diff_summary")
    if isinstance(diff_summary, str) and not diff_summary.strip():
        diff_summary = None
    elif diff_summary is not None:
        diff_summary = str(diff_summary)

    turn = {
        "turn_id": str(turn_id),
        "role": role,
        "ts": to_iso(raw.get("ts") or raw.get("timestamp")),
        "text": text,
        "files": files,
        "tool_name": tool_name,
        "tool_is_error": tool_is_error,
        "exit_code": exit_code,
        "diff_summary": diff_summary,
    }
    if _is_empty_turn(turn):
        return None
    return turn


def normalize_session(raw: Any) -> dict[str, Any]:
    """Return a frozen-schema session dict. Raises ValueError on bad source."""
    if not isinstance(raw, dict):
        raise TypeError("session must be a dict")
    source = raw.get("source")
    if source not in SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    session_id = raw.get("session_id") or raw.get("id") or "unknown"
    session_id = str(session_id)

    project_path = raw.get("project_path")
    if project_path:
        project_path = redact_path(str(project_path))
    else:
        project_path = None

    model = raw.get("model")
    if model == "" or model is None:
        model = None
    else:
        model = str(model)

    turns: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("turns") or []):
        turn = normalize_turn(item, session_id, index)
        if turn:
            turns.append(turn)

    started_at = to_iso(raw.get("started_at"))
    if not started_at and turns:
        started_at = turns[0].get("ts")

    return {
        "session_id": session_id,
        "source": source,
        "started_at": started_at,
        "project_path": project_path,
        "model": model,
        "turns": turns,
    }
