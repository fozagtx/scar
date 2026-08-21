---
target_branch: main
merge_order: [graph-core, ingest-extract, correction-miner, agent-serve, dashboard-demo, hackathon-pack]
created: 2026-08-20
---

# Merge Plan

## Merge Order (Dependency-Based)

Execute merges in this order to respect dependencies:

1. **graph-core** (`parallel/graph-core-hydradb-ontology`) — No dependencies. Lands Docker, client, ontology, `scar/models.py`, `pyproject.toml`, `fixtures/demo_graph.json`.
2. **ingest-extract** (`parallel/ingest-extract-transcripts`) — No dependencies. Lands extractors and transcript fixtures. Union `pyproject.toml` if both created one.
3. **correction-miner** (`parallel/correction-miner-error-links`) — No code dependency on 1–2. If transcript fixtures conflict, keep ingest-extract files and miner’s `happy_path.json`.
4. **agent-serve** (`parallel/agent-serve-recall-mcp`) — Depends on graph-core and correction-miner. Wire `scar ingest` to `mine_jsonl` + query upserts.
5. **dashboard-demo** (`parallel/dashboard-demo-ui`) — Depends on graph-core fixture. Point the UI at live `/v1/recall` when agent-serve is merged.
6. **hackathon-pack** (`parallel/hackathon-pack-docs`) — Docs last so command names match reality.

## Merge Commands

```bash
git checkout main
git pull origin main 2>/dev/null || true

# Wave 1
git merge --no-ff parallel/graph-core-hydradb-ontology -m "Merge graph-core: HydraDB ontology and client"
git merge --no-ff parallel/ingest-extract-transcripts -m "Merge ingest-extract: Cursor Claude Codex extractors"
git merge --no-ff parallel/correction-miner-error-links -m "Merge correction-miner: error links and corrections"

# Wave 2
git merge --no-ff parallel/agent-serve-recall-mcp -m "Merge agent-serve: CLI MCP HTTP recall"
git merge --no-ff parallel/dashboard-demo-ui -m "Merge dashboard-demo: scar graph UI"

# Wave 3
git merge --no-ff parallel/hackathon-pack-docs -m "Merge hackathon-pack: README license submission docs"

# Verify
python -m pytest
```

Live check after tests (optional but required before the video):

```bash
docker compose up -d
python scripts/seed_fixture_graph.py
python -m scar recall --repo demo-repo --file src/timeutil.py --error "AttributeError utcnow"
python scripts/demo_api.py
```

## Conflict Resolution

If conflicts occur, resolve in dependency order and verify tests pass after each merge.

| File | Winner |
|---|---|
| `pyproject.toml` | Union. Keep neo4j, pydantic, pytest, console script `scar` |
| `scar/models.py` | graph-core only |
| `scar/graph/queries.py` | graph-core only |
| `fixtures/demo_graph.json` | graph-core |
| `fixtures/transcripts/cursor_repeat_mistake.json` (and sibling stories) | ingest-extract |
| `README.md` | hackathon-pack |
| `docker-compose.yml` | graph-core |

## Post-Merge Verification

- [ ] All tests pass
- [ ] `docker compose up` + seed + recall returns a real correction on the demo file
- [ ] Recall on an unrelated file abstains
- [ ] UI shows FIXES and SUPERSEDES
- [ ] MCP example file matches running tool names
- [ ] README HydraDB section matches compose ports
- [ ] LICENSE and NOTICE present
- [ ] No `.env` or auth-token committed
- [ ] Demo script fits 3 minutes
