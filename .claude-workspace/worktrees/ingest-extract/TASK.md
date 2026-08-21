---
id: ingest-extract
name: assistant-transcript-extractors
priority: 1
dependencies: []
estimated_hours: 3
tags: [ingest, cursor, claude-code, codex]
---

## Objective

Extract coding-agent transcripts from Cursor, Claude Code, and Codex into one frozen JSONL schema so the miner can detect corrections without caring which IDE produced the session.

## Context

Hack Hydra requires original work in this repository. Extract local Cursor / Claude Code / Codex transcripts; do not vendor another project's extractors.

Scope for the hackathon: **Cursor, Claude Code, Codex only**. Trae/Windsurf/Continue/Gemini/OpenCode are out of scope.

Privacy: extractors read local files in read-only mode. Never upload raw transcripts in tests. Redact home-directory prefixes in normalized `path` fields using `~` or a repo-relative path.

## Frozen transcript schema (you emit this; miner consumes it)

One JSON object per session, JSONL on disk. Do not add required keys without updating this table in a follow-up — optional keys are fine.

```json
{
  "session_id": "string",
  "source": "cursor" | "claude-code" | "codex",
  "started_at": "ISO-8601 or null",
  "project_path": "string or null",
  "model": "string or null",
  "turns": [
    {
      "turn_id": "string",
      "role": "user" | "assistant" | "tool",
      "ts": "ISO-8601 or null",
      "text": "string",
      "files": [{"path": "string", "language": "string or null"}],
      "tool_name": "string or null",
      "tool_is_error": false,
      "exit_code": null,
      "diff_summary": "string or null"
    }
  ]
}
```

`tool_is_error` is true when the tool result looks like a failure (nonzero exit, traceback, compiler error, test failure). Heuristics belong here so the miner can trust the flag.

## Implementation

1. `scar/ingest/extractors/claude_code.py` — scan `~/.claude/projects/**/*.jsonl` (and `~/.claude-code` if present). Parse event types for user/assistant/tool_use/tool_result. Map to the frozen schema.
2. `scar/ingest/extractors/cursor.py` — read-only SQLite (`mode=ro` URI) from:
   - macOS `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb`
   - macOS `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
   - Linux `~/.config/Cursor/...`
   Handle composer/agent keys: `composerData:`, `bubbleId:`. Best-effort; missing installs return `[]`, never crash.
3. `scar/ingest/extractors/codex.py` — `~/.codex/**/rollout-*.jsonl` session_meta / user_message / agent_message / tool_result.
4. `scar/ingest/normalize.py` — `normalize_session(raw) -> dict` enforcing the schema, assigning stable `turn_id`s if missing, collapsing empty turns.
5. `scar/ingest/cli.py` — `python -m scar.ingest path/to/out.jsonl --source all|cursor|claude-code|codex`. Writes JSONL. Does **not** talk to HydraDB.
6. `fixtures/transcripts/` — at least three **synthetic** sessions (no real user data):
   - `cursor_repeat_mistake.json` — agent applies a bad edit, tests fail, user says "do not use datetime.utcnow, we already banned that"
   - `claude_retry_chain.json` — tool error, then a successful retry on the same file
   - `codex_supersede.json` — user later contradicts an earlier instruction
7. Tests use only fixtures plus tiny in-memory sqlite if needed. Do not require Cursor to be installed.

## Acceptance Criteria

- [ ] All three extractors return `[]` on machines without that tool installed
- [ ] `normalize_session` output validates against the frozen schema (test helper)
- [ ] Synthetic fixtures round-trip through normalize
- [ ] Cursor extractor opens SQLite read-only
- [ ] CLI writes JSONL with one session per line
- [ ] Extractors are original to this repo; missing installs return `[]`
- [ ] `pytest tests/test_extract.py tests/test_normalize.py` pass

## Files to Create/Modify

- `scar/ingest/__init__.py`
- `scar/ingest/__main__.py`
- `scar/ingest/cli.py`
- `scar/ingest/normalize.py`
- `scar/ingest/extractors/__init__.py`
- `scar/ingest/extractors/claude_code.py`
- `scar/ingest/extractors/cursor.py`
- `scar/ingest/extractors/codex.py`
- `fixtures/transcripts/cursor_repeat_mistake.json`
- `fixtures/transcripts/claude_retry_chain.json`
- `fixtures/transcripts/codex_supersede.json`
- `tests/test_extract.py`
- `tests/test_normalize.py`

If `pyproject.toml` does not exist yet, create a minimal one with `[project] name = "scar"` and pytest. If graph-core already created it, **only add** ingest extras (none required beyond stdlib + pytest) — do not delete neo4j/pydantic.

## Integration Points

- **Provides**: JSONL transcript sessions in the frozen schema; `scar.ingest.normalize.normalize_session`
- **Consumes**: None (schema is frozen in this file and PARALLEL_PLAN.md)
- **Conflicts**: Do not import `scar.graph`. Do not write Cypher. Do not create MCP servers or UI. Do not edit `scar/models.py` (graph-core owns it). Miner will depend on the JSON shape, not on Python class names from this package.
