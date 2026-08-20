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


PROTECTED_PORTS = ("443", "8443")
ADDED_PORT = "10000"


def fail(message):
    raise SystemExit(f"route preservation: {message}")


def load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError, TypeError):
        fail("invalid Tailscale status JSON")
    if not isinstance(value, dict):
        fail("status JSON must be an object")
    return value


def section(status, name):
    value = status.get(name)
    if not isinstance(value, dict):
        fail(f"malformed {name} section")
    return value


def protected_entries(status):
    tcp = section(status, "TCP")
    for port in PROTECTED_PORTS:
        value = tcp.get(port)
        if not isinstance(value, dict) or not value:
            fail(f"malformed TCP {port}")

    web = section(status, "Web")
    web_keys = {}
    for port in PROTECTED_PORTS:
        suffix = f":{port}"
        matches = [key for key in web if isinstance(key, str) and key.endswith(suffix)]
        if len(matches) != 1:
            fail(f"expected exactly one Web key ending {suffix}")
        key = matches[0]
        hostname = key[: -len(suffix)]
        value = web[key]
        if not hostname or not isinstance(value, dict) or not value:
            fail(f"malformed Web {key}")
        web_keys[port] = (hostname, value)
    if web_keys["443"][0] != web_keys["8443"][0]:
        fail("Web hostnames differ")
    hostname = web_keys["443"][0]

    allow_funnel = section(status, "AllowFunnel")
    if "443" in allow_funnel or any(
        isinstance(key, str) and key.endswith(":443") for key in allow_funnel
    ):
        fail("protected AllowFunnel 443 must be absent")
    if "8443" in allow_funnel:
        fail("AllowFunnel 8443 must be host-qualified")
    funnel_keys = [
        key for key in allow_funnel if isinstance(key, str) and key.endswith(":8443")
    ]
    if len(funnel_keys) != 1:
        fail("expected exactly one AllowFunnel key ending :8443")
    funnel_key = funnel_keys[0]
    if funnel_key != f"{hostname}:8443" or allow_funnel[funnel_key] is not True:
        fail("malformed protected AllowFunnel 8443")

    return {
        "hostname": hostname,
        "TCP": tcp,
        "Web": web,
        "AllowFunnel": allow_funnel,
    }


baseline = load(sys.argv[1])
current = load(sys.argv[2])
baseline_entries = protected_entries(baseline)
for section_name in ("TCP", "Web", "AllowFunnel"):
    for key in baseline_entries[section_name]:
        is_port_10000 = key == ADDED_PORT or (
            section_name != "TCP" and isinstance(key, str) and key.endswith(f":{ADDED_PORT}")
        )
        if is_port_10000:
            fail(f"baseline {section_name} must not contain port {ADDED_PORT}")

current_entries = protected_entries(current)
if baseline_entries["hostname"] != current_entries["hostname"]:
    fail("Web hostnames changed")

expected = {
    "TCP": {**baseline_entries["TCP"], ADDED_PORT: {"HTTPS": True}},
    "Web": {
        **baseline_entries["Web"],
        f"{baseline_entries['hostname']}:{ADDED_PORT}": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}},
        },
    },
    "AllowFunnel": {
        **baseline_entries["AllowFunnel"],
        f"{baseline_entries['hostname']}:{ADDED_PORT}": True,
    },
}
for section_name in ("TCP", "Web", "AllowFunnel"):
    if current_entries[section_name] != expected[section_name]:
        fail(f"{section_name} must equal baseline plus exactly port {ADDED_PORT}")
PY
printf 'route preservation: PASS\n'
