---
id: correction-miner
name: error-connection-and-correction-miner
priority: 1
dependencies: []
estimated_hours: 4
tags: [nlp-lite, graph-prep, corrections]
---

## Objective

Turn normalized transcripts into a list of graph mutations: errors, error-to-error links, human corrections, supersession, and antipattern clusters — without talking to HydraDB.

## Context

This is the product brain. Extraction is cheap. The hackathon-hard part is **connecting** mistakes: same signature across sessions, a failed tool call that `LED_TO` a later success, a user correction that `SUPERSEDES` an older one, an antipattern that should be `FORBIDDEN_IN` a repo.

Keep mining deterministic and testable. No LLM required for v1. Optional LLM enrichment can be behind `SCAR_LLM=0` default off so demos work offline.

## Frozen input

The ingest JSON schema from `ingest-extract` TASK.md (`session_id`, `source`, `turns[]` with `tool_is_error`, `text`, `files`).

Work from `fixtures/transcripts/*.json` **copies inside this subtask** if ingest-extract is not merged yet. Keep the same filenames and the same stories:

1. Repeat mistake + explicit user ban ("do not use datetime.utcnow")
2. Tool error then successful retry
3. Later instruction contradicts an earlier one

## Frozen output

`scar/ingest/mine.py` exposes `mine_session(session: dict) -> MineResult` where `MineResult` is a dict (not a Pydantic model in `scar/models.py` — graph-core owns that file):

```json
{
  "errors": [
    {
      "id": "err_...",
      "session_id": "...",
      "turn_id": "...",
      "signature": "python|AttributeError|utcnow|path/rel.py",
      "message": "truncated error text",
      "tool": "shell or null",
      "exit_code": 1,
      "file_path": "src/foo.py",
      "symbol": "module.func or null"
    }
  ],
  "error_links": [
    {"from_id": "err_a", "type": "LED_TO", "to_id": "err_b"},
    {"from_id": "err_a", "type": "SAME_AS", "to_id": "err_c"}
  ],
  "corrections": [
    {
      "id": "cor_...",
      "kind": "human_instruction" | "human_revert" | "successful_retry" | "tool_failure_then_fix",
      "text": "do not use datetime.utcnow; use datetime.now(UTC)",
      "created_at": "ISO-8601 or null",
      "fixes_error_id": "err_...",
      "stated_in_turn_id": "...",
      "supersedes_correction_id": null
    }
  ],
  "antipatterns": [
    {
      "id": "ap_...",
      "name": "banned-utcnow",
      "description": "datetime.utcnow is banned in this repo",
      "error_ids": ["err_..."],
      "constraint_rule": "Never call datetime.utcnow; use datetime.now(timezone.utc)."
    }
  ]
}
```

## Signature rules

`signature` is a stable string used as a graph join key:

```
{language}|{error_class}|{normalized_token}|{normalized_path}
```

- `error_class`: first token that looks like `Error`, `Exception`, `FAILED`, compiler code (`E[0-9]+`, `TS[0-9]+`), or `exit:{n}`
- `normalized_token`: lowercase identifier mentioned in both the error and nearby code (e.g. `utcnow`) or `generic`
- `normalized_path`: repo-relative path, slashes, no user home
- Same signature across two errors ⇒ emit `SAME_AS`

## Correction detection (deterministic)

Apply in order, first match wins per user/assistant pair:

1. **human_instruction** — user turn matches (case-insensitive) any of: `don't`, `do not`, `never`, `stop`, `wrong`, `not that`, `we already`, `you already tried`, `don't do that again`, `instead use`, `use X not Y`. Attach to the nearest preceding assistant/tool error in the same session, else create a synthetic error from the files in that user turn.
2. **human_revert** — user or tool text mentions `revert`, `undo that`, `roll back`, or a diff that deletes the previous assistant patch (if `diff_summary` contains a reversal heuristic).
3. **tool_failure_then_fix** / **successful_retry** — a `tool_is_error=true` turn followed within 5 turns by a same-file tool turn with `tool_is_error=false`. Link `LED_TO` from the failure error to a success marker error or omit `to` error and set `fixes_error_id` on the correction.
4. **supersession** — two `human_instruction` corrections in the same `project_path` whose constraint tokens overlap (shared identifiers) but the later text contradicts (`now use`, `actually`, `ignore previous`, `updated`). Set `supersedes_correction_id` on the newer one.

## Implementation

1. `scar/ingest/signatures.py` — `error_signature(message, path, language) -> str` and `normalize_path(path, project_path)`.
2. `scar/ingest/mine.py` — `mine_session`, `mine_jsonl(path)`.
3. `scar/ingest/load_graph.py` — **adapter only**, no Hydra imports at module import time. Define `MineResult.to_upsert_calls()` as a list of dicts `{"op": "upsert_error", "kwargs": {...}}` matching `scar.graph.queries` names from graph-core. If `scar.graph` is missing, this function still returns the call list (pure data). The agent-serve / seed script will execute the ops after merge.
4. Tests covering all three fixture stories, signature stability, supersession, and "no false correction on a clean happy-path session."

## Acceptance Criteria

- [ ] Repeat-mistake fixture yields ≥1 `human_instruction` correction that `fixes` an error
- [ ] Retry-chain fixture yields `LED_TO` or `successful_retry` / `tool_failure_then_fix`
- [ ] Supersede fixture yields `supersedes_correction_id` set on the newer correction
- [ ] Happy-path session with no errors yields empty `corrections` and empty `errors`
- [ ] Signatures are identical for the same error class + path + token
- [ ] No HydraDB network calls
- [ ] `pytest tests/test_mine.py tests/test_signatures.py` pass

## Files to Create/Modify

- `scar/ingest/signatures.py`
- `scar/ingest/mine.py`
- `scar/ingest/load_graph.py`
- `fixtures/transcripts/happy_path.json` (no errors)
- `fixtures/transcripts/cursor_repeat_mistake.json` (if not already present from ingest-extract; same story)
- `fixtures/transcripts/claude_retry_chain.json`
- `fixtures/transcripts/codex_supersede.json`
- `tests/test_mine.py`
- `tests/test_signatures.py`

If ingest-extract already added the three story fixtures, **do not rewrite them incompatibly**. Add `happy_path.json` only, or skip duplicate files.

## Integration Points

- **Provides**: `mine_session`, signatures, upsert-call adapter
- **Consumes**: frozen transcript JSON (not graph-core)
- **Conflicts**: Do not edit extractors, `scar/graph/*`, `scar/models.py`, UI, or MCP server. Do not add an LLM client that is required for tests.
