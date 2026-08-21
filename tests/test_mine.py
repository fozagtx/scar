"""Correction-miner behavior: fixtures, links, supersession, adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scar.ingest.load_graph import to_upsert_calls
from scar.ingest.mine import mine_jsonl, mine_session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_repeat_mistake_yields_human_instruction_that_fixes_error() -> None:
    result = mine_session(_load("cursor_repeat_mistake.json"))
    instructions = [c for c in result["corrections"] if c["kind"] == "human_instruction"]
    assert instructions, result["corrections"]
    error_ids = {e["id"] for e in result["errors"]}
    assert any(c.get("fixes_error_id") in error_ids for c in instructions)
    assert any("utcnow" in (e.get("signature") or "") for e in result["errors"])
    assert any(
        link["type"] == "SAME_AS" for link in result["error_links"]
    ), result["error_links"]
    assert any(ap["name"] == "banned-utcnow" for ap in result["antipatterns"])


def test_retry_chain_yields_led_to_or_successful_retry() -> None:
    result = mine_session(_load("claude_retry_chain.json"))
    kinds = {c["kind"] for c in result["corrections"]}
    has_led = any(link["type"] == "LED_TO" for link in result["error_links"])
    assert has_led or kinds & {"successful_retry", "tool_failure_then_fix"}, {
        "kinds": kinds,
        "links": result["error_links"],
    }
    retry = [
        c
        for c in result["corrections"]
        if c["kind"] in {"successful_retry", "tool_failure_then_fix"}
    ]
    if retry:
        assert retry[0]["fixes_error_id"]


def test_supersede_sets_supersedes_correction_id_on_newer() -> None:
    result = mine_session(_load("codex_supersede.json"))
    instructions = [c for c in result["corrections"] if c["kind"] == "human_instruction"]
    assert len(instructions) >= 2, result["corrections"]
    newer = instructions[-1]
    older_ids = {c["id"] for c in instructions[:-1]}
    assert newer.get("supersedes_correction_id") in older_ids
    assert instructions[0].get("supersedes_correction_id") in (None, "")


def test_happy_path_has_empty_errors_and_corrections() -> None:
    result = mine_session(_load("happy_path.json"))
    assert result["errors"] == []
    assert result["corrections"] == []
    assert result["error_links"] == []


def test_mine_is_deterministic() -> None:
    session = _load("cursor_repeat_mistake.json")
    first = mine_session(session)
    second = mine_session(session)
    assert first == second


def test_to_upsert_calls_uses_graph_core_op_names() -> None:
    result = mine_session(_load("cursor_repeat_mistake.json"))
    calls = to_upsert_calls(result)
    ops = [c["op"] for c in calls]
    assert "upsert_error" in ops
    assert "upsert_correction" in ops
    assert "upsert_file" in ops
    assert "link_same_signature" in ops
    kwargs_ok = all(isinstance(c.get("kwargs"), dict) for c in calls)
    assert kwargs_ok
    assert result.to_upsert_calls() == calls


def test_supersede_adapter_emits_supersede_correction() -> None:
    result = mine_session(_load("codex_supersede.json"))
    calls = to_upsert_calls(result)
    supersedes = [c for c in calls if c["op"] == "supersede_correction"]
    assert supersedes
    assert supersedes[0]["kwargs"]["older_id"]
    assert supersedes[0]["kwargs"]["newer_id"]
    by_id = {
        c["kwargs"]["id"]: c["kwargs"]["active"]
        for c in calls
        if c["op"] == "upsert_correction"
    }
    older = supersedes[0]["kwargs"]["older_id"]
    newer = supersedes[0]["kwargs"]["newer_id"]
    assert by_id[older] is False
    assert by_id[newer] is True


def test_mine_jsonl_reads_fixture_and_jsonl_roundtrip(tmp_path: Path) -> None:
    session = _load("happy_path.json")
    jsonl = tmp_path / "sessions.jsonl"
    jsonl.write_text(json.dumps(session) + "\n", encoding="utf-8")
    mined = mine_jsonl(jsonl)
    assert len(mined) == 1
    assert mined[0]["errors"] == []
    assert mined[0]["corrections"] == []


def test_no_hydra_or_neo4j_imports() -> None:
    import scar.ingest.load_graph as load_graph
    import scar.ingest.mine as mine
    import scar.ingest.signatures as signatures

    banned = re.compile(
        r"^\s*(?:import|from)\s+(?:neo4j|hydra|hydradb)\b",
        re.MULTILINE,
    )
    for module in (mine, signatures, load_graph):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert banned.search(source) is None, module.__name__
        assert "import openai" not in source
        assert "anthropic" not in source
