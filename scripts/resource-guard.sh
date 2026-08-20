#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
mode="${1:-pre}"
case "$mode" in
  pre) minimum_gib=3 ;;
  post) minimum_gib=6 ;;
  *) printf 'usage: %s pre|post\n' "$0" >&2; exit 2 ;;
esac

available_kib="${MEM_AVAILABLE_KIB:-$(python3 -c 'from pathlib import Path; print(next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")))')}"
minimum_kib=$((minimum_gib * 1024 * 1024))
if (( available_kib < minimum_kib )); then
  printf 'resource guard failed: available RAM below %s GiB\n' "$minimum_gib" >&2
  exit 1
fi

swap_used_kib="${SWAP_USED_KIB:-$(python3 -c 'from pathlib import Path; values = {line.split(":", 1)[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith(("SwapTotal:", "SwapFree:"))}; print(values["SwapTotal"] - values["SwapFree"])')}"
swap_timestamp="${SWAP_TIMESTAMP:-${FIRECRAWL_SWAP_TIMESTAMP_SECONDS:-$(date +%s)}}"
growth_threshold="${SWAP_GROWTH_THRESHOLD_KIB_PER_MINUTE:-${FIRECRAWL_SWAP_GROWTH_THRESHOLD_KIB_PER_MINUTE:-131072}}"
state_file="${FIRECRAWL_SWAP_STATE_FILE:-$ROOT/state/resource-guard-swap.state}"
state_directory="$(dirname -- "$state_file")"

[[ "$available_kib" =~ ^[0-9]+$ ]] || { printf 'resource guard failed: invalid available RAM sample\n' >&2; exit 1; }
[[ "$swap_used_kib" =~ ^[0-9]+$ ]] || { printf 'resource guard failed: invalid swap sample\n' >&2; exit 1; }
[[ "$swap_timestamp" =~ ^[0-9]+$ ]] || { printf 'resource guard failed: invalid swap timestamp\n' >&2; exit 1; }
[[ "$growth_threshold" =~ ^[0-9]+$ ]] || { printf 'resource guard failed: invalid swap growth threshold\n' >&2; exit 1; }

if [[ -e "$state_file" || -L "$state_file" ]]; then
  [[ -f "$state_file" && ! -L "$state_file" ]] || {
    printf 'resource guard failed: swap state is not a regular file\n' >&2
    exit 1
  }
  read -r previous_timestamp previous_swap extra < "$state_file" || {
    printf 'resource guard failed: malformed swap state\n' >&2
    exit 1
  }
  [[ -z "${extra:-}" && "${previous_timestamp:-}" =~ ^[0-9]+$ && "${previous_swap:-}" =~ ^[0-9]+$ ]] || {
    printf 'resource guard failed: malformed swap state\n' >&2
    exit 1
  }
  elapsed=$((swap_timestamp - previous_timestamp))
  delta=$((swap_used_kib - previous_swap))
  if (( elapsed <= 0 )); then
    printf 'resource guard failed: non-increasing swap sample time\n' >&2
    exit 1
  fi
  if (( delta > 0 )) && (( delta * 60 >= growth_threshold * elapsed )); then
    printf 'resource guard failed: swap growth exceeds %s KiB/minute\n' "$growth_threshold" >&2
    exit 1
  fi
fi

install -d -m 700 "$state_directory"
chmod 700 "$state_directory"
temporary_state="$(mktemp "$state_file.tmp.XXXXXX")"
printf '%s %s\n' "$swap_timestamp" "$swap_used_kib" > "$temporary_state"
chmod 600 "$temporary_state"
mv -f -- "$temporary_state" "$state_file"

free -h | awk '$1 == "Mem:" || $1 == "Swap:" { print }'
