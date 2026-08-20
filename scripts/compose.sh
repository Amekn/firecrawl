#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for required in "$ROOT/.env" "$ROOT/secrets/stack.env"; do
  [[ -f "$required" ]] || { printf 'missing required file: %s\n' "$required" >&2; exit 2; }
done
exec docker compose \
  --env-file "$ROOT/.env" \
  --env-file "$ROOT/secrets/stack.env" \
  -f "$ROOT/docker-compose.yaml" \
  -f "$ROOT/compose.the-dream-land.yaml" \
  "$@"
