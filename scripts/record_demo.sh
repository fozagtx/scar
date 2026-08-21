#!/usr/bin/env bash
# 60-second judge click path for the SCAR demo video.
# Hand-rolled SVG graph — no Node, no vis-network CDN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${SCAR_DEMO_HOST:-127.0.0.1}"
PORT="${SCAR_DEMO_PORT:-7331}"
BASE="http://${HOST}:${PORT}"

cat <<'EOF'
SCAR demo — 60s click path (live HydraDB)
========================================
Prereq:  docker compose up (readyz), then extract+ingest local sessions,
         then python scripts/demo_api.py
Open:    http://127.0.0.1:7331/

00:00  Mast: SCAR / hydradb-oss / LIVE. Three panes. Graph is the stage.
00:08  Left: sessions and files from the ingested graph. Files with scars are marked.
00:16  Center: nodes and edges from GET /graph (HydraDB export, not a JSON fixture).
00:24  Right: pick a file that has a scar. Click RECALL (or R).
00:34  Hit: active correction text. Superseded corrections are not in the hit list.
00:42  Click BLAST RADIUS (or B). Importers light up (IMPORTS*). Unrelated files stay dark.
00:50  Click a file with no scar. RECALL.
00:56  ABSTAIN — "SCAR has no stored correction for this context. Do not invent a house rule."
01:00  Cut.

Fallback if the UI is down: the curls below hit the same live endpoints.
Graph renderer: ui/graph.js (SVG). No CDN.
EOF

if curl -sf "${BASE}/health" >/dev/null 2>&1; then
  echo
  echo "-- live API check against ${BASE} --"
  echo "1) graph dump from HydraDB"
  curl -sS "${BASE}/graph" | python3 -c 'import json,sys; g=json.load(sys.stdin); print("files", len(g.get("files") or []), "errors", len(g.get("errors") or []), "corrections", len(g.get("corrections") or []))'
  echo
  echo "2) health"
  curl -sS "${BASE}/health"
  echo
else
  echo
  echo "Server not running. Start HydraDB, ingest sessions, then:"
  echo "  python ${ROOT}/scripts/demo_api.py"
fi
