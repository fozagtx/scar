"""Extractor tests: fixtures, synthetic stores, missing installs, CLI JSONL."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scar.ingest.cli import main
from scar.ingest.extractors.claude_code import extract_claude_code
from scar.ingest.extractors.codex import extract_codex
from scar.ingest.extractors.cursor import extract_cursor
from tests.test_normalize import FIXTURES, assert_valid_session


def test_missing_installs_return_empty(tmp_path: Path) -> None:
    empty = tmp_path / "no-dotfiles"
    empty.mkdir()
    assert extract_cursor(home=empty) == []
    assert extract_claude_code(home=empty) == []
    assert extract_codex(home=empty) == []


def test_extractors_do_not_require_cursor_on_this_machine() -> None:
    """Calling with a missing home path must not raise even if Cursor is installed elsewhere."""
    missing = Path("/definitely-not-a-real-home-for-scar-tests")
    assert extract_cursor(home=missing) == []


def _write_claude_jsonl(home: Path) -> Path:
    project = home / ".claude" / "projects" / "-tmp-demo-repo"
    project.mkdir(parents=True)
    path = project / "sess-retry.jsonl"
    events = [
        {
            "type": "user",
            "sessionId": "sess-retry",
            "cwd": "/tmp/demo-repo",
            "timestamp": "2026-06-02T10:00:00Z",
            "message": {"role": "user", "content": "Fix the parse bug in src/parser.py"},
        },
        {
            "type": "assistant",
            "sessionId": "sess-retry",
            "timestamp": "2026-06-02T10:00:04Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [
                    {"type": "text", "text": "I'll patch src/parser.py."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Edit",
                        "input": {
                            "file_path": "/tmp/demo-repo/src/parser.py",
                            "old_string": "pass",
                            "new_string": "return json.loads(raw",
                        },
                    },
                ],
            },
        },
        {
            "type": "user",
            "sessionId": "sess-retry",
            "timestamp": "2026-06-02T10:00:06Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "is_error": True,
                        "content": (
                            "Traceback (most recent call last):\n"
                            "  File \"src/parser.py\", line 12\n"
                            "SyntaxError: '(' was never closed\n"
                            "FAILED tests/test_parser.py::test_parse\n"
                            "exit_code: 1"
                        ),
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "sessionId": "sess-retry",
            "timestamp": "2026-06-02T10:00:12Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Edit",
                        "input": {"file_path": "/tmp/demo-repo/src/parser.py"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "sessionId": "sess-retry",
            "timestamp": "2026-06-02T10:00:14Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "is_error": False,
                        "content": "1 passed in 0.04s\nexit_code: 0",
                    }
                ],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def test_claude_code_extracts_tool_retry(tmp_path: Path) -> None:
    _write_claude_jsonl(tmp_path)
    sessions = extract_claude_code(home=tmp_path)
    assert len(sessions) == 1
    session = sessions[0]
    assert_valid_session(session)
    assert session["source"] == "claude-code"
    assert session["session_id"] == "sess-retry"
    tool_turns = [t for t in session["turns"] if t["role"] == "tool"]
    assert any(t["tool_is_error"] for t in tool_turns)
    assert any(not t["tool_is_error"] and t["tool_name"] == "Edit" for t in tool_turns)
    assert any(
        f["path"].endswith("src/parser.py")
        for t in session["turns"]
        for f in t["files"]
    )


def test_claude_code_skips_agent_files(tmp_path: Path) -> None:
    project = tmp_path / ".claude" / "projects" / "p"
    project.mkdir(parents=True)
    (project / "agent-123.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "agent",
                "message": {"role": "user", "content": "secret"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert extract_claude_code(home=tmp_path) == []


def _write_codex_rollout(home: Path) -> Path:
    folder = home / ".codex" / "sessions" / "2026" / "06" / "03"
    folder.mkdir(parents=True)
    path = folder / "rollout-2026-06-03T09-00-00-codex-supersede.jsonl"
    events = [
        {
            "type": "session_meta",
            "timestamp": "2026-06-03T09:00:00Z",
            "payload": {
                "id": "codex-sess-1",
                "session_id": "codex-sess-1",
                "cwd": "/tmp/demo-repo",
                "timestamp": "2026-06-03T09:00:00Z",
            },
        },
        {
            "type": "turn_context",
            "timestamp": "2026-06-03T09:00:00Z",
            "payload": {"model": "gpt-5", "cwd": "/tmp/demo-repo"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-06-03T09:00:02Z",
            "payload": {
                "type": "user_message",
                "message": "do not use urllib in src/http_client.py; instead use requests",
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-06-03T09:00:08Z",
            "payload": {
                "type": "agent_message",
                "message": "Switching fetch_json to requests.",
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-06-03T09:00:09Z",
            "payload": {
                "type": "tool_result",
                "tool": "shell",
                "output": "ok",
                "exit_code": 0,
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-06-03T09:12:00Z",
            "payload": {
                "type": "user_message",
                "message": "actually ignore previous, now use httpx in src/http_client.py",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-06-03T09:12:05Z",
            "payload": {
                "type": "function_call_output",
                "call_id": "c1",
                "output": json.dumps(
                    {
                        "output": "AttributeError: boom\nexit_code: 1",
                        "exit_code": 1,
                    }
                ),
            },
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def test_codex_extracts_user_agent_tool(tmp_path: Path) -> None:
    _write_codex_rollout(tmp_path)
    sessions = extract_codex(home=tmp_path)
    assert len(sessions) == 1
    session = sessions[0]
    assert_valid_session(session)
    assert session["source"] == "codex"
    assert session["session_id"] == "codex-sess-1"
    roles = [t["role"] for t in session["turns"]]
    assert "user" in roles and "assistant" in roles and "tool" in roles
    users = [t["text"] for t in session["turns"] if t["role"] == "user"]
    assert any("do not use urllib" in t for t in users)
    assert any("ignore previous" in t and "now use httpx" in t for t in users)
    assert any(t["role"] == "tool" and t["tool_is_error"] for t in session["turns"])


def _build_cursor_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    composer = {
        "composerId": "comp-utcnow",
        "createdAt": 1717243200000,
        "modelConfig": {"modelName": "gpt-4.1"},
        "name": "utcnow helper",
    }
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        ("composerData:comp-utcnow", json.dumps(composer)),
    )
    bubbles = [
        {
            "bubbleId": "b1",
            "type": 1,
            "text": "Add a helper in src/timeutil.py",
            "createdAt": "2026-06-01T14:00:01Z",
            "context": {
                "fileSelections": [
                    {"uri": {"fsPath": "/tmp/demo-repo/src/timeutil.py"}}
                ]
            },
        },
        {
            "bubbleId": "b2",
            "type": 2,
            "text": "I'll add now() using datetime.utcnow",
            "createdAt": "2026-06-01T14:00:08Z",
        },
        {
            "bubbleId": "b3",
            "type": 2,
            "text": "",
            "createdAt": "2026-06-01T14:00:12Z",
            "toolFormerData": {
                "name": "run_terminal_command_v2",
                "status": "error",
                "params": json.dumps({"command": "pytest tests/test_timeutil.py"}),
                "result": (
                    "FAILED tests/test_timeutil.py::test_now - "
                    "AttributeError: utcnow\nexit_code: 1"
                ),
            },
        },
        {
            "bubbleId": "b4",
            "type": 1,
            "text": "do not use datetime.utcnow, we already banned that",
            "createdAt": "2026-06-01T14:00:20Z",
        },
    ]
    for bubble in bubbles:
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES (?, ?)",
            (f"bubbleId:comp-utcnow:{bubble['bubbleId']}", json.dumps(bubble)),
        )
    conn.commit()
    conn.close()


def test_cursor_extracts_from_readonly_sqlite(tmp_path: Path) -> None:
    user_root = tmp_path / "Library" / "Application Support" / "Cursor" / "User"
    db_path = user_root / "globalStorage" / "state.vscdb"
    _build_cursor_db(db_path)
    before = db_path.read_bytes()
    sessions = extract_cursor(home=tmp_path)
    after = db_path.read_bytes()
    assert before == after, "extractor must open sqlite read-only"
    assert len(sessions) == 1
    session = sessions[0]
    assert_valid_session(session)
    assert session["source"] == "cursor"
    assert session["session_id"] == "comp-utcnow"
    texts = " ".join(t["text"] for t in session["turns"])
    assert "datetime.utcnow" in texts
    assert any(t["role"] == "tool" and t["tool_is_error"] for t in session["turns"])
    assert any(
        "do not use datetime.utcnow" in t["text"] and "we already banned" in t["text"]
        for t in session["turns"]
        if t["role"] == "user"
    )


def test_cursor_linux_config_path(tmp_path: Path) -> None:
    db_path = tmp_path / ".config" / "Cursor" / "User" / "workspaceStorage" / "abc" / "state.vscdb"
    _build_cursor_db(db_path)
    (db_path.parent / "workspace.json").write_text(
        json.dumps({"folder": "file:///tmp/demo-repo"}), encoding="utf-8"
    )
    sessions = extract_cursor(home=tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["project_path"] in {"/tmp/demo-repo", "file:///tmp/demo-repo", "~/demo-repo"}


def test_cursor_source_uses_mode_ro() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scar"
        / "ingest"
        / "extractors"
        / "cursor.py"
    ).read_text(encoding="utf-8")
    assert "mode=ro" in source
    assert "mode=ro" in source.split("sqlite3.connect", 1)[1]


def test_cli_writes_one_session_per_line(tmp_path: Path) -> None:
    _write_claude_jsonl(tmp_path)
    _write_codex_rollout(tmp_path)
    out = tmp_path / "out" / "sessions.jsonl"
    rc = main([str(out), "--source", "all", "--home", str(tmp_path)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    sources = set()
    for line in lines:
        session = json.loads(line)
        assert_valid_session(session)
        sources.add(session["source"])
    assert "claude-code" in sources
    assert "codex" in sources


def test_cli_source_filter(tmp_path: Path) -> None:
    _write_claude_jsonl(tmp_path)
    _write_codex_rollout(tmp_path)
    out = tmp_path / "only-codex.jsonl"
    assert main([str(out), "--source", "codex", "--home", str(tmp_path)]) == 0
    sessions = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert sessions and all(s["source"] == "codex" for s in sessions)


def test_fixtures_are_valid_frozen_sessions() -> None:
    for name in (
        "cursor_repeat_mistake.json",
        "claude_retry_chain.json",
        "codex_supersede.json",
    ):
        session = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        assert_valid_session(session)
