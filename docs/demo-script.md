# SCAR demo video — 3:00 or less

Record the UI at http://127.0.0.1:7331/ (fixture mode is enough for the graph
argument). Optional cutaway: terminal with `scar recall` against a live node.

Prereq:

```bash
python scripts/demo_api.py
# optional live: ./scripts/init-hydradb-data.sh && docker compose up
#               python scripts/seed_fixture_graph.py
```

60-second click path is also printed by `bash scripts/record_demo.sh`.

## Timed narration

**0:00–0:20 — Problem**

Agents repeat mistakes. You already told Cursor not to use `datetime.utcnow`.
The next session embeds the repo and does it again. Embeddings treat "use utcnow"
and "never use utcnow" as near neighbors. That is the bug.

**0:20–0:40 — What we built**

SCAR stores corrections and error connections in HydraDB OSS. Not a vector
index of chat logs. A graph: files, symbols, errors, corrections, `FIXES`,
`IMPORTS`, `CALLS`, `SUPERSEDES`.

**0:40–1:20 — Graph (judge must see this)**

Open http://127.0.0.1:7331/

- Mast: SCAR / demo-repo / FIXTURE. Three panes. The graph is the stage.
- Left: session `demo-utcnow`. Files: `timeutil.py` has a scar; `unrelated.py` abstains.
- Center: `src/api.py --IMPORTS--> src/timeutil.py`. Error `utcnow-attr --FIXES--> cor:utcnow-ban`.
- Point at `cor:old-utcnow`: grey, struck, badge `superseded`. Edge `SUPERSEDES` from the live ban.
  Say: a vector store would retrieve both.

**1:20–1:50 — Recall hit**

Right pane: file `src/timeutil.py`, error `AttributeError utcnow`. Click **Recall** (or R).

Hit: "never use datetime.utcnow; use datetime.now(timezone.utc)" via file.
The old utcnow instruction is not in the hit list.

**1:50–2:15 — Blast radius**

Click **Blast radius** (or B). `src/api.py` lights up (`IMPORTS*`). `unrelated.py` stays dark.
This is the IDE-assistant question: if this failure repeats, which files are exposed.

**2:15–2:40 — Abstain**

Click `src/unrelated.py`. Recall.

On screen: `SCAR has no stored correction for this context. Do not invent a house rule.`

Long-context agents fail here by inventing. SCAR stops.

**2:40–3:00 — HydraDB + how to hook an agent**

HydraDB OSS `graph-node` is the store (Bolt 7687). Cypher lives in `scar/graph/queries.py`.
Agents call `scar recall` / MCP `scar_recall` before they edit, `scar record` after a human correction.

Cut. Do not exceed 3:00.

## Fallback curls (if the UI cannot be screen-recorded)

```bash
curl -sS -X POST http://127.0.0.1:7331/v1/recall \
  -H 'Content-Type: application/json' \
  -d '{"repo_id":"demo-repo","file_path":"src/timeutil.py","error_text":"AttributeError utcnow"}'

curl -sS -X POST http://127.0.0.1:7331/v1/recall \
  -H 'Content-Type: application/json' \
  -d '{"repo_id":"demo-repo","file_path":"src/unrelated.py"}'

curl -sS -X POST http://127.0.0.1:7331/v1/blast \
  -H 'Content-Type: application/json' \
  -d '{"error_id":"err:utcnow-attr"}'
```
