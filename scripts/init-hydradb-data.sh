#!/usr/bin/env bash
# Create HydraDB OSS local store/cache and the plaintext auth token file.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/hydradb-data"
TOKEN_VALUE="local-development-token-32-bytes"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

mkdir -p "$DATA/store" "$DATA/cache"

TOKEN_FILE="$DATA/auth-token"
if [[ ! -f "$TOKEN_FILE" ]]; then
  printf '%s\n' "$TOKEN_VALUE" > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"

ENV_FILE="$ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
HYDRA_BOLT_URI=bolt://127.0.0.1:7687
HYDRA_HTTP_URI=http://127.0.0.1:8443
HYDRA_AUTH_TOKEN=$TOKEN_VALUE
HYDRA_GRAPH_ID=default
HYDRA_NAMESPACE=default
HYDRA_CELL_ID=cell-0
UID=$HOST_UID
GID=$HOST_GID
EOF
else
  if ! grep -q '^UID=' "$ENV_FILE"; then
    printf '\nUID=%s\n' "$HOST_UID" >> "$ENV_FILE"
  fi
  if ! grep -q '^GID=' "$ENV_FILE"; then
    printf 'GID=%s\n' "$HOST_GID" >> "$ENV_FILE"
  fi
  if ! grep -q '^HYDRA_AUTH_TOKEN=' "$ENV_FILE"; then
    printf 'HYDRA_AUTH_TOKEN=%s\n' "$TOKEN_VALUE" >> "$ENV_FILE"
  fi
fi

echo "hydradb-data ready at $DATA"
echo "token file: $TOKEN_FILE"
echo "start: UID=$HOST_UID GID=$HOST_GID docker compose up"
