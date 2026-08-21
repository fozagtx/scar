# SCAR

Stored Corrections And Recall. A HydraDB graph of coding-agent errors, human corrections, and the connections between them so the next session does not repeat the same mistake.

Hack Hydra track **2B** (code graphs for IDE assistants). HydraDB OSS is the system of record; details in [HYDRA.md](HYDRA.md).

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![HydraDB](https://img.shields.io/badge/HydraDB-OSS_graph--node-111827?style=flat-square)](https://github.com/hydra-db/hydradb)
[![Bolt](https://img.shields.io/badge/Bolt-5.x-018BFF?style=flat-square&logo=neo4j&logoColor=white)](https://neo4j.com/docs/bolt/)
[![OpenCypher](https://img.shields.io/badge/OpenCypher-HTTP-E34F26?style=flat-square)](https://github.com/hydra-db/hydradb)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square)](https://docs.pydantic.dev/)
[![MCP](https://img.shields.io/badge/MCP-stdio-111111?style=flat-square)](https://modelcontextprotocol.io/)
[![pytest](https://img.shields.io/badge/pytest-8-0A9B5A?style=flat-square&logo=pytest&logoColor=white)](https://docs.pytest.org/)

## Features

- Extract local Cursor, Claude Code, and Codex sessions into one JSONL schema
- Mine error signatures, retry chains (`LED_TO`), and corrections (`FIXES`, `SUPERSEDES`)
- Store the graph in HydraDB OSS (`graph-node` over Bolt/HTTP)
- Recall active corrections for a file/symbol/error; **abstain** when nothing matches
- Blast radius over `IMPORTS*` — which files sit downstream of a failure
- CLI, HTTP (`:8765`), MCP tools, and a no-build demo UI (`:7331`)

## Graph

HydraDB stores this ontology. Recall walks the current file, then `IMPORTS` / `CALLS` neighbors, then error signature. Only an active correction that does not sit behind `SUPERSEDES` is returned. No path → abstain.

```mermaid
flowchart LR
  subgraph session["Session"]
    Session:::sess
    Turn:::sess
    Session -->|HAS_TURN| Turn
  end

  subgraph code["Code graph"]
    Importer["src/api.py"]:::file
    FileN["src/timeutil.py"]:::file
    Symbol["timeutil.now"]:::sym
    Callee["datetime"]:::sym
    Importer -->|IMPORTS| FileN
    FileN --- Symbol
    Symbol -->|CALLS| Callee
  end

  subgraph scars["Corrections"]
    Fail["utcnow AttributeError"]:::error
    Retry["retry"]:::error
    Live["use datetime.now UTC"]:::corr
    Dead["superseded"]:::dead
    AP["banned-utcnow"]:::ap
    Fail -->|LED_TO| Retry
    Fail -->|SAME_AS| Retry
    Live -->|FIXES| Fail
    Live -->|SUPERSEDES| Dead
    Fail -->|INSTANCE_OF| AP
  end

  Session -->|IN_REPO| Repo:::sess
  Turn -->|TOUCHED| FileN
  Turn -->|EMITTED| Fail
  Fail -->|IN_FILE| FileN
  Fail -->|ON_SYMBOL| Symbol
  Live -->|STATED_IN| Turn
  AP -->|FORBIDDEN_IN| Repo

  classDef file fill:#6ec8e8,stroke:#2c2c26,color:#10100e
  classDef error fill:#ff5d4c,stroke:#2c2c26,color:#10100e
  classDef corr fill:#d6ff3f,stroke:#2c2c26,color:#14150a
  classDef sym fill:#e0a84a,stroke:#2c2c26,color:#10100e
  classDef ap fill:#d989c8,stroke:#2c2c26,color:#10100e
  classDef dead fill:#6a675c,stroke:#2c2c26,color:#e4dfd2
  classDef sess fill:#1a1a16,stroke:#6ec8e8,color:#e4dfd2
```

Legend: cyan File, gold Symbol, red Error, acid Correction, mauve AntiPattern, grey superseded. Same palette as the demo UI.

`blast_radius` is `(:File)-[:IMPORTS*]->(:File)<-[:IN_FILE]-(:Error {signature})`. A vector index cannot answer that.

## Prerequisites

- Python 3.11+
- Docker, only if you want a live HydraDB node (the demo UI runs without it)

## Getting started

Fixture demo (no HydraDB):

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python scripts/demo_api.py
```

Open http://127.0.0.1:7331/ . Graph in the center, superseded corrections struck through. Click path: `bash scripts/record_demo.sh`.

Live graph:

```bash
./scripts/init-hydradb-data.sh
UID=$(id -u) GID=$(id -g) docker compose up
```

Wait for `:9090` `/readyz`, then:

```bash
.venv/bin/python scripts/seed_fixture_graph.py
.venv/bin/scar recall --repo demo-repo --file src/timeutil.py --error "AttributeError utcnow"
.venv/bin/scar abstain-check --repo demo-repo --file src/unrelated.py
```

Tests:

```bash
.venv/bin/pytest
```

## Usage

Ingest assistant history, then query or record:

```bash
.venv/bin/python -m scar.ingest extracted.jsonl --source all
.venv/bin/scar ingest extracted.jsonl --repo demo-repo

.venv/bin/scar recall --repo demo-repo --file src/timeutil.py --error "AttributeError utcnow"
.venv/bin/scar record --repo demo-repo --file src/timeutil.py --correction "never use datetime.utcnow"
```

| Command | What it does |
|---|---|
| `scar ingest <jsonl> --repo <id>` | Mine JSONL and upsert into HydraDB |
| `scar recall --repo --file [--error] [--symbol]` | Print active corrections or abstain |
| `scar record --repo --file --correction` | Write a human correction now |
| `scar abstain-check --repo --file` | Exit 0 only if recall abstains |
| `scar serve` | HTTP API on `127.0.0.1:8765` |
| `scar mcp` | MCP stdio (`scar_recall`, `scar_record`, `scar_blast_radius`) |

MCP config: [integrations/mcp.json.example](integrations/mcp.json.example). Cursor rule / Claude skill: [integrations/cursor-rule.mdc](integrations/cursor-rule.mdc), [integrations/claude-skill.md](integrations/claude-skill.md).

Recall walks the current file, then `CALLS` / `IMPORTS` neighbors, then error signature. It keeps only `active` corrections that are not the target of `SUPERSEDES`. Empty neighborhood → abstain, never invent a house rule.

```text
local sessions  →  extract  →  mine  →  HydraDB OSS
                                         ├─ scar CLI / MCP / HTTP :8765
                                         └─ demo UI :7331 (fixture or SCAR_LIVE=1)
```

## Configuration

Copy `.env.example`. Compose reads `UID`/`GID` and the token file from `./scripts/init-hydradb-data.sh`.

| Variable | Default | Used by |
|---|---|---|
| `HYDRA_BOLT_URI` | `bolt://127.0.0.1:7687` | Graph client |
| `HYDRA_HTTP_URI` | `http://127.0.0.1:8443` | HTTP Cypher fallback |
| `HYDRA_AUTH_TOKEN` | token file / local-dev token | Bolt and HTTP |
| `HYDRA_ADMIN_URI` | `http://127.0.0.1:9090` | Readiness |
| `SCAR_LIVE` | unset | Demo UI: try live `recall_for_context` |
| `SCAR_DEMO_PORT` | `7331` | Demo UI bind port |

Image: `ghcr.io/hydra-db/hydradb:latest`. SCAR does not call `api.hydradb.com`. Cypher lives only in `scar/graph/queries.py`. File-by-file map: [HYDRA.md](HYDRA.md).

## Troubleshooting

**Demo UI is enough for the graph argument.** Fixture mode on `:7331` does not need Docker.

**`docker compose up` cannot write the store.** The image runs as UID 10001; bind mounts are host-owned. Always pass `UID=$(id -u) GID=$(id -g)` (or let `.env` set them after `init-hydradb-data.sh`).

**Live `scar recall` fails with connection errors.** `graph-node` is not up. Check `curl -sS http://127.0.0.1:9090/readyz` and `HYDRA_BOLT_URI`.

**Extractors print nothing.** Missing Cursor / Claude Code / Codex installs return `[]`. That is expected.

**Port clash.** Agent HTTP is `:8765` (`scar serve`). Demo UI is `:7331`. HydraDB is `7687` / `8443` / `9090`.
