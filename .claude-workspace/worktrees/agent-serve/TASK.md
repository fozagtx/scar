---
id: agent-serve
name: recall-mcp-and-cli
priority: 2
dependencies: [graph-core, correction-miner]
estimated_hours: 3
tags: [mcp, cli, agents, http]
---

## Objective

Give coding agents a way to **query SCAR before they edit** and a way to **record a new scar after they get corrected**, via CLI, a small HTTP API, and an MCP server.

## Context

Track 2B is "the missing piece for editor wrappers." Similarity search over repos is the status quo; SCAR serves **connected** context: prior errors on this symbol, corrections on callees, blast radius of an antipattern, and honest abstention.

This subtask assumes graph-core's `scar.graph.queries.recall_for_context` and `upsert_*` exist after merge. Until then, implement against the function names in graph-core TASK.md and keep a `FakeGraph` in tests.

## Implementation

1. `scar/serve/prompt.py` — `format_recall(result) -> str` used as a system/user injection. Must include:
   - If `abstain`: `SCAR has no stored correction for this context. Do not invent a house rule.`
   - Else: numbered scars with `correction.text`, `error.signature`, file/symbol, whether neighborhood was via `CALLS` or `IMPORTS`, and `active` only.
   - Never dump full transcripts.
2. `scar/cli.py` — commands:
   - `scar ingest <jsonl>` — mine + execute upsert ops (calls `mine_jsonl` then graph queries). If miner or graph is missing, fail with a clear message.
   - `scar recall --repo <id> --file <path> [--symbol NAME] [--error TEXT] [--task TEXT]` — prints `format_recall`.
   - `scar record --repo <id> --file <path> --correction TEXT [--error TEXT]` — writes a `human_instruction` correction now (manual capture when the user just yelled at the agent).
   - `scar abstain-check --repo <id> --file /no/such.py` — exits 0 only if abstain is true (demo/test helper).
3. `scar/serve/http_api.py` — stdlib `http.server` or FastAPI **only if already in pyproject**. Prefer stdlib to avoid dep fights:
   - `POST /v1/recall` JSON body `{repo_id, file_path, symbol, error_text, task_text}`
   - `POST /v1/record` JSON body `{repo_id, file_path, correction_text, error_text}`
   - `GET /healthz`
4. `scar/serve/mcp_server.py` — MCP stdio server with tools:
   - `scar_recall` (same args as HTTP)
   - `scar_record`
   - `scar_blast_radius` (`error_id` or `signature`)
   Use the official MCP Python SDK if adding a dependency is necessary; otherwise a minimal JSON-RPC stdio loop. Document the Claude Desktop / Cursor mcp.json snippet in `integrations/mcp.json.example` (not README.md).
5. `integrations/cursor-rule.mdc` — a Cursor rule: "Before applying a non-trivial edit, call scar_recall with the current file and the error/task. If SCAR returns hits, obey active corrections. If it abstains, proceed normally."
6. `integrations/claude-skill.md` — same instruction for Claude Code skills.
7. Tests: FakeGraph covering prompt formatting, abstain text, HTTP handler with unittest.mock, CLI argparse help.

## Acceptance Criteria

- [ ] `scar recall` on empty fake graph prints the abstain sentence verbatim
- [ ] `scar recall` on a hit list prints correction text and signature, not raw session dumps
- [ ] `POST /v1/recall` returns JSON `{hits, abstain, reason}`
- [ ] `scar_record` creates an upsert_correction op
- [ ] MCP tool list includes `scar_recall`, `scar_record`, `scar_blast_radius`
- [ ] Cursor rule and Claude skill files exist
- [ ] `pytest tests/test_serve.py tests/test_cli.py tests/test_prompt.py` pass without a live HydraDB node

## Files to Create/Modify

- `scar/cli.py`
- `scar/__main__.py` - `python -m scar`
- `scar/serve/__init__.py`
- `scar/serve/prompt.py`
- `scar/serve/http_api.py`
- `scar/serve/mcp_server.py`
- `integrations/mcp.json.example`
- `integrations/cursor-rule.mdc`
- `integrations/claude-skill.md`
- `tests/test_serve.py`
- `tests/test_cli.py`
- `tests/test_prompt.py`

Do not create top-level `README.md`. Do not create `docker-compose.yml`. Do not edit extractors or `queries.py`. You may add a console_scripts entry in `pyproject.toml` (`scar = "scar.cli:main"`) without removing existing deps.

## Integration Points

- **Provides**: CLI, HTTP, MCP, agent instruction files, prompt formatter
- **Consumes**: `scar.graph.queries`, `scar.ingest.mine.mine_jsonl`, `scar.ingest.load_graph`
- **Conflicts**: Avoid `ui/`. Avoid `schema/`. Avoid extractor files.
