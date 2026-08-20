#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BACKUP_ROOT="$ROOT/backups"

fail_usage() {
  printf '%s\n' "$1" >&2
  exit 2
}

ensure_backup_root() {
  if [[ -L "$BACKUP_ROOT" || ( -e "$BACKUP_ROOT" && ! -d "$BACKUP_ROOT" ) ]]; then
    fail_usage "backup root is not a real directory: $BACKUP_ROOT"
  fi
  [[ -d "$BACKUP_ROOT" && ! -L "$BACKUP_ROOT" ]] || fail_usage "backup root is not a real directory: $BACKUP_ROOT"
}

assert_no_symlink_components() {
  local candidate="$1"
  local current="$ROOT"
  local relative="${candidate#"$ROOT"/}"
  local component
  local -a components
  IFS='/' read -r -a components <<< "$relative"
  for component in "${components[@]}"; do
    [[ -z "$component" || "$component" == "." ]] && continue
    current="$current/$component"
    [[ ! -L "$current" ]] || fail_usage "backup path contains a symlink: $candidate"
  done
}

resolve_restore_path() {
  local requested="$1"
  local candidate canonical backup_root_canonical
  [[ -n "$requested" ]] || fail_usage "backup path must not be empty"
  [[ "$requested" != /* ]] || fail_usage "backup path must be relative beneath $BACKUP_ROOT"
  [[ "$requested" != *:* && "$requested" != *$'\n'* && "$requested" != *$'\r'* ]] || fail_usage "backup path contains a Docker volume delimiter"
  case "/$requested/" in
    */../*) fail_usage "backup path must not contain traversal components" ;;
  esac
  candidate="$ROOT/$requested"
  backup_root_canonical="$(realpath -- "$BACKUP_ROOT")"
  canonical="$(realpath -- "$candidate")" || fail_usage "missing backup directory: $requested"
  [[ "$canonical" == "$backup_root_canonical"/* ]] || fail_usage "backup path must be beneath $BACKUP_ROOT"
  assert_no_symlink_components "$candidate"
  [[ -d "$candidate" && ! -L "$candidate" ]] || fail_usage "backup path is not a real directory: $requested"
  printf '%s\n' "$canonical"
}

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

ensure_backup_root
backup_dir="$(resolve_restore_path "$backup_dir")"

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

validate_checksums() {
  local line checksum archive count=0
  declare -A seen=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    ((count += 1))
    if [[ ! "$line" =~ ^([[:xdigit:]]{64})[[:space:]][[:space:]]([^[:space:]]+)$ ]]; then
      printf 'invalid checksum entry\n' >&2
      return 1
    fi
    checksum="${BASH_REMATCH[1]}"
    archive="${BASH_REMATCH[2]}"
    case "$archive" in
      postgres.tar.gz|redis.tar.gz|rabbitmq.tar.gz) ;;
      *) printf 'unexpected checksum entry: %s\n' "$archive" >&2; return 1 ;;
    esac
    [[ -z "${seen[$archive]+set}" ]] || { printf 'duplicate checksum entry: %s\n' "$archive" >&2; return 1; }
    seen["$archive"]="$checksum"
  done < "$checksums"
  ((count == ${#archives[@]})) || { printf 'checksum file must contain exactly three archive entries\n' >&2; return 1; }
  for archive in "${archives[@]}"; do
    [[ -n "${seen[$archive]+set}" ]] || { printf 'missing checksum entry: %s\n' "$archive" >&2; return 1; }
  done
}

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
validate_checksums
(
  cd -- "$backup_dir"
  sha256sum -c SHA256SUMS
)

running_containers_output=""
if ! running_containers_output="$(docker ps --filter name=firecrawl --format '{{.Names}}')"; then
  printf 'failed to query active Firecrawl containers\n' >&2
  exit 1
fi
running_containers=()
if [[ -n "$running_containers_output" ]]; then
  mapfile -t running_containers <<< "$running_containers_output"
fi
if ((${#running_containers[@]})); then
  printf 'refusing restore while Firecrawl containers are running: %s\n' "${running_containers[*]}" >&2
  exit 1
fi

for archive in "${archives[@]}"; do
  docker run --rm \
    -v "${backup_dir}:/backup:ro" \
    "$BACKUP_HELPER_IMAGE" \
    sh -eu -c "tar -tzf /backup/${archive} >/dev/null"
done

pre_restore_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
pre_restore_argument="backups/pre-restore-$pre_restore_timestamp"
pre_restore_dir="$BACKUP_ROOT/pre-restore-$pre_restore_timestamp"
"$BACKUP_SCRIPT" --leave-stopped --output "$pre_restore_argument"

restore_mutation_started=0
restore_failure_cleanup() {
  local status=$?
  trap - EXIT
  if (( restore_mutation_started )); then
    "$COMPOSE_SCRIPT" stop gateway api playwright-service redis rabbitmq nuq-postgres >/dev/null 2>&1 || true
    printf 'restore failed after volume mutation; services stopped; safety backup: %s\n' "$pre_restore_dir" >&2
  fi
  exit "$status"
}
trap restore_failure_cleanup EXIT
restore_mutation_started=1

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
trap - EXIT
printf 'restore completed from: %s\n' "$backup_dir"
