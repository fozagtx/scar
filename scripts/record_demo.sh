#!/usr/bin/env bash
# 60-second judge click path for the SCAR demo video.
# Hand-rolled SVG graph — no Node, no vis-network CDN.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${SCAR_DEMO_HOST:-127.0.0.1}"
PORT="${SCAR_DEMO_PORT:-7331}"
BASE="http://${HOST}:${PORT}"

cat <<'EOF'
SCAR demo — 60s click path (workstation graph)
==============================================
Prereq:  python scripts/demo_api.py
Open:    http://127.0.0.1:7331/

00:00  Mast: SCAR / demo-repo / FIXTURE. Three panes. Graph is the stage.
00:06  Left: session:demo-utcnow (cursor). Files: timeutil.py has scar, unrelated.py abstain.
00:12  Center: File src/api.py --IMPORTS--> src/timeutil.py.
              Error utcnow-attr --FIXES--> cor:utcnow-ban (acid green).
00:20  Point at cor:old-utcnow: grey, struck, badge "superseded".
              Edge SUPERSEDES from the live ban. Vector search would surface both.
00:28  Right: file=src/timeutil.py  error=AttributeError utcnow. Click RECALL (or R).
00:34  Hit: "never use datetime.utcnow; use datetime.now(timezone.utc)" via file.
              Old utcnow instruction is NOT in the hit list.
00:42  Click BLAST RADIUS (or B). src/api.py lights up (IMPORTS*). unrelated.py stays dark.
00:50  Left: click src/unrelated.py (clears error text). RECALL.
00:56  ABSTAIN — "SCAR has no stored correction for this context. Do not invent a house rule."
01:00  Cut.

Fallback if the UI is down: the curls below replay the same story.
Graph renderer: ui/graph.js (SVG). No CDN. If vis-network is ever added, keep graph.js.
EOF

if curl -sf "${BASE}/health" >/dev/null 2>&1; then
  echo
  echo "-- live API check against ${BASE} --"
  echo "1) banned utcnow file → hit"
  curl -sS -X POST "${BASE}/v1/recall" \
    -H 'Content-Type: application/json' \
    -d '{"repo_id":"demo-repo","file_path":"src/timeutil.py","error_text":"AttributeError utcnow"}'
  echo
  echo "2) unrelated file → abstain"
  curl -sS -X POST "${BASE}/v1/recall" \
    -H 'Content-Type: application/json' \
    -d '{"repo_id":"demo-repo","file_path":"src/unrelated.py"}'
  echo
  echo "3) blast radius from err:utcnow-attr"
  curl -sS -X POST "${BASE}/v1/blast" \
    -H 'Content-Type: application/json' \
    -d '{"error_id":"err:utcnow-attr"}'
  echo
else
  echo
  echo "Server not running. Start it with:"
  echo "  python ${ROOT}/scripts/demo_api.py"
fi
