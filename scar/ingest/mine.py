"""Deterministic correction miner.

Turns a frozen transcript session into errors, SAME_AS / LED_TO links,
human corrections, SUPERSEDES edges, and antipattern clusters.

No HydraDB. No LLM required (``SCAR_LLM`` defaults off).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from scar.ingest.signatures import (
    error_signature,
    infer_normalized_token,
    normalize_path,
)

# --- phrase tables (first match wins per user/assistant pair) ---------------

_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdon't\b", re.IGNORECASE),
    re.compile(r"\bdo not\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bstop\b", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"\bnot that\b", re.IGNORECASE),
    re.compile(r"\bwe already\b", re.IGNORECASE),
    re.compile(r"\byou already tried\b", re.IGNORECASE),
    re.compile(r"\bdon't do that again\b", re.IGNORECASE),
    re.compile(r"\binstead use\b", re.IGNORECASE),
    re.compile(r"\buse\s+\S+\s+not\s+\S+", re.IGNORECASE),
)

_REVERT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brevert\b", re.IGNORECASE),
    re.compile(r"\bundo that\b", re.IGNORECASE),
    re.compile(r"\broll back\b", re.IGNORECASE),
    re.compile(r"\brollback\b", re.IGNORECASE),
)

_SUPERSEDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnow use\b", re.IGNORECASE),
    re.compile(r"\bactually\b", re.IGNORECASE),
    re.compile(r"\bignore previous\b", re.IGNORECASE),
    re.compile(r"\bupdated\b", re.IGNORECASE),
)

_CONSTRAINT_STOP = frozenset(
    {
        "don't",
        "dont",
        "does",
        "doesn",
        "do",
        "not",
        "never",
        "stop",
        "wrong",
        "that",
        "this",
        "we",
        "already",
        "you",
        "tried",
        "again",
        "instead",
        "use",
        "using",
        "used",
        "please",
        "should",
        "must",
        "cannot",
        "the",
        "and",
        "or",
        "for",
        "with",
        "from",
        "now",
        "actually",
        "ignore",
        "previous",
        "updated",
        "call",
        "here",
        "there",
        "your",
        "our",
        "its",
        "let",
        "lets",
        "make",
        "sure",
        "also",
        "just",
        "like",
        "want",
        "need",
        "have",
        "been",
        "was",
        "were",
        "will",
        "can",
        "could",
        "would",
        "banned",
        "ban",
        "please",
        "thanks",
        "hello",
        "yes",
        "no",
        "ok",
        "okay",
        "time",
        "zone",
        "timezone",
    }
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
}

_RETRY_WINDOW = 5
_MESSAGE_LIMIT = 500


class MineResult(dict):
    """Dict-shaped miner output. ``to_upsert_calls`` is the graph-core adapter."""

    def to_upsert_calls(self) -> list[dict[str, Any]]:
        from scar.ingest.load_graph import to_upsert_calls

        return to_upsert_calls(self)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _truncate(text: str | None, limit: int = _MESSAGE_LIMIT) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _files(turn: dict[str, Any]) -> list[Any]:
    files = turn.get("files") or []
    return list(files) if isinstance(files, list) else []


def _file_entries(turn: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in _files(turn):
        if isinstance(item, str):
            entries.append({"path": item, "language": None})
        elif isinstance(item, dict) and item.get("path"):
            entries.append(item)
    return entries


def _file_paths(turn: dict[str, Any], project_path: str | None) -> list[str]:
    return [
        normalize_path(entry.get("path"), project_path)
        for entry in _file_entries(turn)
        if entry.get("path")
    ]


def _language_for(turn: dict[str, Any], project_path: str | None = None) -> str:
    for entry in _file_entries(turn):
        lang = entry.get("language")
        if lang:
            return str(lang).strip().lower()
    for path in _file_paths(turn, project_path):
        ext = Path(path).suffix.lower()
        if ext in _EXT_LANG:
            return _EXT_LANG[ext]
    return "unknown"


def _primary_path(turn: dict[str, Any], project_path: str | None) -> str | None:
    paths = _file_paths(turn, project_path)
    return paths[0] if paths else None


def _symbol_from(turn: dict[str, Any]) -> str | None:
    text = turn.get("text") or ""
    match = re.search(
        r"\bin\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)",
        text,
    )
    if match:
        return match.group(1)
    return None


def _matches_any(text: str | None, patterns: Iterable[re.Pattern[str]]) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in patterns)


def _is_human_instruction(text: str | None) -> bool:
    return _matches_any(text, _INSTRUCTION_PATTERNS)


def _is_revert_text(text: str | None) -> bool:
    return _matches_any(text, _REVERT_PATTERNS)


def _diff_adds_deletes(diff_summary: str | None) -> tuple[set[str], set[str]]:
    if not diff_summary:
        return set(), set()
    added = {m.group(1).strip() for m in re.finditer(r"^\+\s*(.+)$", diff_summary, re.M)}
    deleted = {m.group(1).strip() for m in re.finditer(r"^-\s*(.+)$", diff_summary, re.M)}
    added.discard("++")
    deleted.discard("--")
    return added, deleted


def _diff_is_reversal(
    diff_summary: str | None, previous_diffs: list[str]
) -> bool:
    if not diff_summary:
        return False
    if _is_revert_text(diff_summary):
        return True
    if re.search(r"\brevers(?:e|ing)\b", diff_summary, re.IGNORECASE):
        return True
    _added_now, deleted_now = _diff_adds_deletes(diff_summary)
    if not deleted_now:
        return False
    for prev in previous_diffs:
        added_prev, _deleted_prev = _diff_adds_deletes(prev)
        if added_prev and added_prev <= deleted_now:
            return True
    return False


def _constraint_tokens(text: str | None) -> set[str]:
    tokens: set[str] = set()
    for match in _IDENT.finditer(text or ""):
        token = match.group(0).lower()
        if len(token) < 3 or token in _CONSTRAINT_STOP:
            continue
        if token.endswith("error") or token.endswith("exception"):
            continue
        tokens.add(token)
    return tokens


def _contradicts(text: str | None) -> bool:
    return _matches_any(text, _SUPERSEDE_PATTERNS)


def _is_tool_turn(turn: dict[str, Any]) -> bool:
    return turn.get("role") == "tool"


def _is_failure_error(err: dict[str, Any]) -> bool:
    if err.get("exit_code") not in (None, 0):
        return True
    signature = err.get("signature") or ""
    parts = signature.split("|")
    if len(parts) > 1 and parts[1] == "exit:0":
        return False
    return err.get("exit_code") != 0


def _error_from_turn(
    session: dict[str, Any],
    turn: dict[str, Any],
    *,
    synthetic: bool = False,
    marker: str = "",
) -> dict[str, Any]:
    session_id = session.get("session_id") or ""
    project_path = session.get("project_path")
    path = _primary_path(turn, project_path)
    language = _language_for(turn, project_path)
    text = turn.get("text") or ""
    signature = error_signature(text, path, language)
    turn_id = turn.get("turn_id") or ""
    err_id = _stable_id(
        "err",
        session_id,
        turn_id,
        signature,
        marker or ("synth" if synthetic else "fail"),
    )
    exit_code = turn.get("exit_code")
    if synthetic and exit_code is None:
        exit_code = 1
    return {
        "id": err_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "signature": signature,
        "message": _truncate(text),
        "tool": turn.get("tool_name"),
        "exit_code": exit_code,
        "file_path": path,
        "symbol": _symbol_from(turn),
    }


def _nearest_preceding_error(
    errors: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    before = {t.get("turn_id") for t in turns[:index]}
    for err in reversed(errors):
        if err.get("turn_id") not in before:
            continue
        if not _is_failure_error(err):
            continue
        return err
    return None


def _correction(
    *,
    session: dict[str, Any],
    turn: dict[str, Any],
    kind: str,
    text: str,
    fixes_error_id: str | None,
) -> dict[str, Any]:
    session_id = session.get("session_id") or ""
    turn_id = turn.get("turn_id") or ""
    return {
        "id": _stable_id("cor", session_id, turn_id, kind, text),
        "kind": kind,
        "text": _truncate(text, 1000),
        "created_at": turn.get("ts"),
        "fixes_error_id": fixes_error_id,
        "stated_in_turn_id": turn_id,
        "supersedes_correction_id": None,
    }


def _antipattern_from_correction(
    session: dict[str, Any],
    cor: dict[str, Any],
    err: dict[str, Any] | None,
) -> dict[str, Any]:
    text = cor.get("text") or ""
    token = infer_normalized_token(text, err.get("file_path") if err else None)
    if token == "generic":
        tokens = sorted(_constraint_tokens(text), key=len, reverse=True)
        token = tokens[0] if tokens else "generic"
    name = f"banned-{token}"
    error_ids = [err["id"]] if err else []
    if cor.get("fixes_error_id") and cor["fixes_error_id"] not in error_ids:
        error_ids.append(cor["fixes_error_id"])
    return {
        "id": _stable_id("ap", session.get("session_id"), name, cor.get("id")),
        "name": name,
        "description": _truncate(text, 240) or f"{token} is banned in this repo",
        "error_ids": error_ids,
        "constraint_rule": text,
    }


def mine_session(session: dict[str, Any] | None) -> MineResult:
    """Detect errors, links, corrections, and antipatterns in one session."""
    session = session or {}
    turns: list[dict[str, Any]] = list(session.get("turns") or [])
    project_path = session.get("project_path")

    errors: list[dict[str, Any]] = []
    error_by_turn: dict[str, dict[str, Any]] = {}
    error_links: list[dict[str, str]] = []
    corrections: list[dict[str, Any]] = []
    classified_turns: set[str] = set()

    for turn in turns:
        if turn.get("tool_is_error"):
            err = _error_from_turn(session, turn)
            errors.append(err)
            if turn.get("turn_id"):
                error_by_turn[str(turn["turn_id"])] = err

    # SAME_AS: identical failure signatures in this session.
    by_signature: dict[str, list[dict[str, Any]]] = {}
    for err in errors:
        if not _is_failure_error(err):
            continue
        by_signature.setdefault(err["signature"], []).append(err)
    for group in by_signature.values():
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                error_links.append(
                    {"from_id": left["id"], "type": "SAME_AS", "to_id": right["id"]}
                )

    diffs_seen: list[str] = []
    for index, turn in enumerate(turns):
        turn_id = str(turn.get("turn_id") or index)
        text = turn.get("text") or ""
        diff_summary = turn.get("diff_summary")
        role = turn.get("role")

        if role == "user" and _is_human_instruction(text):
            nearest = _nearest_preceding_error(errors, turns, index)
            if nearest is None:
                nearest = _error_from_turn(session, turn, synthetic=True)
                errors.append(nearest)
                if turn.get("turn_id"):
                    error_by_turn[str(turn["turn_id"])] = nearest
            corrections.append(
                _correction(
                    session=session,
                    turn=turn,
                    kind="human_instruction",
                    text=text,
                    fixes_error_id=nearest["id"],
                )
            )
            classified_turns.add(turn_id)
        elif turn_id not in classified_turns and (
            _is_revert_text(text) or _diff_is_reversal(diff_summary, diffs_seen)
        ):
            nearest = _nearest_preceding_error(errors, turns, index)
            if nearest is None and role == "user" and _file_entries(turn):
                nearest = _error_from_turn(session, turn, synthetic=True)
                errors.append(nearest)
            corrections.append(
                _correction(
                    session=session,
                    turn=turn,
                    kind="human_revert",
                    text=text or (diff_summary or "revert"),
                    fixes_error_id=nearest["id"] if nearest else None,
                )
            )
            classified_turns.add(turn_id)

        if diff_summary:
            diffs_seen.append(str(diff_summary))

    # tool_failure_then_fix / successful_retry within 5 turns, same file.
    linked_failures: set[str] = set()
    for index, turn in enumerate(turns):
        if not turn.get("tool_is_error"):
            continue
        fail_err = error_by_turn.get(str(turn.get("turn_id") or ""))
        if fail_err is None:
            continue
        fail_files = set(_file_paths(turn, project_path))
        if not fail_files:
            continue
        window = turns[index + 1 : index + 1 + _RETRY_WINDOW]
        for later in window:
            if later.get("tool_is_error"):
                continue
            if not _is_tool_turn(later):
                continue
            later_files = set(_file_paths(later, project_path))
            if not (fail_files & later_files):
                continue
            success_err = _error_from_turn(session, later, marker="ok")
            # Success marker keeps LED_TO's to_id addressable without
            # pretending the retry failed.
            success_err["exit_code"] = (
                later.get("exit_code") if later.get("exit_code") is not None else 0
            )
            success_err["signature"] = error_signature(
                later.get("text") or "exit:0",
                success_err.get("file_path"),
                _language_for(later, project_path),
            )
            errors.append(success_err)
            error_links.append(
                {
                    "from_id": fail_err["id"],
                    "type": "LED_TO",
                    "to_id": success_err["id"],
                }
            )
            same_tool = (later.get("tool_name") or "") == (turn.get("tool_name") or "")
            kind = "successful_retry" if same_tool else "tool_failure_then_fix"
            if fail_err["id"] not in linked_failures:
                corrections.append(
                    _correction(
                        session=session,
                        turn=later,
                        kind=kind,
                        text=later.get("text") or f"{kind} on {sorted(fail_files)[0]}",
                        fixes_error_id=fail_err["id"],
                    )
                )
                linked_failures.add(fail_err["id"])
            break

    # supersession: later human_instruction contradicts an earlier one
    # with overlapping constraint tokens in the same project_path.
    human = [c for c in corrections if c["kind"] == "human_instruction"]
    for i, older in enumerate(human):
        older_tokens = _constraint_tokens(older.get("text"))
        if not older_tokens:
            continue
        for newer in human[i + 1 :]:
            if not _contradicts(newer.get("text")):
                continue
            newer_tokens = _constraint_tokens(newer.get("text"))
            if older_tokens & newer_tokens:
                newer["supersedes_correction_id"] = older["id"]

    antipatterns: list[dict[str, Any]] = []
    seen_ap: set[str] = set()
    errors_by_id = {e["id"]: e for e in errors}
    for cor in corrections:
        if cor["kind"] != "human_instruction":
            continue
        err = errors_by_id.get(cor.get("fixes_error_id") or "")
        antipattern = _antipattern_from_correction(session, cor, err)
        if antipattern["name"] in seen_ap:
            existing = next(a for a in antipatterns if a["name"] == antipattern["name"])
            for eid in antipattern["error_ids"]:
                if eid not in existing["error_ids"]:
                    existing["error_ids"].append(eid)
            continue
        seen_ap.add(antipattern["name"])
        antipatterns.append(antipattern)

    return MineResult(
        {
            "errors": errors,
            "error_links": error_links,
            "corrections": corrections,
            "antipatterns": antipatterns,
        }
    )


def _load_sessions(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        sessions: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, list):
                sessions.extend(obj)
            else:
                sessions.append(obj)
        return sessions
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj
    return [obj]


def mine_jsonl(path: str | Path) -> list[MineResult]:
    """Mine each JSON object in a JSONL file (``.json`` single session also ok)."""
    target = Path(path)
    if target.is_dir():
        files = sorted(target.glob("*.jsonl")) + sorted(target.glob("*.json"))
        sessions: list[dict[str, Any]] = []
        for file_path in files:
            sessions.extend(_load_sessions(file_path))
        return [mine_session(session) for session in sessions]
    return [mine_session(session) for session in _load_sessions(target)]
