#!/usr/bin/env bash
set -euo pipefail

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

free -h | awk '$1 == "Mem:" || $1 == "Swap:" { print }'
