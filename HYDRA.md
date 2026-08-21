# How SCAR uses HydraDB OSS

Hack Hydra rule: HydraDB has to do real work, not sit in the README.
The system of record is **HydraDB OSS `graph-node`**, image
`ghcr.io/hydra-db/hydradb:latest`, not `api.hydradb.com`.

If you replace HydraDB with a single SQLite table of "lessons", you lose
`CALLS` / `IMPORTS*` neighborhood recall, `SUPERSEDES` as an edge, and
`blast_radius` as a traversal. Those are the product.

## Runtime

| Port | Role |
|---|---|
| `7687` | Bolt (neo4j driver) — primary Cypher |
| `8443` | HTTP OpenCypher JSON/NDJSON — fallback |
| `9090` | Admin `/readyz` |

Bring-up (from repo root):

```bash
./scripts/init-hydradb-data.sh
UID=$(id -u) GID=$(id -g) docker compose up
```

Env (see `.env.example`): `HYDRA_BOLT_URI`, `HYDRA_HTTP_URI`, `HYDRA_AUTH_TOKEN`,
optional `HYDRA_ADMIN_URI`. Local token file is gitignored
`hydradb-data/auth-token` with value `local-development-token-32-bytes`.

The demo UI on `:7331` reads HydraDB (`GET /graph`, live `recall_for_context`). Extract local sessions and ingest them before opening it.

## File-by-file map

| File | What it does with HydraDB |
|---|---|
| `docker-compose.yml` | Starts one plaintext `graph-node`. OSS flags: `CLOUD_PROVIDER=local`, `GRAPH_ALLOW_PLAINTEXT=true`, `RUST_MIN_STACK=33554432`. |
| `scripts/init-hydradb-data.sh` | Creates store/cache dirs and the auth token file compose mounts. |
| `scar/graph/client.py` | `GraphClient.query(cypher, params)`. Bolt first via `neo4j`, HTTP fallback via `httpx`. Token from env or token file. `hydra_is_ready()` hits `:9090`. |
| `scar/graph/schema.py` | MERGE-on-`id` convention (OpenCypher subset may not have unique constraints). |
| `scar/graph/queries.py` | **Only file that contains Cypher.** Named ops: `upsert_repo/file/symbol/session/turn/error/correction`, `link_same_signature`, `link_call`, `link_import`, `link_led_to`, `supersede_correction`, `recall_for_context`, `blast_radius`, `export_graph`. |
| `scar/models.py` | Pydantic shapes for graph labels. Not a second database. |
| `scar/cli.py` | `scar ingest/recall/record` call `queries.py` through `scar.serve`. |
| `scar/serve/http_api.py` | `POST /v1/recall` and `/v1/record` on `:8765` against the same client. |
| `scar/serve/mcp_server.py` | MCP tools `scar_recall`, `scar_record`, `scar_blast_radius`. |
| `scar/ingest/load_graph.py` | Emits `{op, kwargs}` matching query names. Does **not** import Hydra at module import time. |
| `scripts/demo_api.py` | UI on `:7331`. `GET /graph` is `export_graph`. Recall/blast hit HydraDB. No fixture fallback. |

## Queries a row store does not express cleanly

`recall_for_context` walks:

1. Errors on the current file
2. Errors on files in the `IMPORTS` neighborhood (1–2 hops, live blast uses `IMPORTS*1..8`)
3. Errors on symbols in the `CALLS` neighborhood
4. Signature match against `error_text`
5. Corrections with `active = true` that are not the target of `SUPERSEDES`

`blast_radius(error_id)`:

```cypher
MATCH (same:Error {signature: $signature})-[:IN_FILE]->(origin:File)
MATCH (importer:File)-[:IMPORTS*1..8]->(origin)
RETURN importer.path
```

That is a transitive reverse-import closure over a failure signature. Embedding
search over chunks cannot answer it.

## What we deliberately do not use

- HydraDB Cloud `https://api.hydradb.com`
- `hydradb-sdk` / `@hydradb/sdk`
- Vector recall as the system of record
