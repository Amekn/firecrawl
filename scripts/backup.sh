#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ $- == *x* ]]; then
  set +x
fi
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || { printf 'missing required file: %s\n' "$ENV_FILE" >&2; exit 2; }
unset BACKUP_HELPER_IMAGE
# shellcheck disable=SC1091
source "$ROOT/.env"
: "${BACKUP_HELPER_IMAGE:?missing BACKUP_HELPER_IMAGE in .env}"

COMPOSE_SCRIPT="${FIRECRAWL_COMPOSE_SCRIPT:-$SCRIPT_DIR/compose.sh}"
RESOURCE_GUARD="${FIRECRAWL_RESOURCE_GUARD_SCRIPT:-$SCRIPT_DIR/resource-guard.sh}"

leave_stopped=0
output_dir=""
while (($#)); do
  case "$1" in
    --leave-stopped)
      leave_stopped=1
      shift
      ;;
    --output)
      (($# >= 2)) || { printf 'usage: %s [--leave-stopped] [--output DIR]\n' "$0" >&2; exit 2; }
      output_dir="$2"
      shift 2
      ;;
    *)
      printf 'usage: %s [--leave-stopped] [--output DIR]\n' "$0" >&2
      exit 2
      ;;
  esac
done

backup_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "$output_dir" ]]; then
  backup_dir="$ROOT/backups/$backup_timestamp"
elif [[ "$output_dir" = /* ]]; then
  backup_dir="$output_dir"
else
  backup_dir="$ROOT/$output_dir"
fi
install -d -m 700 "$backup_dir"

"$RESOURCE_GUARD" pre

volumes=(
  firecrawl-postgres-data
  firecrawl-redis-data
  firecrawl-rabbitmq-data
)
archives=(
  postgres.tar.gz
  redis.tar.gz
  rabbitmq.tar.gz
)

services_stopped=0
restart_services() {
  printf 'restarting Firecrawl stateful services\n' >&2
  "$COMPOSE_SCRIPT" up -d nuq-postgres redis rabbitmq
  printf 'restarting Firecrawl application services\n' >&2
  "$COMPOSE_SCRIPT" up -d playwright-service api gateway
}
backup_exit() {
  local status=$?
  trap - EXIT
  if (( services_stopped && !leave_stopped )); then
    if ! restart_services; then
      printf 'failed to restart Firecrawl services after backup\n' >&2
      (( status == 0 )) && status=1
    fi
  fi
  exit "$status"
}
trap backup_exit EXIT

services_stopped=1
"$COMPOSE_SCRIPT" stop gateway api playwright-service
"$COMPOSE_SCRIPT" stop redis rabbitmq nuq-postgres

for index in "${!volumes[@]}"; do
  volume="${volumes[$index]}"
  archive="${archives[$index]}"
  docker volume inspect "$volume" >/dev/null
  docker run --rm \
    -v "${volume}:/source:ro" \
    -v "${backup_dir}:/backup" \
    "$BACKUP_HELPER_IMAGE" \
    sh -eu -c "cd /source && tar -czf /backup/${archive} ."
  [[ -s "$backup_dir/$archive" ]] || {
    printf 'backup archive is empty or missing: %s\n' "$backup_dir/$archive" >&2
    exit 1
  }
done

compose_version="$("$COMPOSE_SCRIPT" version --short)"
git_commit="$(git rev-parse HEAD)"
git_description="$(git describe --tags --always)"
printf '%s\n' \
  "Git commit: $git_commit" \
  "Git describe: $git_description" \
  "Compose version: $compose_version" \
  "Volume: firecrawl-postgres-data -> postgres.tar.gz" \
  "Volume: firecrawl-redis-data -> redis.tar.gz" \
  "Volume: firecrawl-rabbitmq-data -> rabbitmq.tar.gz" \
  "BACKUP_HELPER_IMAGE: $BACKUP_HELPER_IMAGE" \
  "UTC timestamp: $backup_timestamp" \
  > "$backup_dir/manifest.txt"
(
  cd -- "$backup_dir"
  sha256sum -- *.tar.gz > SHA256SUMS
)
printf 'backup created: %s\n' "$backup_dir"
