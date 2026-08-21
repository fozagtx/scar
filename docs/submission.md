# Hack Hydra submission form — paste

Copy these answers into the official form. Deadline: August 20, 2026, 11:59 PM PT.

## Project name

SCAR (Stored Corrections And Recall)

## Short project description

A HydraDB correction graph for coding agents. SCAR stores human corrections and error connections from Cursor / Claude Code / Codex so the next session does not repeat the same mistake, and abstains when it has never seen the context.

## Problem being addressed

IDE assistants retrieve code by embedding similarity. Similarity cannot represent "we banned this", "this error led to that fix", "this file imports the module that already failed", or "the old rule was overwritten." Agents therefore recommit the same bug. Track 2B: code graphs for IDE assistants.

## What you built

- HydraDB OSS ontology: Repo, File, Symbol, Session, Turn, Error, Correction, AntiPattern, with `FIXES`, `LED_TO`, `SAME_AS`, `CALLS`, `IMPORTS`, `SUPERSEDES`.
- Extractors for Cursor, Claude Code, and Codex local session stores.
- Deterministic miner: error signatures, retry chains, human instructions, supersession.
- `scar` CLI, HTTP `:8765`, MCP tools `scar_recall` / `scar_record` / `scar_blast_radius`.
- Workstation demo UI on `:7331` that shows recall hits, blast radius, superseded corrections, and abstain.

## Deployed project link

Local demo: `http://127.0.0.1:7331/` after `python scripts/demo_api.py`.
No hosted deploy required if the repo runs from README.

## How the project uses the HydraDB Open Source Repo

Runs `ghcr.io/hydra-db/hydradb:latest` via `docker-compose.yml` (`graph-node`, Bolt 7687, HTTP 8443). All writes and recalls go through OpenCypher in `scar/graph/queries.py` (`recall_for_context`, `blast_radius` as `IMPORTS*`). HydraDB Cloud is not used. Details: `HYDRA.md`.

## Tech stack

Python 3.11, HydraDB OSS (Docker), neo4j Bolt driver, httpx, Pydantic, pytest, vanilla HTML/CSS/JS demo UI.

## Team members and individual contributions

Fill with real names before submit. Work was split across parallel branches: graph-core, ingest-extract, correction-miner, agent-serve, dashboard-demo, hackathon-pack.

## GitHub repository link

Public repo URL (create and push this tree; no commits before August 12, 2026).

## 3-minute demo video link

YouTube (unlisted is fine). Follow `docs/demo-script.md`.
