---
id: graph-core
name: hydradb-ontology-and-client
priority: 1
dependencies: []
estimated_hours: 3
tags: [backend, hydradb, ontology, docker]
---

## Objective

Stand up HydraDB OSS locally and own the correction-graph ontology plus the Python Bolt/HTTP client that every other subtask writes through.

## Context

Hack Hydra requires HydraDB OSS (`github.com/hydra-db/hydradb`) to do real work, not sit in the README. SCAR's product claim is that **error connections are a graph problem**: a vector index cannot answer "what corrections live on the callers of this function" or "which files import a module that already failed with this signature." This subtask is the load-bearing HydraDB usage.

Do **not** use the managed `api.hydradb.com` / `hydradb-sdk` cloud product as the system of record. That is a different product. The hackathon judges clone `hydra-db/hydradb` and expect Bolt or HTTPS OpenCypher against `graph-node`.

Local node (from the OSS README):

- Bolt `127.0.0.1:7687`
- HTTP `127.0.0.1:8443`
- Admin `127.0.0.1:9090`
- Auth token file containing `local-development-token-32-bytes`
- `GRAPH_ALLOW_PLAINTEXT=true`
- Image `ghcr.io/hydra-db/hydradb:latest`

## Frozen contract this subtask owns

Python types live in `scar/models.py`. Other subtasks **read** this file at merge time; they must not edit it. They code against the JSON shapes documented in `PARALLEL_PLAN.md`.

Node labels and required properties:

| Label | Key properties |
|---|---|
| `Repo` | `id`, `root`, `language` |
| `File` | `id`, `path`, `language` |
| `Symbol` | `id`, `qualified_name`, `kind` |
| `Session` | `id`, `source`, `started_at` |
| `Turn` | `id`, `role`, `ts`, `text` |
| `Error` | `id`, `signature`, `message`, `tool`, `exit_code` |
| `Correction` | `id`, `kind`, `text`, `created_at`, `active` |
| `AntiPattern` | `id`, `name`, `description` |
| `Constraint` | `id`, `rule`, `active` |

Relationship types: `IN_REPO`, `HAS_TURN`, `TOUCHED`, `MENTIONS`, `EMITTED`, `IN_FILE`, `ON_SYMBOL`, `SAME_AS`, `FIXES`, `STATED_IN`, `SUPERSEDES`, `INSTANCE_OF`, `FORBIDDEN_IN`, `IMPORTS`, `CALLS`, `LED_TO`.

Correction `kind` enum: `human_instruction`, `human_revert`, `successful_retry`, `tool_failure_then_fix`.

## Implementation

1. Create `docker-compose.yml` that starts one plaintext `graph-node` with host-mounted `hydradb-data/store`, `hydradb-data/cache`, and `hydradb-data/auth-token`. Match the official OSS docker flags (`CLOUD_PROVIDER=local`, `RUST_MIN_STACK=33554432`, `--user` note in README).
2. Create `scar/graph/client.py` wrapping both Bolt (`neo4j` driver) and HTTP JSON query. One `query(cypher, params)` function. Auth from `HYDRA_BOLT_URI`, `HYDRA_HTTP_URI`, `HYDRA_AUTH_TOKEN`.
3. Create `scar/graph/schema.py` that MERGEs uniqueness constraints / indexes if the OpenCypher subset supports them; otherwise document the MERGE key convention (`id` on every node).
4. Create `scar/graph/queries.py` with these **named** operations (other subtasks call these names, they do not invent Cypher):
   - `upsert_repo`, `upsert_file`, `upsert_symbol`, `upsert_session`, `upsert_turn`
   - `upsert_error`, `link_same_signature`, `upsert_correction`, `supersede_correction`
   - `link_call`, `link_import`, `link_led_to`
   - `recall_for_context(repo_id, file_path, symbol, error_text, task_text)` — multi-hop:
     1. exact `Error.signature` match
     2. `CALLS`/`IMPORTS` neighborhood of the current file/symbol (1–2 hops)
     3. active `Correction` only (`active = true`)
     4. if a newer correction `SUPERSEDES` an older one, return only the newest
     5. if nothing matches, return `{hits: [], abstain: true, reason: "..."}` — never invent a scar
   - `blast_radius(error_id)` — files that `IMPORTS*` a file that emitted the same signature
5. Create `scar/models.py` with Pydantic v2 models matching the frozen contract.
6. Create `schema/ontology.cypher` as the human-readable source of truth for the graph.
7. Create `scripts/seed_fixture_graph.py` that writes the demo graph from `fixtures/demo_graph.json` (this subtask also **creates** that JSON fixture — dashboard-demo may add UI-only fixtures later, not this file).
8. Tests in `tests/test_graph_queries.py`:
   - round-trip write + recall of one correction
   - supersession hides the old correction
   - neighborhood recall via `CALLS`
   - abstain when the repo has no matching scar
   Skip live HydraDB tests with `@pytest.mark.integration` if the node is down; include a mocked client unit test that still asserts Cypher shape.

## Acceptance Criteria

- [ ] `docker compose up` brings up graph-node; `/readyz` on 9090 succeeds
- [ ] A Python write then read round-trips a Correction that `FIXES` an Error
- [ ] `recall_for_context` returns only active, non-superseded corrections
- [ ] `recall_for_context` returns `abstain: true` on an empty graph rather than a hallucinated lesson
- [ ] `blast_radius` traverses `IMPORTS` (graph, not string match)
- [ ] `scar/models.py` matches the table above
- [ ] Tests pass (`pytest tests/test_graph_queries.py`)
- [ ] No security vulnerabilities (token from env/file, never hardcoded in git besides the documented local-dev token file which is gitignored except `.env.example`)

## Files to Create/Modify

- `docker-compose.yml` - HydraDB OSS graph-node
- `.env.example` - `HYDRA_BOLT_URI`, `HYDRA_HTTP_URI`, `HYDRA_AUTH_TOKEN`
- `pyproject.toml` - package `scar`, deps: `neo4j`, `pydantic`, `httpx`, `pytest` (other subtasks add their deps without removing these)
- `scar/__init__.py`
- `scar/models.py`
- `scar/graph/__init__.py`
- `scar/graph/client.py`
- `scar/graph/schema.py`
- `scar/graph/queries.py`
- `schema/ontology.cypher`
- `schema/README.md` - why this is a graph, not a vector store
- `scripts/seed_fixture_graph.py`
- `fixtures/demo_graph.json`
- `tests/test_graph_queries.py`
- `tests/conftest.py` - Hydra skip/live fixture

## Integration Points

- **Provides**: HydraDB client, ontology, named Cypher operations, Pydantic models, docker-compose, pyproject.toml
- **Consumes**: None
- **Conflicts**: Do not create MCP/HTTP agent servers. Do not create extractors. Do not create the dashboard. Do not write the top-level README.md (hackathon-pack owns it). You may create `schema/README.md` only.
