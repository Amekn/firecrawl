#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BASELINE_PATH="${1:-}"
PUBLIC_URL="${FIRECRAWL_FUNNEL_URL:-https://the-dream-land.taile6fad0.ts.net:10000}"
API_ENV_FILE="${FIRECRAWL_API_ENV_FILE:-$REPO_ROOT/secrets/api.env}"
OUTPUT_DIR="${FIRECRAWL_VERIFICATION_OUTPUT_DIR:-$REPO_ROOT/verification-output}"
TAILSCALE_BIN="${TAILSCALE_BIN:-tailscale}"

if [[ -z "$BASELINE_PATH" ]]; then
  printf 'usage: %s BASELINE_STATUS_JSON\n' "$0" >&2
  exit 2
fi
[[ -f "$BASELINE_PATH" ]] || { printf 'missing baseline status JSON\n' >&2; exit 2; }
[[ -f "$API_ENV_FILE" ]] || { printf 'missing API environment file\n' >&2; exit 2; }
# shellcheck disable=SC1090
source "$API_ENV_FILE"
: "${FIRECRAWL_API_KEY:?missing FIRECRAWL_API_KEY in API environment file}"

install -d -m 700 "$OUTPUT_DIR"
temporary_directory="$(mktemp -d "$OUTPUT_DIR/funnel.XXXXXX")"
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

request_status "public readiness without key" "401" "$temporary_directory/readiness-no-key" \
  --request GET "$PUBLIC_URL/v0/health/readiness"
authorization_header=( -H "Authorization: Bearer ${FIRECRAWL_API_KEY}" )
request_status "public readiness with key" "200" "$temporary_directory/readiness-key" \
  --request GET "${authorization_header[@]}" "$PUBLIC_URL/v0/health/readiness"

if ! "$TAILSCALE_BIN" funnel status --json > "$temporary_directory/current.json" 2>/dev/null; then
  printf 'route preservation: unable to read current Tailscale status\n' >&2
  exit 1
fi
python3 - "$BASELINE_PATH" "$temporary_directory/current.json" <<'PY'
import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError, TypeError):
        raise SystemExit("route preservation: invalid Tailscale status JSON")
    if not isinstance(value, dict):
        raise SystemExit("route preservation: status JSON must be an object")
    return value


def port_entries(status, section, port):
    section_value = status.get(section, {})
    if not isinstance(section_value, dict):
        return []
    matches = []
    for key, value in section_value.items():
        key_text = str(key)
        if key_text == port or key_text == f":{port}" or key_text.endswith(f":{port}"):
            matches.append((key_text, value))
    return sorted(matches, key=lambda item: item[0])

baseline = load(sys.argv[1])
current = load(sys.argv[2])
for section in ("TCP", "Web", "AllowFunnel"):
    for port in ("443", "8443"):
        if port_entries(baseline, section, port) != port_entries(current, section, port):
            raise SystemExit(f"route preservation failed: {section} {port}")
PY
printf 'route preservation: PASS\n'
