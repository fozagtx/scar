"""Tests for frozen-schema normalization and the three miner fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scar.ingest.normalize import (
    looks_like_tool_error,
    normalize_session,
    redact_path,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"

SESSION_KEYS = {
    "session_id",
    "source",
    "started_at",
    "project_path",
    "model",
    "turns",
}
TURN_KEYS = {
    "turn_id",
    "role",
    "ts",
    "text",
    "files",
    "tool_name",
    "tool_is_error",
    "exit_code",
    "diff_summary",
}
SOURCES = {"cursor", "claude-code", "codex"}
ROLES = {"user", "assistant", "tool"}


def assert_valid_session(session: dict) -> None:
    """Schema validator helper used by extract tests as well."""
    assert isinstance(session, dict)
    assert SESSION_KEYS <= set(session.keys())
    assert session["source"] in SOURCES
    assert isinstance(session["session_id"], str) and session["session_id"]
    assert session["started_at"] is None or isinstance(session["started_at"], str)
    assert session["project_path"] is None or isinstance(session["project_path"], str)
    assert session["model"] is None or isinstance(session["model"], str)
    assert isinstance(session["turns"], list)
    seen_ids: set[str] = set()
    for turn in session["turns"]:
        assert TURN_KEYS <= set(turn.keys())
        assert turn["role"] in ROLES
        assert isinstance(turn["turn_id"], str) and turn["turn_id"]
        assert turn["turn_id"] not in seen_ids
        seen_ids.add(turn["turn_id"])
        assert turn["ts"] is None or isinstance(turn["ts"], str)
        assert isinstance(turn["text"], str)
        assert isinstance(turn["tool_is_error"], bool)
        assert turn["exit_code"] is None or isinstance(turn["exit_code"], int)
        assert turn["tool_name"] is None or isinstance(turn["tool_name"], str)
        assert turn["diff_summary"] is None or isinstance(turn["diff_summary"], str)
        assert isinstance(turn["files"], list)
        for entry in turn["files"]:
            assert isinstance(entry, dict)
            assert "path" in entry and isinstance(entry["path"], str)
            assert "language" in entry
            assert entry["language"] is None or isinstance(entry["language"], str)
            assert not entry["path"].startswith("/Users/")
            assert not entry["path"].startswith("/home/")


@pytest.mark.parametrize(
    "name",
    [
        "cursor_repeat_mistake.json",
        "claude_retry_chain.json",
        "codex_supersede.json",
    ],
)
def test_fixtures_round_trip_normalize(name: str) -> None:
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    out = normalize_session(raw)
    assert_valid_session(out)
    assert out["session_id"] == raw["session_id"]
    assert out["source"] == raw["source"]
    assert len(out["turns"]) == len(raw["turns"])
    again = normalize_session(out)
    assert again == out


def test_cursor_repeat_mistake_story() -> None:
    session = normalize_session(
        json.loads((FIXTURES / "cursor_repeat_mistake.json").read_text())
    )
    texts = " ".join(t["text"] for t in session["turns"])
    assert "datetime.utcnow" in texts
    assert any(t["role"] == "tool" and t["tool_is_error"] for t in session["turns"])
    user = [t for t in session["turns"] if t["role"] == "user"][-1]
    assert "do not use datetime.utcnow" in user["text"]
    assert "we already banned that" in user["text"]
    assert any(
        f["path"].endswith("src/timeutil.py")
        for t in session["turns"]
        for f in t["files"]
    )


def test_claude_retry_chain_story() -> None:
    session = normalize_session(
        json.loads((FIXTURES / "claude_retry_chain.json").read_text())
    )
    tool_turns = [t for t in session["turns"] if t["role"] == "tool"]
    errors = [t for t in tool_turns if t["tool_is_error"]]
    successes = [t for t in tool_turns if not t["tool_is_error"]]
    assert errors, "retry chain needs a failing tool turn"
    assert successes, "retry chain needs a later successful tool turn"
    fail_files = {f["path"] for f in errors[0]["files"]}
    later = [
        t
        for t in tool_turns
        if (not t["tool_is_error"])
        and t["ts"] >= errors[0]["ts"]
        and fail_files & {f["path"] for f in t["files"]}
    ]
    assert later, "same file must succeed after the error"
    assert "src/parser.py" in fail_files or any(
        p.endswith("src/parser.py") for p in fail_files
    )


def test_codex_supersede_story() -> None:
    session = normalize_session(
        json.loads((FIXTURES / "codex_supersede.json").read_text())
    )
    users = [t["text"] for t in session["turns"] if t["role"] == "user"]
    assert len(users) >= 2
    assert "do not use" in users[0] or "instead use" in users[0]
    later = users[-1].lower()
    assert "actually" in later
    assert "ignore previous" in later
    assert "now use" in later


def test_stable_turn_ids_assigned_when_missing() -> None:
    raw = {
        "session_id": "s-missing-ids",
        "source": "cursor",
        "started_at": "2026-01-01T00:00:00Z",
        "project_path": None,
        "model": None,
        "turns": [
            {"role": "user", "text": "hello"},
            {"role": "assistant", "text": "world"},
        ],
    }
    out = normalize_session(raw)
    assert out["turns"][0]["turn_id"] == "s-missing-ids:t0000"
    assert out["turns"][1]["turn_id"] == "s-missing-ids:t0001"


def test_drops_empty_turns() -> None:
    raw = {
        "session_id": "s-empty",
        "source": "codex",
        "started_at": None,
        "project_path": None,
        "model": None,
        "turns": [
            {"role": "user", "text": "   "},
            {"role": "assistant", "text": "kept"},
            {"role": "tool", "text": "", "tool_name": None, "files": []},
        ],
    }
    out = normalize_session(raw)
    assert [t["text"] for t in out["turns"]] == ["kept"]
    assert_valid_session(out)


def test_redacts_home_directory_in_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/Users/kaizen")
    raw = {
        "session_id": "s-home",
        "source": "claude-code",
        "started_at": "2026-01-01T00:00:00Z",
        "project_path": "/Users/kaizen/work/demo",
        "model": None,
        "turns": [
            {
                "role": "user",
                "text": "open this",
                "files": [
                    {"path": "/Users/kaizen/work/demo/src/timeutil.py", "language": None}
                ],
            }
        ],
    }
    out = normalize_session(raw)
    assert out["project_path"] == "~/work/demo"
    assert out["turns"][0]["files"][0]["path"] == "~/work/demo/src/timeutil.py"
    assert out["turns"][0]["files"][0]["language"] == "python"
    assert redact_path("/Users/anyone/secret") == "~/secret"


def test_tool_error_heuristics() -> None:
    assert looks_like_tool_error("Traceback (most recent call last):")
    assert looks_like_tool_error("FAILED tests/test_timeutil.py")
    assert looks_like_tool_error("AttributeError: utcnow")
    assert looks_like_tool_error("error TS2304: Cannot find name")
    assert looks_like_tool_error("boom", exit_code=1)
    assert looks_like_tool_error("ok", is_error=True)
    assert not looks_like_tool_error("all tests passed", exit_code=0)


def test_invalid_source_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_session({"session_id": "x", "source": "windsurf", "turns": []})


def test_started_at_falls_back_to_first_turn() -> None:
    out = normalize_session(
        {
            "session_id": "s",
            "source": "cursor",
            "turns": [{"role": "user", "text": "hi", "ts": "2026-02-02T02:02:02Z"}],
        }
    )
    assert out["started_at"] == "2026-02-02T02:02:02Z"
