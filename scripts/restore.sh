#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if (($# != 2)); then
  printf 'usage: %s BACKUP_DIR --confirm\n' "$0" >&2
  exit 2
fi
if [[ "$1" == "--confirm" ]]; then
  backup_dir="$2"
elif [[ "$2" == "--confirm" ]]; then
  backup_dir="$1"
else
  printf 'usage: %s BACKUP_DIR --confirm\n' "$0" >&2
  exit 2
fi

if [[ "$backup_dir" != /* ]]; then
  backup_dir="$ROOT/$backup_dir"
fi
[[ -d "$backup_dir" ]] || { printf 'missing backup directory: %s\n' "$backup_dir" >&2; exit 2; }

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
BACKUP_SCRIPT="${FIRECRAWL_BACKUP_SCRIPT:-$SCRIPT_DIR/backup.sh}"
VERIFY_LOCAL="${FIRECRAWL_VERIFY_LOCAL_SCRIPT:-$SCRIPT_DIR/verify-local.sh}"
RESOURCE_GUARD="${FIRECRAWL_RESOURCE_GUARD_SCRIPT:-$SCRIPT_DIR/resource-guard.sh}"

manifest="$backup_dir/manifest.txt"
checksums="$backup_dir/SHA256SUMS"
[[ -s "$manifest" ]] || { printf 'missing or empty manifest: %s\n' "$manifest" >&2; exit 2; }
[[ -s "$checksums" ]] || { printf 'missing or empty checksums: %s\n' "$checksums" >&2; exit 2; }

for required_manifest_field in \
  '^Git commit: .+$' \
  '^Git describe: .+$' \
  '^Compose version: .+$' \
  '^UTC timestamp: .+$'; do
  grep -Eq -- "$required_manifest_field" "$manifest" || {
    printf 'manifest is missing required field: %s\n' "$required_manifest_field" >&2
    exit 2
  }
done

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
for index in "${!volumes[@]}"; do
  volume="${volumes[$index]}"
  archive="${archives[$index]}"
  grep -Fqx -- "Volume: $volume -> $archive" "$manifest" || {
    printf 'manifest is missing volume mapping: %s -> %s\n' "$volume" "$archive" >&2
    exit 2
  }
  [[ -s "$backup_dir/$archive" ]] || {
    printf 'missing or empty archive: %s\n' "$backup_dir/$archive" >&2
    exit 2
  }
done
(
  cd -- "$backup_dir"
  sha256sum -c SHA256SUMS
)

pre_restore_dir="backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
"$BACKUP_SCRIPT" --leave-stopped --output "$pre_restore_dir"

mapfile -t running_containers < <(docker ps --filter name=firecrawl --format '{{.Names}}')
if ((${#running_containers[@]})); then
  printf 'refusing restore while Firecrawl containers are running: %s\n' "${running_containers[*]}" >&2
  exit 1
fi

for volume in "${volumes[@]}"; do
  docker volume inspect "$volume" >/dev/null
  docker run --rm \
    -v "${volume}:/target" \
    "$BACKUP_HELPER_IMAGE" \
    sh -eu -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
done

for index in "${!volumes[@]}"; do
  volume="${volumes[$index]}"
  archive="${archives[$index]}"
  docker run --rm \
    -v "${volume}:/target" \
    -v "${backup_dir}:/backup:ro" \
    "$BACKUP_HELPER_IMAGE" \
    sh -eu -c "cd /target && tar -xzf /backup/${archive}"
done

"$COMPOSE_SCRIPT" up -d nuq-postgres redis rabbitmq
health_timeout="${FIRECRAWL_HEALTH_TIMEOUT_SECONDS:-120}"
wait_for_healthy() {
  local service="$1"
  local deadline=$((SECONDS + health_timeout))
  local container_id health_status
  while (( SECONDS < deadline )); do
    container_id="$("$COMPOSE_SCRIPT" ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      health_status="$(docker inspect --format '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
      if [[ "$health_status" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  printf 'service did not become healthy: %s\n' "$service" >&2
  return 1
}
for service in nuq-postgres redis rabbitmq; do
  wait_for_healthy "$service"
done

"$COMPOSE_SCRIPT" up -d playwright-service api gateway
"$VERIFY_LOCAL"
"$RESOURCE_GUARD" post
printf 'restore completed from: %s\n' "$backup_dir"
