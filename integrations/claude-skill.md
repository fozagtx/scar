---
name: scar-recall
description: Query SCAR stored corrections before editing, and record a new scar after a human correction. Use when making a non-trivial code change, reproducing an error, or after the user yells at you.
---

# SCAR — Stored Corrections And Recall

Before applying a non-trivial edit, call `scar_recall` with the current file and the error/task. If SCAR returns hits, obey active corrections. If it abstains, proceed normally.

Never invent a house rule. If SCAR says it has no stored correction for this context, continue with ordinary judgment.

## Tools

- `scar_recall` — `repo_id`, `file_path`, optional `symbol`, `error_text`, `task_text`
- `scar_record` — `repo_id`, `file_path`, `correction_text`, optional `error_text` (writes a `human_instruction` now)
- `scar_blast_radius` — `error_id` or `signature` (files that `IMPORTS*` the origin)

Equivalent CLI: `scar recall`, `scar record`, `scar abstain-check`. Equivalent HTTP: `POST /v1/recall`, `POST /v1/record`. Same graph as Cursor, Codex, Hermes, and OpenClaw.
