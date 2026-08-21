---
id: hackathon-pack
name: submission-readme-license-hydra-usage
priority: 3
dependencies: [graph-core, ingest-extract, correction-miner, agent-serve, dashboard-demo]
estimated_hours: 2
tags: [docs, hackathon, license]
---

## Objective

Make the repo judge-ready for Hack Hydra: public-repo README, license, HydraDB usage explanation, setup that actually runs, attribution, and a demo-video shot list.

## Context

Deadline: **August 20, 2026, 11:59 PM PT**. Submission needs (1) form (2) ≤3 minute video (3) public GitHub repo with:

- Complete source
- No participant-authored commits before August 12, 2026
- Clear README
- Setup and run instructions
- How HydraDB is used
- Env/dependency info
- Attribution for third-party code
- Open-source license

HydraDB OSS is AGPL-3.0. SCAR should be **Apache-2.0 or MIT** and treat HydraDB as a runtime dependency via Docker, not a vendored copy of the HydraDB source.

Track to enter: **Track 2 — Repos, Dependencies + Code as Graphs / option B: Code graphs for IDE assistants.** Also mention Track 3 memory behaviors (supersession, chronology, abstention) in the README as capabilities, but do not dual-enter the same repo.

Attribute only runtime dependencies in the README and NOTICE (HydraDB, neo4j, httpx, Pydantic). Do not name other products as sources.

## Implementation

1. `LICENSE` — MIT.
2. `README.md` — the only top-level README. Sections in this order:
   - One-line pitch
   - Problem (agents repeat mistakes; embeddings miss connections)
   - Demo GIF/screenshot placeholder path `docs/demo.png` (dashboard-demo or you capture)
   - Graph model diagram (mermaid)
   - Why HydraDB (named Cypher queries, blast radius, supersession) — a paragraph a judge can quote
   - Quick start: docker compose, seed, UI, CLI recall, MCP snippet
   - How HydraDB OSS is used (ports, image, what breaks if you replace it with SQLite)
   - Architecture
   - Extractor attribution
   - Track, team, license
3. `HYDRA.md` — file-by-file map of HydraDB calls (`scar/graph/client.py`, `queries.py`, docker-compose). This is the "be ready to say where it is used" rule.
4. `NOTICE` — third-party runtime deps: HydraDB, neo4j driver, httpx, Pydantic.
5. `docs/demo-script.md` — 3-minute video narration, timed, matching `scripts/record_demo.sh`.
6. `docs/submission.md` — paste-ready answers for the Hack Hydra form (project name SCAR, problem, what you built, how HydraDB OSS is used, tech stack).
7. `.env.example` — if missing.
8. Do not rewrite other teams' code. Fix broken links in README only after merge.

## Acceptance Criteria

- [ ] `LICENSE` present
- [ ] README explains HydraDB as load-bearing, with a concrete query that SQLite-without-graph would not express as cleanly
- [ ] HYDRA.md lists every Hydra touchpoint
- [ ] HydraDB attributed as the graph runtime
- [ ] Quick start has copy-paste commands
- [ ] Demo script is ≤3:00
- [ ] submission.md filled
- [ ] No secrets in git

## Files to Create/Modify

- `LICENSE`
- `README.md`
- `HYDRA.md`
- `NOTICE`
- `docs/demo-script.md`
- `docs/submission.md`
- `.env.example` (if missing)
- `docs/demo.png` (optional screenshot)

## Integration Points

- **Provides**: judge-facing docs and license
- **Consumes**: all other subtasks (paths, command names)
- **Conflicts**: You own `README.md`. Do not refactor Python. If compose flags differ from graph-core, document reality rather than inventing flags.
