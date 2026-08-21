"""Unit and optional live tests for named HydraDB graph operations."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest

from scar.graph.queries import (
    blast_radius,
    link_call,
    link_import,
    recall_for_context,
    supersede_correction,
    upsert_correction,
    upsert_error,
    upsert_file,
    upsert_repo,
    upsert_symbol,
)
from scar.models import Correction, CorrectionKind, Error, FileNode, Repo, Symbol

ROOT = Path(__file__).resolve().parents[1]


def _seed_graph():
    path = ROOT / "scripts" / "seed_fixture_graph.py"
    spec = importlib.util.spec_from_file_location("seed_fixture_graph", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module.seed_graph


def _seed_utcnow(client) -> None:
    upsert_repo(client, id="demo-repo", root="/tmp/demo-repo", language="python")
    upsert_file(
        client,
        id="file:src/timeutil.py",
        path="src/timeutil.py",
        language="python",
        repo_id="demo-repo",
    )
    upsert_file(
        client,
        id="file:src/api.py",
        path="src/api.py",
        language="python",
        repo_id="demo-repo",
    )
    upsert_file(
        client,
        id="file:src/unrelated.py",
        path="src/unrelated.py",
        language="python",
        repo_id="demo-repo",
    )
    upsert_symbol(
        client,
        id="sym:timeutil.now",
        qualified_name="timeutil.now",
        kind="function",
        file_id="file:src/timeutil.py",
    )
    upsert_symbol(client, id="sym:datetime", qualified_name="datetime", kind="module")
    link_call(client, from_id="sym:timeutil.now", to_id="sym:datetime")
    link_import(client, from_id="file:src/api.py", to_id="file:src/timeutil.py")
    upsert_error(
        client,
        id="err:utcnow-attr",
        signature="python|AttributeError|utcnow|src/timeutil.py",
        message="AttributeError: type object 'datetime.datetime' has no attribute 'utcnow'",
        tool="shell",
        exit_code=1,
        file_id="file:src/timeutil.py",
        symbol_id="sym:timeutil.now",
        repo_id="demo-repo",
    )
    upsert_correction(
        client,
        id="cor:old-utcnow",
        kind="human_instruction",
        text="use datetime.utcnow for naive UTC timestamps",
        created_at="2024-01-01T00:00:00Z",
        active=True,
        fixes_error_id="err:utcnow-attr",
    )
    upsert_correction(
        client,
        id="cor:utcnow-ban",
        kind="human_instruction",
        text="never use datetime.utcnow; use datetime.now(timezone.utc)",
        created_at="2024-06-01T10:01:00Z",
        active=True,
        fixes_error_id="err:utcnow-attr",
    )
    supersede_correction(client, newer_id="cor:utcnow-ban", older_id="cor:old-utcnow")


def test_models_match_frozen_contract() -> None:
    repo = Repo(id="demo-repo", root="/tmp/demo-repo", language="python")
    file_node = FileNode(id="file:src/timeutil.py", path="src/timeutil.py", language="python")
    symbol = Symbol(id="sym:timeutil.now", qualified_name="timeutil.now", kind="function")
    error = Error(
        id="err:x",
        signature="python|AttributeError|utcnow|src/timeutil.py",
        message="boom",
        tool="shell",
        exit_code=1,
    )
    correction = Correction(
        id="cor:x",
        kind=CorrectionKind.human_instruction,
        text="never use datetime.utcnow; use datetime.now(timezone.utc)",
        created_at="2024-06-01T10:01:00Z",
        active=True,
    )
    assert repo.language == "python"
    assert file_node.path.endswith("timeutil.py")
    assert symbol.kind == "function"
    assert error.signature.startswith("python|")
    assert correction.kind is CorrectionKind.human_instruction


def test_upsert_error_cypher_shape(fake_client) -> None:
    upsert_error(
        fake_client,
        id="err:shape",
        signature="python|AttributeError|utcnow|src/timeutil.py",
        message="AttributeError utcnow",
        tool="shell",
        exit_code=1,
    )
    cypher, params = fake_client.calls[0]
    assert "MERGE" in cypher
    assert ":Error" in cypher
    assert params["id"] == "err:shape"
    assert params["signature"].endswith("src/timeutil.py")


def test_round_trip_write_and_recall(fake_client) -> None:
    _seed_utcnow(fake_client)
    result = recall_for_context(
        fake_client,
        "demo-repo",
        "src/timeutil.py",
        symbol="timeutil.now",
        error_text="AttributeError utcnow",
    )
    assert result["abstain"] is False
    texts = [hit["correction"]["text"] for hit in result["hits"]]
    assert "never use datetime.utcnow; use datetime.now(timezone.utc)" in texts
    assert all(hit["active"] is True for hit in result["hits"])
    assert all(hit["correction"]["active"] is True for hit in result["hits"])


def test_supersession_hides_old_correction(fake_client) -> None:
    _seed_utcnow(fake_client)
    result = recall_for_context(
        fake_client,
        "demo-repo",
        "src/timeutil.py",
        error_text="AttributeError utcnow",
    )
    texts = [hit["correction"]["text"] for hit in result["hits"]]
    assert "use datetime.utcnow for naive UTC timestamps" not in texts
    ids = [hit["correction"]["id"] for hit in result["hits"]]
    assert "cor:old-utcnow" not in ids
    assert "cor:utcnow-ban" in ids


def test_neighborhood_recall_via_calls(fake_client) -> None:
    upsert_repo(fake_client, id="calls-repo", root="/tmp/calls", language="python")
    upsert_file(
        fake_client,
        id="file:src/caller.py",
        path="src/caller.py",
        language="python",
        repo_id="calls-repo",
    )
    upsert_file(
        fake_client,
        id="file:src/callee.py",
        path="src/callee.py",
        language="python",
        repo_id="calls-repo",
    )
    upsert_symbol(fake_client, id="sym:caller.fn", qualified_name="caller.fn", kind="function")
    upsert_symbol(fake_client, id="sym:callee.fn", qualified_name="callee.fn", kind="function")
    link_call(fake_client, from_id="sym:caller.fn", to_id="sym:callee.fn")
    upsert_error(
        fake_client,
        id="err:callee",
        signature="python|TypeError|boom|src/callee.py",
        message="TypeError boom",
        file_id="file:src/callee.py",
        symbol_id="sym:callee.fn",
        repo_id="calls-repo",
    )
    upsert_correction(
        fake_client,
        id="cor:callee",
        kind="human_instruction",
        text="callee.fn must not be passed a None",
        created_at="2024-02-02T00:00:00Z",
        active=True,
        fixes_error_id="err:callee",
    )
    result = recall_for_context(
        fake_client,
        "calls-repo",
        "src/caller.py",
        symbol="caller.fn",
        error_text="",
    )
    assert result["abstain"] is False
    assert any(hit["via"] == "CALLS" for hit in result["hits"])
    assert result["hits"][0]["correction"]["text"] == "callee.fn must not be passed a None"
    cypher_blob = " ".join(c for c, _p in fake_client.calls)
    assert "CALLS" in cypher_blob


def test_abstain_when_no_matching_scar(fake_client) -> None:
    _seed_utcnow(fake_client)
    result = recall_for_context(
        fake_client,
        "demo-repo",
        "src/unrelated.py",
        symbol=None,
        error_text="some unrelated failure",
    )
    assert result["hits"] == []
    assert result["abstain"] is True
    assert "invent" in result["reason"].lower() or "no stored correction" in result["reason"].lower()


def test_blast_radius_follows_imports(fake_client) -> None:
    _seed_utcnow(fake_client)
    radius = blast_radius(fake_client, "err:utcnow-attr")
    assert radius["signature"] == "python|AttributeError|utcnow|src/timeutil.py"
    assert "src/timeutil.py" in radius["origin_files"]
    assert "src/api.py" in radius["files"]
    assert "src/unrelated.py" not in radius["files"]
    cypher_blob = " ".join(c for c, _p in fake_client.calls)
    assert "IMPORTS" in cypher_blob


def test_demo_fixture_seed_round_trip(fake_client) -> None:
    payload = json.loads((ROOT / "fixtures" / "demo_graph.json").read_text(encoding="utf-8"))
    _seed_graph()(fake_client, payload)
    hit = recall_for_context(
        fake_client,
        "demo-repo",
        "src/api.py",
        error_text="AttributeError utcnow",
    )
    assert hit["abstain"] is False
    assert any("timezone.utc" in row["correction"]["text"] for row in hit["hits"])
    silent = recall_for_context(fake_client, "demo-repo", "src/unrelated.py")
    assert silent["abstain"] is True


def test_miner_kwargs_upsert_error(fake_client) -> None:
    upsert_error(
        fake_client,
        id="err:miner",
        signature="python|AttributeError|utcnow|src/timeutil.py",
        message="AttributeError utcnow",
        tool="shell",
        exit_code=1,
        session_id=None,
        turn_id=None,
        file_path="src/timeutil.py",
        symbol="timeutil.now",
    )
    labels = fake_client.nodes["err:miner"]["_labels"]
    assert "Error" in labels
    assert "file:src/timeutil.py" in fake_client.nodes


@pytest.mark.integration
def test_live_round_trip(live_client) -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = f"test-repo-{suffix}"
    file_id = f"file:src/live_{suffix}.py"
    path = f"src/live_{suffix}.py"
    error_id = f"err:live-{suffix}"
    correction_id = f"cor:live-{suffix}"
    signature = f"python|AttributeError|utcnow|{path}"
    upsert_repo(live_client, id=repo_id, root="/tmp/live", language="python")
    upsert_file(live_client, id=file_id, path=path, language="python", repo_id=repo_id)
    upsert_error(
        live_client,
        id=error_id,
        signature=signature,
        message="AttributeError utcnow",
        tool="shell",
        exit_code=1,
        file_id=file_id,
        repo_id=repo_id,
    )
    upsert_correction(
        live_client,
        id=correction_id,
        kind="human_instruction",
        text="never use datetime.utcnow; use datetime.now(timezone.utc)",
        created_at="2024-06-01T10:01:00Z",
        active=True,
        fixes_error_id=error_id,
    )
    result = recall_for_context(
        live_client,
        repo_id,
        path,
        error_text="AttributeError utcnow",
    )
    assert result["abstain"] is False
    assert any("timezone.utc" in hit["correction"]["text"] for hit in result["hits"])
    silent = recall_for_context(live_client, repo_id, "src/no-such-file.py")
    assert silent["abstain"] is True
    radius = blast_radius(live_client, error_id)
    assert path in radius["origin_files"]
