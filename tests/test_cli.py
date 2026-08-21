"""CLI: argparse help, recall/record/ingest/abstain-check against FakeGraph."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scar.cli import build_parser, main
from scar.graph import queries
from scar.serve.prompt import ABSTAIN_MESSAGE

ROOT = Path(__file__).resolve().parents[1]


class FakeGraph:
    """Empty query client: recall_for_context abstains."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        self.calls.append((cypher, dict(params or {})))
        return []


def _seed_hit(client) -> None:
    queries.upsert_repo(client, id="demo-repo", root="/tmp/demo-repo", language="python")
    queries.upsert_file(
        client,
        id="file:src/timeutil.py",
        path="src/timeutil.py",
        language="python",
        repo_id="demo-repo",
    )
    queries.upsert_error(
        client,
        id="err:utcnow-attr",
        signature="python|AttributeError|utcnow|src/timeutil.py",
        message="AttributeError utcnow",
        file_id="file:src/timeutil.py",
        repo_id="demo-repo",
    )
    queries.upsert_correction(
        client,
        id="cor:utcnow-ban",
        kind="human_instruction",
        text="never use datetime.utcnow; use datetime.now(timezone.utc)",
        created_at="2024-06-01T10:01:00Z",
        active=True,
        fixes_error_id="err:utcnow-attr",
    )


def test_argparse_help_lists_commands(capsys) -> None:
    text = build_parser().format_help()
    assert "ingest" in text
    assert "recall" in text
    assert "record" in text
    assert "abstain-check" in text
    with pytest.raises(SystemExit) as exited:
        main(["--help"])
    assert exited.value.code == 0
    with pytest.raises(SystemExit) as recall_help:
        main(["recall", "--help"])
    assert recall_help.value.code == 0
    recall_text = capsys.readouterr().out
    assert "--repo" in recall_text
    assert "--file" in recall_text
    assert "--symbol" in recall_text
    assert "--error" in recall_text
    assert "--task" in recall_text


def test_recall_empty_fake_graph_prints_abstain(capsys) -> None:
    rc = main(
        ["recall", "--repo", "demo-repo", "--file", "/no/such.py"],
        client=FakeGraph(),
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == ABSTAIN_MESSAGE


def test_recall_hit_list_prints_correction_not_session_dump(fake_client, capsys) -> None:
    _seed_hit(fake_client)
    rc = main(
        [
            "recall",
            "--repo",
            "demo-repo",
            "--file",
            "src/timeutil.py",
            "--error",
            "AttributeError utcnow",
        ],
        client=fake_client,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "never use datetime.utcnow; use datetime.now(timezone.utc)" in out
    assert "python|AttributeError|utcnow|src/timeutil.py" in out
    assert "session dump" not in out
    assert ABSTAIN_MESSAGE not in out


def test_record_creates_upsert_correction(fake_client, monkeypatch) -> None:
    seen: list[dict] = []
    real = queries.upsert_correction

    def spy(client, **kwargs):
        seen.append(kwargs)
        return real(client, **kwargs)

    monkeypatch.setattr(queries, "upsert_correction", spy)
    rc = main(
        [
            "record",
            "--repo",
            "demo-repo",
            "--file",
            "src/timeutil.py",
            "--correction",
            "never use datetime.utcnow",
            "--error",
            "AttributeError utcnow",
        ],
        client=fake_client,
    )
    assert rc == 0
    assert seen
    assert seen[0]["kind"] == "human_instruction"
    assert seen[0]["text"] == "never use datetime.utcnow"
    assert seen[0]["active"] is True
    corrections = [
        node
        for node in fake_client.nodes.values()
        if "Correction" in node.get("_labels", set())
    ]
    assert corrections
    assert any("utcnow" in (node.get("text") or "") for node in corrections)


def test_abstain_check_exit_codes(fake_client) -> None:
    empty = main(
        ["abstain-check", "--repo", "demo-repo", "--file", "/no/such.py"],
        client=FakeGraph(),
    )
    assert empty == 0
    _seed_hit(fake_client)
    hits = main(
        ["abstain-check", "--repo", "demo-repo", "--file", "src/timeutil.py"],
        client=fake_client,
    )
    assert hits == 1


def test_ingest_mines_and_upserts(fake_client, tmp_path, capsys) -> None:
    session = {
        "session_id": "s1",
        "source": "cursor",
        "started_at": "2024-01-01T00:00:00Z",
        "project_path": "/tmp/demo-repo",
        "turns": [
            {
                "turn_id": "t1",
                "role": "tool",
                "ts": "2024-01-01T00:00:00Z",
                "text": "AttributeError: type object 'datetime.datetime' has no attribute 'utcnow'",
                "tool_name": "shell",
                "tool_is_error": True,
                "exit_code": 1,
                "files": [{"path": "src/timeutil.py", "language": "python"}],
            },
            {
                "turn_id": "t2",
                "role": "user",
                "ts": "2024-01-01T00:00:01Z",
                "text": "don't use datetime.utcnow; use datetime.now(timezone.utc)",
                "files": [{"path": "src/timeutil.py", "language": "python"}],
            },
        ],
    }
    jsonl = tmp_path / "sessions.jsonl"
    jsonl.write_text(json.dumps(session) + "\n", encoding="utf-8")
    rc = main(["ingest", str(jsonl), "--repo", "demo-repo"], client=fake_client)
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingested" in out
    corrections = [
        node
        for node in fake_client.nodes.values()
        if "Correction" in node.get("_labels", set())
    ]
    assert corrections


def test_ingest_missing_file_is_clear(tmp_path) -> None:
    rc = main(
        ["ingest", str(tmp_path / "missing.jsonl"), "--repo", "demo-repo"],
        client=FakeGraph(),
    )
    assert rc == 2


def test_pyproject_console_script_keeps_existing_deps() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'scar = "scar.cli:main"' in text
    assert 'scar-ingest = "scar.ingest.cli:main"' in text
    assert "neo4j" in text
    assert "pydantic" in text
    assert "httpx" in text


def test_module_entrypoint_exports_main() -> None:
    import scar.__main__ as mod

    assert callable(mod.main)
