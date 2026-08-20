#!/usr/bin/env bash
set -euo pipefail
umask 077

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
VERIFY_LOCAL="${FIRECRAWL_VERIFY_LOCAL_SCRIPT:-$SCRIPT_DIR/verify-local.sh}"
WAIT_TIMEOUT="${FIRECRAWL_WAIT_TIMEOUT_SECONDS:-300}"
BACKUP_ROOT="$ROOT/backups"

fail_usage() {
  printf '%s\n' "$1" >&2
  exit 2
}

[[ "$WAIT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || fail_usage "wait timeout must be a positive integer"

ensure_backup_root() {
  if [[ -L "$BACKUP_ROOT" || ( -e "$BACKUP_ROOT" && ! -d "$BACKUP_ROOT" ) ]]; then
    fail_usage "backup root is not a real directory: $BACKUP_ROOT"
  fi
  if [[ ! -e "$BACKUP_ROOT" ]]; then
    mkdir -m 700 -- "$BACKUP_ROOT"
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

resolve_output_path() {
  local requested="$1"
  local candidate canonical backup_root_canonical
  [[ -n "$requested" ]] || fail_usage "output path must not be empty"
  [[ "$requested" != /* ]] || fail_usage "output path must be relative beneath $BACKUP_ROOT"
  [[ "$requested" != *:* && "$requested" != *$'\n'* && "$requested" != *$'\r'* ]] || fail_usage "output path contains a Docker volume delimiter"
  case "/$requested/" in
    */../*) fail_usage "output path must not contain traversal components" ;;
  esac
  candidate="$ROOT/$requested"
  backup_root_canonical="$(realpath -- "$BACKUP_ROOT")"
  canonical="$(realpath -m -- "$candidate")"
  [[ "$canonical" == "$backup_root_canonical"/* ]] || fail_usage "output path must be beneath $BACKUP_ROOT"
  assert_no_symlink_components "$candidate"
  [[ ! -e "$candidate" && ! -L "$candidate" ]] || fail_usage "output directory already exists: $requested"
  printf '%s\n' "$canonical"
}

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
ensure_backup_root
if [[ -z "$output_dir" ]]; then
  backup_dir="$(resolve_output_path "backups/$backup_timestamp")"
else
  backup_dir="$(resolve_output_path "$output_dir")"
fi
mkdir -p -- "$(dirname -- "$backup_dir")"
mkdir -m 700 -- "$backup_dir"

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
  "$COMPOSE_SCRIPT" up -d --wait --wait-timeout "$WAIT_TIMEOUT" nuq-postgres redis rabbitmq || return 1
  printf 'restarting Firecrawl application services\n' >&2
  "$COMPOSE_SCRIPT" up -d --wait --wait-timeout "$WAIT_TIMEOUT" playwright-service api gateway || return 1
  "$VERIFY_LOCAL" || return 1
  "$RESOURCE_GUARD" post || return 1
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
  if (( status == 0 )); then
    printf 'backup created: %s\n' "$backup_dir"
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
  chmod 600 -- "$backup_dir/$archive"
done

compose_version="$("$COMPOSE_SCRIPT" version --short)"
git_commit="$(git -C "$ROOT" rev-parse HEAD)"
git_description="$(git -C "$ROOT" describe --tags --always)"
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
  while read -r checksum archive; do
    printf 'Archive SHA-256: %s  %s\n' "$checksum" "$archive"
  done < SHA256SUMS >> manifest.txt
)
