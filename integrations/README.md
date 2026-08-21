# Agent integrations

Cursor, Claude Code, Codex, Hermes, and OpenClaw share one HydraDB graph. Each agent can use the `scar` CLI, HTTP `:8765`, or MCP tools over stdio.

Spawn (from the clone, HydraDB already up):

```bash
curl -sS http://127.0.0.1:9090/readyz
/ABS/PATH/TO/scar/.venv/bin/python -m scar.serve.mcp_server
```

That process is `scar/serve/mcp_server.py`. Tools: `scar_recall`, `scar_record`, `scar_blast_radius`. `scar mcp` runs the same loop.

Replace `/ABS/PATH/TO/scar` with the clone path. Point `command` at that clone's `.venv/bin/python`.

## Per agent

| Agent | File | What to do |
|---|---|---|
| Cursor | [mcp.json.example](mcp.json.example), [cursor-rule.mdc](cursor-rule.mdc) | Paste the JSON into Cursor MCP settings. Copy the rule into `.cursor/rules/`. |
| Claude Code | [claude.mcp.json.example](claude.mcp.json.example), [claude-skill.md](claude-skill.md) | Commit `.mcp.json` at the project root, or `claude mcp add` (see README). Copy the skill into `.claude/skills/`. |
| Codex | [codex.toml.example](codex.toml.example) | Merge into `~/.codex/config.toml` or the project's `.codex/config.toml`. |
| Hermes | [hermes.yaml.example](hermes.yaml.example) | Merge `mcp_servers.scar` into `~/.hermes/config.yaml`. CLI below also works. |
| OpenClaw | [openclaw.json.example](openclaw.json.example) | Merge `mcp.servers.scar` into `~/.openclaw/openclaw.json`. CLI below also works. |

## CLI

```bash
.venv/bin/scar recall --repo my-repo --file src/timeutil.py --error "AttributeError utcnow"
.venv/bin/scar record --repo my-repo --file src/timeutil.py --correction "use datetime.now with timezone.utc"
```

## HTTP

```bash
.venv/bin/scar serve
```

`POST http://127.0.0.1:8765/v1/recall` and `POST /v1/record` take `repo_id` and `file_path`.

## Extract, then mine

```bash
.venv/bin/python -m scar.ingest extracted.jsonl --source all
.venv/bin/scar ingest extracted.jsonl --repo my-repo
```

Extract reads local **Cursor**, **Claude Code**, and **Codex** transcript stores. Hermes and OpenClaw use `scar record` from a live session.
