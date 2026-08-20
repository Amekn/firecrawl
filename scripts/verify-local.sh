#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOCAL_URL="${FIRECRAWL_LOCAL_URL:-http://127.0.0.1:3002}"
API_ENV_FILE="${FIRECRAWL_API_ENV_FILE:-$REPO_ROOT/secrets/api.env}"
OUTPUT_DIR="${FIRECRAWL_VERIFICATION_OUTPUT_DIR:-$REPO_ROOT/verification-output}"
COMPOSE_SCRIPT="${FIRECRAWL_COMPOSE_SCRIPT:-$SCRIPT_DIR/compose.sh}"

[[ -f "$API_ENV_FILE" ]] || { printf 'missing API environment file\n' >&2; exit 2; }
# shellcheck disable=SC1090
source "$API_ENV_FILE"
: "${FIRECRAWL_API_KEY:?missing FIRECRAWL_API_KEY in API environment file}"

install -d -m 700 "$OUTPUT_DIR"
temporary_directory="$(mktemp -d "$OUTPUT_DIR/local.XXXXXX")"
cleanup() {
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT

request_status() {
  local name="$1"
  local expected="$2"
  local response_file="$3"
  shift 3
  local status

  if ! status="$(curl --silent --show-error --output "$response_file" --write-out '%{http_code}' "$@" 2>/dev/null)"; then
    printf '%s: ERROR\n' "$name" >&2
    return 1
  fi
  if [[ "$status" != "$expected" ]]; then
    printf '%s: expected %s, got %s\n' "$name" "$expected" "$status" >&2
    return 1
  fi
  printf '%s: %s\n' "$name" "$status"
}

request_status "healthz" "200" "$temporary_directory/healthz" \
  --request GET "$LOCAL_URL/healthz"
request_status "readiness without key" "401" "$temporary_directory/readiness-no-key" \
  --request GET "$LOCAL_URL/v0/health/readiness"
request_status "readiness with wrong key" "401" "$temporary_directory/readiness-wrong-key" \
  --request GET -H 'Authorization: Bearer wrong' "$LOCAL_URL/v0/health/readiness"

authorization_header=( -H "Authorization: Bearer ${FIRECRAWL_API_KEY}" )
request_status "readiness with key" "200" "$temporary_directory/readiness-key" \
  --request GET "${authorization_header[@]}" "$LOCAL_URL/v0/health/readiness"

search_payload='{"query":"Firecrawl self hosting","sources":["web"]}'
request_status "search" "200" "$temporary_directory/search" \
  --request POST -H 'Content-Type: application/json' "${authorization_header[@]}" \
  --data "$search_payload" "$LOCAL_URL/v2/search"
python3 - "$temporary_directory/search" <<'PY'
import json
import sys

try:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    data = payload.get("data", payload)
    web = data.get("web") if isinstance(data, dict) else None
except (OSError, ValueError, TypeError):
    raise SystemExit("search: invalid JSON response")
if not isinstance(web, list) or not web:
    raise SystemExit("search: no web results")
PY
printf 'search results: PASS\n'

scrape_payload='{"url":"https://example.com","formats":["markdown"]}'
request_status "scrape" "200" "$temporary_directory/scrape" \
  --request POST -H 'Content-Type: application/json' "${authorization_header[@]}" \
  --data "$scrape_payload" "$LOCAL_URL/v2/scrape"
python3 - "$temporary_directory/scrape" <<'PY'
import json
import sys

try:
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    data = payload.get("data", payload)
    markdown = data.get("markdown") if isinstance(data, dict) else None
except (OSError, ValueError, TypeError):
    raise SystemExit("scrape: invalid JSON response")
if not isinstance(markdown, str) or not markdown.strip():
    raise SystemExit("scrape: empty Markdown")
PY
printf 'scrape Markdown: PASS\n'

if ! "$COMPOSE_SCRIPT" logs --since=5m api > "$temporary_directory/logs" 2>&1; then
  printf 'searxng logs: ERROR\n' >&2
  exit 1
fi
if ! grep -Fq -- 'Using searxng search' "$temporary_directory/logs"; then
  printf 'searxng logs: missing search backend marker\n' >&2
  exit 1
fi
printf 'searxng logs: PASS\n'
