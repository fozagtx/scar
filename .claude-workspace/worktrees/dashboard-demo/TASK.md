---
id: dashboard-demo
name: scar-graph-demo-ui
priority: 2
dependencies: [graph-core]
estimated_hours: 3
tags: [frontend, demo, visualization]
---

## Objective

Ship a local demo UI that makes the graph argument visible: nodes are files, errors, and corrections; edges are `FIXES`, `LED_TO`, `CALLS`, `SUPERSEDES`; the recall panel shows hits or an explicit abstain.

## Context

Judges have three minutes. They will not read Cypher. The UI has to show why HydraDB matters: click an error, see the blast radius through `IMPORTS`/`CALLS`, see an old correction greyed out because a newer one `SUPERSEDES` it.

Stack: **single static HTML file plus a tiny Python static+proxy server** so we do not fight React/Next lockfiles across worktrees. Use vanilla HTML/CSS/JS in `ui/`. Talk to `POST /v1/recall` if agent-serve is present; otherwise call `scripts/demo_api.py` in this subtask that reads `fixtures/demo_graph.json` and returns the same JSON shape as graph-core recall (`hits`, `abstain`, `reason`).

Visual direction: dense workstation, not a SaaS landing page. Dark background, one accent (amber or acid green), monospace for signatures, no hero gradient, no generic card grid of "features." The main view is the graph. Typography: IBM Plex Mono or JetBrains Mono via a system-font stack if offline.

## Implementation

1. `ui/index.html` — three panes:
   - Left: session/repo list from demo fixture (hardcoded demo repo `demo-repo`)
   - Center: SVG or canvas graph (use vis-network via CDN **or** a hand-rolled SVG — prefer no build step). Node types color-coded: File, Error, Correction, Symbol, AntiPattern.
   - Right: recall inspector. Inputs: file path, error text. Button: Recall. Output: formatted scars or abstain. Second button: Blast radius.
2. `ui/styles.css` — layout, no purple-on-white AI aesthetic.
3. `ui/graph.js` — render demo_graph.json; highlight path on recall.
4. `scripts/demo_api.py` — `python scripts/demo_api.py` serves `ui/` on `127.0.0.1:7331` and:
   - `GET /fixture` → demo_graph.json
   - `POST /v1/recall` → if `SCAR_LIVE=1`, proxy to graph-core queries; else filter the fixture in-process with the **same abstain rules** (active only, newest supersession, neighborhood via CALLS/IMPORTS in the fixture).
5. Extend `fixtures/demo_graph.json` **only if graph-core has not created it**. If it exists, consume it. If you must add demo-only view metadata, put it in `fixtures/demo_ui_layout.json` (positions), never fork a second ontology.
6. `scripts/record_demo.sh` — prints a 60-second click path for the video (open UI, show repeat mistake, recall hits, show superseded correction greyed, show abstain on unrelated file).

## Acceptance Criteria

- [ ] `python scripts/demo_api.py` serves the UI without Node
- [ ] Graph shows at least File, Error, Correction nodes and FIXES / SUPERSEDES / CALLS or IMPORTS edges
- [ ] Recalling the banned-utcnow file shows the instruction correction
- [ ] Recalling an unrelated path shows abstain, not a random scar
- [ ] Superseded correction is visually distinct (grey, struck, or labeled `superseded`)
- [ ] Works offline except optional CDN; if CDN is used, document a fallback
- [ ] No edits to `scar/graph/queries.py` or extractors

## Files to Create/Modify

- `ui/index.html`
- `ui/styles.css`
- `ui/graph.js`
- `ui/app.js`
- `scripts/demo_api.py`
- `scripts/record_demo.sh`
- `fixtures/demo_ui_layout.json` (optional)
- `fixtures/demo_graph.json` (only if missing)

## Integration Points

- **Provides**: demo UI, local demo server, video click path
- **Consumes**: `fixtures/demo_graph.json` shape from graph-core; optional live `/v1/recall` from agent-serve
- **Conflicts**: Do not write `README.md`. Do not add npm/Next. Do not change ontology labels.
