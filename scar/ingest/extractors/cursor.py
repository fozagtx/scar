"""Cursor transcript extractor for SCAR.

Reads composer/agent chats from local Cursor SQLite (`composerData:` / `bubbleId:` keys)
into the frozen SCAR session schema.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scar.ingest.normalize import (
    files_from_mapping,
    files_from_paths,
    looks_like_tool_error,
    normalize_session,
    parse_exit_code,
    stringify_content,
    to_iso,
)

_USER_TYPES = {1, "1", "user", "human"}
_ASSISTANT_TYPES = {2, "2", "ai", "assistant", "bot"}


def extract_cursor(home: Path | None = None) -> list[dict[str, Any]]:
    """Return frozen-schema sessions. Missing install => [] and never raises."""
    try:
        root = Path(home) if home is not None else Path.home()
    except Exception:
        return []
    try:
        db_paths = _discover_dbs(root)
    except Exception:
        return []
    sessions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for db_path in db_paths:
        try:
            for session in _extract_db(db_path):
                sid = session.get("session_id")
                if sid in seen_ids:
                    continue
                seen_ids.add(str(sid))
                sessions.append(session)
        except Exception:
            continue
    return sessions


def _discover_dbs(home: Path) -> list[Path]:
    roots = [
        home / "Library" / "Application Support" / "Cursor" / "User",
        home / ".config" / "Cursor" / "User",
        home / ".config" / "cursor" / "User",
    ]
    found: list[Path] = []
    for root in roots:
        global_db = root / "globalStorage" / "state.vscdb"
        if global_db.is_file():
            found.append(global_db)
        workspace = root / "workspaceStorage"
        if workspace.is_dir():
            try:
                children = list(workspace.iterdir())
            except OSError:
                children = []
            for child in children:
                db = child / "state.vscdb"
                if db.is_file():
                    found.append(db)
    return found


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)


def _extract_db(db_path: Path) -> list[dict[str, Any]]:
    project_path = _workspace_folder(db_path)
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error:
        return []
    try:
        kv = _load_kv(conn)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    composers = _collect_composers(kv)
    bubbles_by_composer = _collect_bubbles(kv)
    sessions: list[dict[str, Any]] = []
    for composer_id, composer in composers.items():
        bubbles = composer.get("conversation")
        if not isinstance(bubbles, list) or not bubbles:
            bubbles = bubbles_by_composer.get(composer_id, [])
            headers = composer.get("fullConversationHeadersOnly")
            if isinstance(headers, list) and headers:
                by_id = {
                    str(b.get("bubbleId") or ""): b
                    for b in bubbles
                    if isinstance(b, dict)
                }
                ordered: list[dict[str, Any]] = []
                for header in headers:
                    hid = None
                    if isinstance(header, dict):
                        hid = header.get("bubbleId")
                    elif isinstance(header, str):
                        hid = header
                    if hid and str(hid) in by_id:
                        ordered.append(by_id[str(hid)])
                if ordered:
                    bubbles = ordered
        if not bubbles:
            continue
        raw = _composer_to_session(
            composer_id, composer, bubbles, project_path=project_path
        )
        if not raw["turns"]:
            continue
        try:
            sessions.append(normalize_session(raw))
        except (TypeError, ValueError):
            continue
    return sessions


def _workspace_folder(db_path: Path) -> str | None:
    workspace_json = db_path.parent / "workspace.json"
    if not workspace_json.is_file():
        return None
    try:
        data = json.loads(workspace_json.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    folder = data.get("folder")
    if isinstance(folder, str) and folder:
        return folder
    if isinstance(folder, dict):
        return folder.get("path") or folder.get("fsPath")
    return None


def _load_kv(conn: sqlite3.Connection) -> dict[str, Any]:
    kv: dict[str, Any] = {}
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table in ("cursorDiskKV", "ItemTable"):
        if table not in tables:
            continue
        try:
            rows = conn.execute(f"SELECT key, value FROM {table}").fetchall()
        except sqlite3.Error:
            continue
        for key, value in rows:
            if not key:
                continue
            kv[str(key)] = value
    return kv


def _loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _collect_composers(kv: dict[str, Any]) -> dict[str, dict[str, Any]]:
    composers: dict[str, dict[str, Any]] = {}
    for key, value in kv.items():
        if not isinstance(key, str):
            continue
        if key.startswith("composerData:"):
            data = _loads(value)
            if not isinstance(data, dict):
                continue
            composer_id = str(
                data.get("composerId") or key.split(":", 1)[1]
            )
            composers[composer_id] = data
            continue
        if key == "composer.composerData":
            data = _loads(value)
            if not isinstance(data, dict):
                continue
            all_composers = data.get("allComposers")
            if isinstance(all_composers, list):
                for item in all_composers:
                    if not isinstance(item, dict):
                        continue
                    composer_id = str(item.get("composerId") or item.get("composer_id") or "")
                    if composer_id:
                        composers[composer_id] = item
    return composers


def _collect_bubbles(kv: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for key, value in kv.items():
        if not isinstance(key, str) or not key.startswith("bubbleId:"):
            continue
        parts = key.split(":", 2)
        if len(parts) < 3:
            continue
        composer_id = parts[1]
        data = _loads(value)
        if not isinstance(data, dict):
            continue
        if not data.get("bubbleId"):
            data["bubbleId"] = parts[2]
        grouped.setdefault(composer_id, []).append(data)
    for composer_id, bubbles in grouped.items():
        bubbles.sort(key=lambda b: (_bubble_sort_key(b), str(b.get("bubbleId") or "")))
    return grouped


def _bubble_sort_key(bubble: dict[str, Any]) -> str:
    created = bubble.get("createdAt") or bubble.get("timestamp") or ""
    iso = to_iso(created)
    return iso or str(created)


def _composer_to_session(
    composer_id: str,
    composer: dict[str, Any],
    bubbles: list[Any],
    *,
    project_path: str | None,
) -> dict[str, Any]:
    model = None
    model_config = composer.get("modelConfig")
    if isinstance(model_config, dict):
        model = model_config.get("modelName") or model_config.get("model")
    model = model or composer.get("model")
    started_at = to_iso(composer.get("createdAt") or composer.get("created_at"))
    turns: list[dict[str, Any]] = []
    for bubble in bubbles:
        if not isinstance(bubble, dict):
            continue
        turns.extend(_turns_from_bubble(bubble))
        if not model:
            info = bubble.get("modelInfo")
            if isinstance(info, dict):
                model = info.get("modelName") or info.get("model")
            model = model or bubble.get("model") or bubble.get("modelName")
        if not started_at:
            started_at = to_iso(bubble.get("createdAt"))
        if not project_path:
            project_path = _project_from_bubble(bubble)
    return {
        "session_id": composer_id,
        "source": "cursor",
        "started_at": started_at,
        "project_path": project_path,
        "model": model,
        "turns": turns,
    }


def _project_from_bubble(bubble: dict[str, Any]) -> str | None:
    context = bubble.get("context")
    if not isinstance(context, dict):
        return None
    for key in ("currentFile", "current_file"):
        current = context.get(key)
        if isinstance(current, dict):
            path = current.get("path") or current.get("fsPath")
            if path:
                return str(Path(str(path)).parent)
        if isinstance(current, str) and current:
            return str(Path(current).parent)
    return None


def _turns_from_bubble(bubble: dict[str, Any]) -> list[dict[str, Any]]:
    ts = to_iso(bubble.get("createdAt") or bubble.get("timestamp"))
    bubble_type = bubble.get("type")
    files = _files_from_bubble(bubble)
    text = stringify_content(bubble.get("text") or bubble.get("richText"))
    turns: list[dict[str, Any]] = []

    if bubble_type in _USER_TYPES:
        if text.strip() or files:
            turns.append(
                {
                    "role": "user",
                    "ts": ts,
                    "text": text,
                    "files": files,
                    "tool_name": None,
                    "tool_is_error": False,
                    "exit_code": None,
                    "diff_summary": None,
                }
            )
    elif bubble_type in _ASSISTANT_TYPES:
        if text.strip():
            turns.append(
                {
                    "role": "assistant",
                    "ts": ts,
                    "text": text,
                    "files": files,
                    "tool_name": None,
                    "tool_is_error": False,
                    "exit_code": None,
                    "diff_summary": _diff_summary_from_bubble(bubble),
                }
            )
        tfd = bubble.get("toolFormerData")
        if isinstance(tfd, dict) and (tfd.get("name") or tfd.get("result") or tfd.get("tool")):
            turns.append(_tool_former_turn(tfd, ts, files))
        elif isinstance(tfd, list):
            for item in tfd:
                if isinstance(item, dict):
                    turns.append(_tool_former_turn(item, ts, files))
    else:
        tfd = bubble.get("toolFormerData")
        if isinstance(tfd, dict):
            turns.append(_tool_former_turn(tfd, ts, files))
        elif text.strip():
            turns.append(
                {
                    "role": "assistant",
                    "ts": ts,
                    "text": text,
                    "files": files,
                    "tool_name": None,
                    "tool_is_error": False,
                    "exit_code": None,
                    "diff_summary": None,
                }
            )
    return turns


def _files_from_bubble(bubble: dict[str, Any]) -> list[dict[str, Any]]:
    files = files_from_mapping(bubble)
    context = bubble.get("context")
    if isinstance(context, dict):
        for key in ("fileSelections", "selections", "attachedFiles"):
            files.extend(files_from_mapping_list(context.get(key)))
        current = context.get("currentFile") or context.get("current_file")
        files.extend(files_from_mapping(current) if isinstance(current, dict) else files_from_paths(current))
    for key in ("attachedCodeChunks", "codeBlocks", "suggestedCodeBlocks"):
        files.extend(files_from_mapping_list(bubble.get(key)))
    tfd = bubble.get("toolFormerData")
    if isinstance(tfd, dict):
        params = tfd.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = None
        if isinstance(params, dict):
            files.extend(files_from_mapping(params))
    # dedupe happens in normalize
    return files


def files_from_mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return files_from_mapping(value) if isinstance(value, dict) else files_from_paths(value)
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.extend(files_from_mapping(item))
            uri = item.get("uri")
            if isinstance(uri, dict):
                out.extend(files_from_mapping(uri))
        else:
            out.extend(files_from_paths(item))
    return out


def _diff_summary_from_bubble(bubble: dict[str, Any]) -> str | None:
    diffs = bubble.get("diffHistories") or bubble.get("assistantSuggestedDiffs") or bubble.get("gitDiffs")
    if isinstance(diffs, list) and diffs:
        first = diffs[0]
        if isinstance(first, dict):
            path = first.get("path") or first.get("file") or first.get("uri")
            return f"diff {path}" if path else "diff"
        return "diff"
    return None


def _tool_former_turn(
    tfd: dict[str, Any], ts: str | None, fallback_files: list[dict[str, Any]]
) -> dict[str, Any]:
    name = tfd.get("name") or tfd.get("tool")
    if isinstance(name, int):
        name = str(name)
    result = stringify_content(tfd.get("result") or tfd.get("output"))
    params = tfd.get("params") or tfd.get("rawArgs")
    parsed_params: dict[str, Any] | None = None
    if isinstance(params, str):
        try:
            loaded = json.loads(params)
            parsed_params = loaded if isinstance(loaded, dict) else None
            if not result:
                result = params
        except json.JSONDecodeError:
            if not result:
                result = params
    elif isinstance(params, dict):
        parsed_params = params
        if not result:
            result = stringify_content(params)
    files = files_from_mapping(parsed_params) if parsed_params else []
    if not files:
        files = list(fallback_files)
    status = str(tfd.get("status") or "").lower()
    is_error = status in {"error", "failed", "failure"}
    exit_code = parse_exit_code(result, tfd.get("exit_code") or tfd.get("exitCode"))
    if not result:
        result = name or "tool"
    return {
        "role": "tool",
        "ts": ts,
        "text": result,
        "files": files,
        "tool_name": str(name) if name else None,
        "tool_is_error": looks_like_tool_error(
            result, exit_code=exit_code, is_error=is_error or None
        ),
        "exit_code": exit_code,
        "diff_summary": f"{name} {files[0]['path']}" if name and files else None,
    }
