"""HTTP + MCP serve tests. FakeGraph / mock client; no live Hydra required."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scar.graph import queries
from scar.serve.http_api import handle_request
from scar.serve.mcp_server import call_tool, handle_rpc, list_tools
from scar.serve.prompt import ABSTAIN_MESSAGE

INTEGRATION_FILES = (
    "integrations/mcp.json.example",
    "integrations/cursor-rule.mdc",
    "integrations/claude-skill.md",
    "integrations/claude.mcp.json.example",
    "integrations/codex.toml.example",
    "integrations/hermes.yaml.example",
    "integrations/openclaw.json.example",
    "integrations/README.md",
)

AGENTS = ("Cursor", "Claude Code", "Codex", "Hermes", "OpenClaw")
MCP_TOOLS = ("scar_recall", "scar_record", "scar_blast_radius")


class FakeGraph:
    """Empty query client used for abstain paths."""

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


def test_healthz() -> None:
    status, content_type, body = handle_request("GET", "/healthz", None, FakeGraph())
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body) == {"ok": True}


def test_post_v1_recall_returns_hits_abstain_reason() -> None:
    canned = {
        "hits": [],
        "abstain": True,
        "reason": ABSTAIN_MESSAGE,
    }
    with patch("scar.graph.queries.recall_for_context", return_value=canned) as mocked:
        status, content_type, body = handle_request(
            "POST",
            "/v1/recall",
            json.dumps({"repo_id": "demo-repo", "file_path": "/no/such.py"}).encode(),
            client=MagicMock(),
        )
    assert status == 200
    assert content_type == "application/json"
    payload = json.loads(body)
    assert payload["hits"] == []
    assert payload["abstain"] is True
    assert payload["reason"] == ABSTAIN_MESSAGE
    mocked.assert_called_once()


def test_post_v1_recall_on_empty_graph_abstains() -> None:
    status, _ctype, body = handle_request(
        "POST",
        "/v1/recall",
        json.dumps({"repo_id": "demo-repo", "file_path": "/no/such.py"}).encode(),
        client=FakeGraph(),
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["hits"] == []
    assert payload["abstain"] is True
    assert "invent" in payload["reason"].lower() or "no stored correction" in payload["reason"].lower()


def test_post_v1_recall_on_hits(fake_client) -> None:
    _seed_hit(fake_client)
    status, _ctype, body = handle_request(
        "POST",
        "/v1/recall",
        json.dumps(
            {
                "repo_id": "demo-repo",
                "file_path": "src/timeutil.py",
                "error_text": "AttributeError utcnow",
            }
        ).encode(),
        client=fake_client,
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["abstain"] is False
    assert payload["hits"]
    assert "hits" in payload and "abstain" in payload and "reason" in payload
    assert any("utcnow" in hit["correction"]["text"] for hit in payload["hits"])


def test_post_v1_record_upserts_correction(fake_client, monkeypatch) -> None:
    seen: list[dict] = []
    real = queries.upsert_correction

    def spy(client, **kwargs):
        seen.append(kwargs)
        return real(client, **kwargs)

    monkeypatch.setattr(queries, "upsert_correction", spy)
    status, _ctype, body = handle_request(
        "POST",
        "/v1/record",
        json.dumps(
            {
                "repo_id": "demo-repo",
                "file_path": "src/timeutil.py",
                "correction_text": "never use datetime.utcnow",
                "error_text": "AttributeError utcnow",
            }
        ).encode(),
        client=fake_client,
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["kind"] == "human_instruction"
    assert seen
    assert seen[0]["kind"] == "human_instruction"


def test_http_recall_missing_fields_is_400() -> None:
    status, _ctype, body = handle_request(
        "POST", "/v1/recall", b"{}", client=FakeGraph()
    )
    assert status == 400
    assert "repo_id" in json.loads(body)["error"]


def test_mcp_tool_list_includes_required_tools() -> None:
    names = {tool["name"] for tool in list_tools()}
    assert names == {"scar_recall", "scar_record", "scar_blast_radius"}
    rpc = handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        FakeGraph(),
    )
    assert rpc is not None
    listed = {tool["name"] for tool in rpc["result"]["tools"]}
    assert listed == names


def test_mcp_scar_recall_abstains_on_empty_graph() -> None:
    result = call_tool(
        "scar_recall",
        {"repo_id": "demo-repo", "file_path": "/no/such.py"},
        FakeGraph(),
    )
    assert result["content"][0]["text"] == ABSTAIN_MESSAGE


def test_mcp_scar_record_creates_upsert_correction(fake_client, monkeypatch) -> None:
    seen: list[dict] = []
    real = queries.upsert_correction

    def spy(client, **kwargs):
        seen.append(kwargs)
        return real(client, **kwargs)

    monkeypatch.setattr(queries, "upsert_correction", spy)
    result = call_tool(
        "scar_record",
        {
            "repo_id": "demo-repo",
            "file_path": "src/timeutil.py",
            "correction_text": "never use datetime.utcnow",
        },
        fake_client,
    )
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert seen
    assert seen[0]["kind"] == "human_instruction"


def test_mcp_scar_blast_radius(fake_client) -> None:
    _seed_hit(fake_client)
    queries.upsert_file(
        fake_client,
        id="file:src/api.py",
        path="src/api.py",
        language="python",
        repo_id="demo-repo",
    )
    queries.link_import(
        fake_client,
        from_id="file:src/api.py",
        to_id="file:src/timeutil.py",
    )
    result = call_tool(
        "scar_blast_radius",
        {"error_id": "err:utcnow-attr"},
        fake_client,
    )
    payload = json.loads(result["content"][0]["text"])
    assert payload["error_id"] == "err:utcnow-attr"
    assert "files" in payload


def test_integration_instruction_files_exist() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in INTEGRATION_FILES:
        path = root / rel
        assert path.is_file(), rel
    rule = (root / "integrations/cursor-rule.mdc").read_text(encoding="utf-8")
    assert "scar_recall" in rule
    assert "If SCAR returns hits, obey active corrections" in rule
    assert "If it abstains, proceed normally" in rule
    skill = (root / "integrations/claude-skill.md").read_text(encoding="utf-8")
    assert "scar_recall" in skill
    mcp = json.loads((root / "integrations/mcp.json.example").read_text(encoding="utf-8"))
    assert "scar" in mcp["mcpServers"]
    args = mcp["mcpServers"]["scar"]["args"]
    assert "scar.serve.mcp_server" in " ".join(args)
    claude_mcp = json.loads(
        (root / "integrations/claude.mcp.json.example").read_text(encoding="utf-8")
    )
    assert claude_mcp["mcpServers"]["scar"]["args"] == ["-m", "scar.serve.mcp_server"]
    codex = (root / "integrations/codex.toml.example").read_text(encoding="utf-8")
    assert "[mcp_servers.scar]" in codex
    hermes = (root / "integrations/hermes.yaml.example").read_text(encoding="utf-8")
    assert "mcp_servers:" in hermes and "scar:" in hermes
    openclaw = json.loads(
        (root / "integrations/openclaw.json.example").read_text(encoding="utf-8")
    )
    assert openclaw["mcp"]["servers"]["scar"]["args"] == ["-m", "scar.serve.mcp_server"]


def test_readme_showcases_cli_mcp_http_and_five_agents() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    src = (root / "scar/serve/mcp_server.py").read_text(encoding="utf-8")
    for agent in AGENTS:
        assert agent in readme, agent
    for tool in MCP_TOOLS:
        assert tool in readme, tool
    assert "scar recall" in readme
    assert "scar record" in readme
    assert "scar serve" in readme
    assert "POST /v1/recall" in readme
    assert "POST /v1/record" in readme
    assert "python -m scar.serve.mcp_server" in readme
    assert "scar recall --repo --file" not in readme
    assert "mcp>=" not in pyproject
    assert '"mcp"' not in pyproject
    assert "from mcp" not in src
    assert "import mcp" not in src
    toc_headings = (
        "## Table of contents",
        "## The problem",
        "## Why it is different",
        "## The graph",
        "## Verify it yourself in 60 seconds",
        "## Five agents",
        "## Architecture",
        "## Requirements",
        "## Install",
        "## Record and recall",
        "## Commands",
        "## MCP tools (stdio)",
        "## HTTP",
        "## What's real vs simplified",
        "## Engineering decisions",
        "## Layout",
        "## Troubleshooting",
        "## License",
    )
    for heading in toc_headings:
        assert heading in readme, heading
    assert "[The problem](#the-problem)" in readme
    assert "[What's real vs simplified](#whats-real-vs-simplified)" in readme
