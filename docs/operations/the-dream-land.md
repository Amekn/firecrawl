# The-Dream-Land Firecrawl operations runbook

This runbook operates the pinned local Firecrawl deployment on `the-dream-land`.
Run commands from the repository unless a block says otherwise.

- Repository: `/home/kang/docker/firecrawl`
- Compose wrapper: `scripts/compose.sh`
- Local gateway: `http://127.0.0.1:3002`
- Public Funnel endpoint: `https://the-dream-land.taile6fad0.ts.net:10000`
- Open WebUI: `https://the-dream-land.taile6fad0.ts.net:8443`
- Nextcloud: `https://the-dream-land.taile6fad0.ts.net` (port `443`, tailnet-only)
- Persistent Firecrawl volumes: `firecrawl-postgres-data`, `firecrawl-redis-data`, and `firecrawl-rabbitmq-data`
- Secret files: `.env`, `secrets/api.env`, and `secrets/stack.env`; all must remain mode `600` and are never copied into tickets, chat, shell history, or logs.

## Safety rules

1. Never run `docker compose down -v`, `docker volume rm`, or an unreviewed destructive cleanup. Firecrawl rollback and restore preserve named volumes unless the operator explicitly approves a data replacement.
2. Do not restart Open WebUI, Nextcloud, SearXNG, Open Terminal, Hermes, Docker, or unrelated containers during Firecrawl maintenance.
3. Do not change Tailscale `443` or `8443`. Firecrawl owns only Funnel port `10000`.
4. Do not print `secrets/api.env`, `secrets/stack.env`, `.env`, bearer keys, PostgreSQL passwords, raw Tailscale JSON, or response bodies containing credentials.
5. A cold backup is verified by checksums and tar listings. Do not run a production restore merely to prove that an archive can be extracted.
6. Make a fresh backup before an upgrade, rollback, restore, key rotation, or Open WebUI configuration change.

The trust model is intentionally narrow: the gateway is the sole Open WebUI/host/public consumer ingress, and SearXNG is the one trusted direct provider-network peer on `firecrawl-search-network`. This segmentation does not claim that every packet from a compromised SearXNG process is gateway-authenticated; the provider peer is trusted for API search traffic, while consumer ingress remains gateway-authenticated.

## Status, logs, and safe diagnostics

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh ps
scripts/compose.sh ps --format '{{.Service}}\t{{.State}}\t{{.Health}}\t{{.ExitCode}}'
scripts/compose.sh logs --tail=100 api
scripts/compose.sh logs --tail=100 gateway
scripts/compose.sh logs --tail=100 playwright-service
scripts/compose.sh logs --tail=100 nuq-postgres redis rabbitmq
```

The following diagnostics expose status and counts, not secret values:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh exec -T nuq-postgres sh -lc \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT current_database(), (SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = ''public'');"'
scripts/compose.sh exec -T redis sh -lc 'redis-cli ping; redis-cli dbsize'
scripts/compose.sh exec -T rabbitmq sh -lc \
  'rabbitmq-diagnostics -q ping; rabbitmqctl list_queues name messages_ready messages_unacknowledged --formatter pretty_table'
for volume in firecrawl-postgres-data firecrawl-redis-data firecrawl-rabbitmq-data; do
  docker volume inspect "$volume" --format '{{.Name}}\t{{.Mountpoint}}'
done
```

The PostgreSQL role and database are supplied by the container environment. If a shell does not expand them, inspect only the variable names and use the rendered non-secret values; never print `POSTGRES_PASSWORD`.

## Start, stop, and restart

Start stateful services first, then the application services. Confirm the installed Compose contract once before relying on the bounded wait flags; this is read-only and must report both options:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/compose.sh up --help | python3 -c 'import sys; t=sys.stdin.read(); missing=[x for x in ("--wait", "--wait-timeout") if x not in t]; print("Compose wait flags: PASS" if not missing else "missing=" + ",".join(missing)); raise SystemExit(bool(missing))'
scripts/compose.sh up -d --wait --wait-timeout 300 nuq-postgres redis rabbitmq
scripts/compose.sh up -d --wait --wait-timeout 300 playwright-service api gateway
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Stop only Firecrawl services, in reverse dependency order:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
```

For a controlled Firecrawl restart, use the same stop/start sequence rather than restarting the entire Compose project. The bounded wait completes before verification:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d --wait --wait-timeout 300 nuq-postgres redis rabbitmq playwright-service api gateway
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Compose's `--wait --wait-timeout 300` waits for services to be running or healthy before returning. A prior Task 9 recovery recorded a transient `healthz: ERROR` while the gateway was still `starting`; that historical result is expected before the bounded wait and is not a reason to restart a healthy stack. If the 300-second deadline expires, collect `scripts/compose.sh ps` and non-secret service logs, then stop rather than treating the verification as a passed or ordinary transient start.

`scripts/resource-guard.sh` enforces the exact 3 GiB pre-build and 6 GiB post-start available-RAM thresholds and a rapid swap-growth ceiling of `131072 KiB/minute` (128 MiB/minute). It stores the last valid timestamp and swap-used sample atomically in mode-`600` `state/resource-guard-swap.state` beneath the ignored mode-`700` `state/` directory; `FIRECRAWL_SWAP_STATE_FILE`, `SWAP_USED_KIB`, `SWAP_TIMESTAMP`, and `SWAP_GROWTH_THRESHOLD_KIB_PER_MINUTE` are test overrides. A malformed state or non-increasing timestamp fails closed.

Do not use `docker compose down` for routine maintenance. The stop/start recovery above leaves all named volumes attached.

## Local, Funnel, and protected-service verification

Local verification checks the gateway health endpoint, unauthenticated and wrong-key `401` responses, authenticated readiness, search, scrape Markdown, and the SearXNG backend marker:

```bash
cd /home/kang/docker/firecrawl
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Funnel verification checks public `401`/`200` authentication and asserts that the current Tailscale configuration is the recorded baseline plus exactly Firecrawl port `10000`:

```bash
cd /home/kang/docker/firecrawl
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
```

The committed MCP verifier must print only the tool count and `PASS`; it must not print the key or raw diagnostics. Check the existing applications without modifying their routes:

```bash
curl --fail --silent --show-error \
  https://the-dream-land.taile6fad0.ts.net:8443/health >/dev/null
curl --fail --silent --show-error \
  https://the-dream-land.taile6fad0.ts.net/status.php >/dev/null
```

For a status snapshot, save JSON to a mode-`700` local state directory and inspect it with a purpose-built parser; do not paste raw JSON into a report:

```bash
cd /home/kang/docker/firecrawl
install -d -m 700 state
umask 077
tailscale serve status --json > state/tailscale-live.json
sha256sum state/tailscale-live.json
```

The baseline hash and the port-by-port preservation check belong in the deployment record, not the raw status document.

## Retrieving and using the API key safely

The key is stored only in `/home/kang/docker/firecrawl/secrets/api.env`. For a local interactive TTY, retrieve it as the `kang` user and do not paste the output into chat or a shared terminal log:

```bash
sudo -u kang -- cat /home/kang/docker/firecrawl/secrets/api.env
```

For a trusted SSH session, run the same read on the target host; do not put the key in an SSH command argument, URL, process list, or shell history:

```bash
ssh -T kang@the-dream-land \
  'sudo -u kang -- cat /home/kang/docker/firecrawl/secrets/api.env'
```

Prefer an in-process check that never displays the key:

```bash
sudo -u kang -- bash -lc '
  set -euo pipefail
  set -a
  . /home/kang/docker/firecrawl/secrets/api.env
  set +a
  curl --silent --show-error --output /dev/null --write-out "readiness=%{http_code}\n" \
    -H "Authorization: Bearer ${FIRECRAWL_API_KEY}" \
    http://127.0.0.1:3002/v0/health/readiness
'
```

Never transmit the generated key through Telegram, a ticket, a commit, or a command such as `curl -H 'Authorization: Bearer <literal-key>'`.

## Rotating the Firecrawl key

Key rotation is a coordinated change because both the gateway and Open WebUI use the key. Schedule a short outage, make a fresh Firecrawl and Open WebUI backup, and stop only the gateway and Open WebUI before replacing the key. The backup gate below must complete successfully before any persisted Open WebUI retrieval setting is changed; do not continue to the stop or mutation steps if it exits nonzero. No secret, database value, or backup contents are printed.

1. Confirm the installed Compose wait contract, record the current revision, and create hard-gated Firecrawl and Open WebUI backups:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/compose.sh up --help | python3 -c 'import sys; t=sys.stdin.read(); missing=[x for x in ("--wait", "--wait-timeout") if x not in t]; print("Firecrawl Compose wait flags: PASS" if not missing else "missing=" + ",".join(missing)); raise SystemExit(bool(missing))'
docker compose -f /home/kang/docker/open-webui/compose.yaml up --help | python3 -c 'import sys; t=sys.stdin.read(); missing=[x for x in ("--wait", "--wait-timeout") if x not in t]; print("Open WebUI Compose wait flags: PASS" if not missing else "missing=" + ",".join(missing)); raise SystemExit(bool(missing))'
git rev-parse HEAD
scripts/backup.sh
umask 077
BACKUP_ROOT=/home/kang/docker/firecrawl/backups/open-webui
BACKUP_DIR="/home/kang/docker/firecrawl/backups/open-webui/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$BACKUP_DIR"
cp -- /home/kang/docker/open-webui/compose.yaml "$BACKUP_DIR/compose.yaml"
chmod 600 "$BACKUP_DIR/compose.yaml"
OPEN_WEBUI_CONTAINER="$(docker compose -f /home/kang/docker/open-webui/compose.yaml ps -q open-webui)"
test -n "$OPEN_WEBUI_CONTAINER"
TMP_IN_CONTAINER=/tmp/task-9-open-webui-webui.db
cleanup_open_webui_tmp() { docker exec "$OPEN_WEBUI_CONTAINER" rm -f -- "$TMP_IN_CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup_open_webui_tmp EXIT
docker exec "$OPEN_WEBUI_CONTAINER" rm -f -- "$TMP_IN_CONTAINER"
docker exec "$OPEN_WEBUI_CONTAINER" python3 -c 'import sqlite3, sys; source=sqlite3.connect("file:/app/backend/data/webui.db?mode=ro", uri=True); target=sqlite3.connect(sys.argv[1]); source.backup(target); target.close(); source.close()' "$TMP_IN_CONTAINER"
docker cp "$OPEN_WEBUI_CONTAINER:$TMP_IN_CONTAINER" "$BACKUP_DIR/webui.db"
chmod 600 "$BACKUP_DIR/webui.db"
docker exec "$OPEN_WEBUI_CONTAINER" rm -f -- "$TMP_IN_CONTAINER"
trap - EXIT
python3 -c 'import sqlite3, sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True); result=c.execute("PRAGMA integrity_check").fetchone()[0]; c.close(); print("Open WebUI SQLite integrity: "+result); raise SystemExit(0 if result == "ok" else 1)' "$BACKUP_DIR/webui.db"
(
  cd "$BACKUP_DIR"
  sha256sum compose.yaml webui.db > SHA256SUMS
  chmod 600 SHA256SUMS
  sha256sum -c SHA256SUMS
)
```

The sequence uses SQLite's online backup API inside the running `open-webui` container, copies only the temporary database to the mode-`700` backup directory, removes the in-container temporary copy, keeps `compose.yaml`, `webui.db`, and `SHA256SUMS` mode `600`, and aborts on any failed checksum or read-only `PRAGMA integrity_check`.

2. Stop the two consumers, rotate the key, update persisted settings, and verify both authentication generations. Capture the old key only in the local shell variable before the atomic replacement; the helper below feeds headers through stdin so neither key is placed in an external process argument or log:

```bash
set -euo pipefail
set +x
old_key=''
new_key=''
cleanup_rotation() { unset old_key new_key; }
trap cleanup_rotation EXIT
cd /home/kang/docker/firecrawl
old_key="$(python3 - secrets/api.env <<'PY'
from pathlib import Path
import sys
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("FIRECRAWL_API_KEY=") and line.split("=", 1)[1]:
        print(line.split("=", 1)[1], end="")
        break
else:
    raise SystemExit("missing API key")
PY
)"
test -n "$old_key"
scripts/compose.sh stop gateway
docker compose -f /home/kang/docker/open-webui/compose.yaml stop open-webui
umask 077
temporary="$(mktemp secrets/api.env.XXXXXX)"
python3 -c 'import secrets; print("FIRECRAWL_API_KEY=" + secrets.token_hex(32))' > "$temporary"
chmod 600 "$temporary"
mv -f -- "$temporary" secrets/api.env

docker compose -f /home/kang/docker/open-webui/compose.yaml \
  --env-file /home/kang/docker/open-webui/.env \
  --env-file /home/kang/docker/firecrawl/secrets/api.env \
  up -d --wait --wait-timeout 300 --no-deps open-webui
docker compose -f /home/kang/docker/open-webui/compose.yaml \
  --env-file /home/kang/docker/open-webui/.env \
  --env-file /home/kang/docker/firecrawl/secrets/api.env \
  exec -T open-webui sh -lc \
  'FIRECRAWL_API_BASE_URL=http://firecrawl-gateway:8080 \
   OPEN_WEBUI_DB_PATH=/app/backend/data/webui.db \
   python3 -' < scripts/configure-open-webui.py
scripts/compose.sh up -d --wait --wait-timeout 300 gateway
new_key="$(python3 - secrets/api.env <<'PY'
from pathlib import Path
import sys
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("FIRECRAWL_API_KEY=") and line.split("=", 1)[1]:
        print(line.split("=", 1)[1], end="")
        break
else:
    raise SystemExit("missing API key")
PY
)"
test -n "$new_key"
check_key() {
  local key="$1"
  printf 'header = "Authorization: Bearer %s"\n' "$key" | \
    curl --config - --silent --show-error --output /dev/null --write-out '%{http_code}' \
      http://127.0.0.1:3002/v0/health/readiness
}
old_status="$(check_key "$old_key")"
new_status="$(check_key "$new_key")"
test "$old_status" = 401
test "$new_status" = 200
printf 'key rotation auth gate: old=401 new=200\n'

docker compose -f /home/kang/docker/open-webui/compose.yaml \
  --env-file /home/kang/docker/open-webui/.env \
  --env-file /home/kang/docker/firecrawl/secrets/api.env \
  exec -T open-webui python3 - <<'PY'
import json
import sqlite3

connection = sqlite3.connect("file:/app/backend/data/webui.db?mode=ro", uri=True)
connection.execute("PRAGMA query_only=ON")
rows = dict(connection.execute(
    "SELECT key, value FROM config WHERE key IN (?, ?, ?, ?, ?)",
    (
        "web.search.engine",
        "web.loader.engine",
        "web.loader.firecrawl_api_url",
        "web.loader.firecrawl_api_key",
        "web.loader.firecrawl_timeout",
    ),
))
connection.close()
expected = {
    "web.search.engine": "firecrawl",
    "web.loader.engine": "firecrawl",
    "web.loader.firecrawl_api_url": "http://firecrawl-gateway:8080",
    "web.loader.firecrawl_timeout": "120",
}
if set(rows) != set(expected) | {"web.loader.firecrawl_api_key"}:
    raise SystemExit("Open WebUI persisted setting set mismatch")
for key, value in expected.items():
    if json.loads(rows[key]) != value:
        raise SystemExit("Open WebUI persisted setting mismatch")
if not json.loads(rows["web.loader.firecrawl_api_key"]):
    raise SystemExit("Open WebUI Firecrawl key is not set")
print("Open WebUI settings: engine=firecrawl base_url=http://firecrawl-gateway:8080 timeout=120 firecrawl_api_key=set")
PY
scripts/verify-local.sh
scripts/resource-guard.sh post
curl --fail --silent --show-error http://127.0.0.1:3000/health >/dev/null
unset old_key new_key
trap - EXIT
```

A rotation is complete only when the old key returns `401`, the new key returns `200`, the read-only SQLite check validates exactly the five settings above while reporting only `firecrawl_api_key=set`, local Firecrawl verification passes, and the browser/manual search is confirmed separately. No final gate is masked with `|| true`.

## Cold backup and non-destructive inspection

Create a cold backup of all three persistent Firecrawl volumes. The script stops and restarts Firecrawl services only:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/backup.sh
latest="$(python3 -c 'from pathlib import Path; candidates=[p for p in Path("backups").iterdir() if p.is_dir() and p.name[:1].isdigit()]; print(max(candidates, key=lambda p:p.stat().st_mtime).resolve())')"
```

Verify hashes from inside the backup directory. Running `sha256sum -c "$latest/SHA256SUMS"` from the repository root is not sufficient because the checksum file contains archive basenames; use the corrected working-directory form:

```bash
cd /home/kang/docker/firecrawl
latest="$(python3 -c 'from pathlib import Path; candidates=[p for p in Path("backups").iterdir() if p.is_dir() and p.name[:1].isdigit()]; print(max(candidates, key=lambda p:p.stat().st_mtime).resolve())')"
(
  cd "$latest"
  sha256sum -c SHA256SUMS
)
for archive in postgres.tar.gz redis.tar.gz rabbitmq.tar.gz; do
  test -s "$latest/$archive"
  tar -tzf "$latest/$archive" >/dev/null
  printf '%s: tar listing PASS\n' "$archive"
done
stat -c '%n %s bytes' "$latest"/*.tar.gz "$latest/manifest.txt" "$latest/SHA256SUMS"
```

Expected artifacts are `postgres.tar.gz`, `redis.tar.gz`, and `rabbitmq.tar.gz`, plus `manifest.txt` and `SHA256SUMS`. Keep the backup directory mode `700`. Record the exact absolute path and archive hashes in the deployment record, but never record the archive contents or secret files.

## Restore procedure (explicit confirmation required)

A restore replaces the contents of the three named volumes. It is not a routine extraction test. Only run it during an approved recovery window after confirming the target path and accepting the data-loss implications.

1. Resolve and inspect a backup without changing production. Use checksum and tar-listing verification above.
2. Obtain explicit operator confirmation in the change record, then set a shell-local confirmation variable. Do not put a key in the command:

```bash
cd /home/kang/docker/firecrawl
export I_UNDERSTAND_FIRECRAWL_RESTORE=YES
test "$I_UNDERSTAND_FIRECRAWL_RESTORE" = YES
restore_dir='backups/YYYYMMDDTHHMMSSZ'
test -d "$restore_dir"
```

3. The restore script refuses to run while any Firecrawl container is active, creates a safety backup, validates the manifest/checksums/archives, replaces volume contents, restarts Firecrawl, and reruns local verification:

```bash
set -euo pipefail
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
I_UNDERSTAND_FIRECRAWL_RESTORE=YES scripts/restore.sh "$restore_dir" --confirm
scripts/compose.sh ps
scripts/resource-guard.sh post
```

Do not run `scripts/restore.sh` merely to prove that a tarball extracts. The Task 9 production backup was verified by `sha256sum` and `tar -tzf`; no production restore was run.

## Firecrawl upgrade: review, sequential rebuild, and verification

Upgrade only to a reviewed branch or tag. Keep the current revision and a fresh cold backup for rollback, and never delete the named volumes.

1. Review the candidate before changing the deployment branch:

```bash
cd /home/kang/docker/firecrawl
git status --short --branch
git fetch --tags origin
git log --oneline --decorate -10
git show --stat --oneline CANDIDATE_REF
git diff --stat HEAD...CANDIDATE_REF
```

Replace `CANDIDATE_REF` only after reviewing its Compose, migrations, image tags, health checks, resource settings, and release notes. Create or switch to a dedicated local branch; do not modify global Git configuration. Every direct runtime image refreshed below must remain digest-pinned; stop if the reviewed Compose renders a floating image.

2. Back up and record the current revision:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
git rev-parse HEAD > state/firecrawl-before-upgrade.commit
scripts/backup.sh
scripts/resource-guard.sh pre
scripts/compose.sh config --quiet
```

3. After the candidate review, pull direct runtime images sequentially. The resource guard runs between every pull; no floating image is accepted:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
for service in redis rabbitmq gateway; do
  image="$(scripts/compose.sh config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")"
  case "$image" in
    *@sha256:*) printf 'reviewed digest-pinned image: %s=%s\n' "$service" "$image" ;;
    *) printf 'refusing non-digest-pinned image for %s\n' "$service" >&2; exit 1 ;;
  esac
done
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh pull redis
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh pull rabbitmq
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh pull gateway
scripts/resource-guard.sh pre
```

4. Rebuild source images one at a time with the pre-build resource guard between each build. The deployment Dockerfiles use the reviewed immutable Node, PostgreSQL, and Go base digests. Versioned external build downloads remain a separate provenance limitation; this wave records that limitation and does not invent checksums for those upstream artifacts:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build nuq-postgres
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build playwright-service
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build api
scripts/resource-guard.sh pre
```

5. Inspect and record the direct image IDs and repository digests before restarting. This records the reviewed, pulled images without printing credentials:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
install -d -m 700 state
umask 077
record_upgrade_images() {
  destination="$1"
  : > "$destination"
  for service in redis rabbitmq gateway; do
    image="$(scripts/compose.sh config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")"
    test -n "$image"
    case "$image" in
      *@sha256:*) ;;
      *) printf 'refusing non-digest-pinned image for %s\n' "$service" >&2; return 1 ;;
    esac
    printf 'service=%s image=%s ' "$service" "$image" >> "$destination"
    docker image inspect "$image" --format 'image_id={{.Id}} repo_digests={{join .RepoDigests ","}}' >> "$destination"
  done
}
record_upgrade_images state/upgrade-images-before.txt
```

6. Stop and start Firecrawl only, preserving the existing volumes. The bounded wait must complete before the post-upgrade gates:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d --wait --wait-timeout 300 nuq-postgres redis rabbitmq playwright-service api gateway
record_upgrade_images() {
  destination="$1"
  : > "$destination"
  for service in redis rabbitmq gateway; do
    image="$(scripts/compose.sh config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$service")"
    test -n "$image"
    case "$image" in
      *@sha256:*) ;;
      *) printf 'refusing non-digest-pinned image for %s\n' "$service" >&2; return 1 ;;
    esac
    printf 'service=%s image=%s ' "$service" "$image" >> "$destination"
    docker image inspect "$image" --format 'image_id={{.Id}} repo_digests={{join .RepoDigests ","}}' >> "$destination"
  done
}
record_upgrade_images state/upgrade-images-after.txt
```

7. Rerun the complete repository and runtime gates:

```bash
cd /home/kang/docker/firecrawl
python -m unittest discover -s deploy/tests -v
scripts/compose.sh config --quiet
scripts/verify-local.sh
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
scripts/resource-guard.sh post
git diff --check
```

Do not upgrade through an unreviewed floating `latest`, do not recreate unrelated services, and do not run `docker compose down -v`. If any gate fails, stop the Firecrawl application services and follow the full rollback procedure below. Keep both image-record files with the deployment evidence.

## Disable only Firecrawl Funnel port 10000

This disables public Firecrawl access while preserving the `443` Nextcloud and `8443` Open WebUI routes. Do not use `tailscale serve reset` or an unqualified Funnel command:

```bash
set -euo pipefail
tailscale funnel --https=10000 off
tailscale funnel status --json > /home/kang/docker/firecrawl/state/funnel-after-disable.json
sha256sum /home/kang/docker/firecrawl/state/funnel-after-disable.json
```

Verify the protected services, without printing raw JSON:

```bash
curl --fail --silent --show-error \
  https://the-dream-land.taile6fad0.ts.net:8443/health >/dev/null
curl --fail --silent --show-error \
  https://the-dream-land.taile6fad0.ts.net/status.php >/dev/null
tailscale serve status
```

To re-enable only the Firecrawl route after local verification succeeds:

```bash
set -euo pipefail
tailscale funnel --bg --yes --https=10000 http://127.0.0.1:3002
cd /home/kang/docker/firecrawl
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
```

## Roll Open WebUI back to direct SearXNG

Direct-SearXNG rollback intentionally uses the Task 7 pre-Firecrawl backup `/home/kang/docker/firecrawl/backups/open-webui/20260820T120549Z/` because it restores SearXNG retrieval. The fresh final-fix backup `/home/kang/docker/firecrawl/backups/open-webui/20260820T150716Z/` is the rollback point for the later network-segmentation change and preserves Firecrawl retrieval; it is not a direct-SearXNG rollback source. Both are outside the Open WebUI repository. Use the Task 7 backup by default for this direct-SearXNG procedure, or an explicitly approved timestamped directory beneath the same backup root. This procedure changes Open WebUI only; it does not stop Firecrawl or modify Tailscale.

1. Set the approved absolute backup path, reject symlinks/non-directories, and verify its files, hashes, and SQLite integrity before stopping or restoring anything:

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
export OPEN_WEBUI_ROLLBACK_CONFIRM=YES
BACKUP_ROOT=/home/kang/docker/firecrawl/backups/open-webui
BACKUP_DIR="${OPEN_WEBUI_BACKUP_DIR:-$BACKUP_ROOT/20260820T120549Z}"
test "$OPEN_WEBUI_ROLLBACK_CONFIRM" = YES
case "$BACKUP_DIR" in
  "$BACKUP_ROOT"/*) ;;
  *) printf 'backup must remain beneath %s\n' "$BACKUP_ROOT" >&2; exit 1 ;;
esac
test -d "$BACKUP_DIR"
test ! -L "$BACKUP_DIR"
test "$(realpath -e -- "$BACKUP_DIR")" = "$BACKUP_DIR"
for name in compose.yaml webui.db SHA256SUMS; do
  test -f "$BACKUP_DIR/$name"
  test ! -L "$BACKUP_DIR/$name"
  test -s "$BACKUP_DIR/$name"
done
if python3 - "$BACKUP_DIR/SHA256SUMS" <<'PY'
from pathlib import Path
import sys
entries = [line.split(maxsplit=1)[1] for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
raise SystemExit(0 if entries and all(Path(entry).parent == Path('.') for entry in entries) else 1)
PY
then
  (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
else
  (cd /home/kang/docker/firecrawl && sha256sum -c "$BACKUP_DIR/SHA256SUMS")
fi
python3 -c 'import sqlite3, sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True); result=c.execute("PRAGMA integrity_check").fetchone()[0]; c.close(); print("Open WebUI SQLite integrity: "+result); raise SystemExit(0 if result == "ok" else 1)' "$BACKUP_DIR/webui.db"
```

The normal rollback manifest is checked with `(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)`. The retained Task 7 manifest records repository-relative paths, so the read-only fallback runs the same manifest from `/home/kang/docker/firecrawl`; both branches verify the exact absolute backup without changing it. Do not stop Open WebUI or copy any file until every validation command passes.

2. Stop only Open WebUI, restore the timestamped Compose/DB backup using absolute paths, and start only Open WebUI with a bounded wait:

```bash
set -euo pipefail
set +x
unset BACKUP_HELPER_IMAGE
cleanup_helper_image() { unset BACKUP_HELPER_IMAGE; }
trap cleanup_helper_image EXIT
BACKUP_HELPER_IMAGE="$(
python3 - /home/kang/docker/firecrawl/.env <<'PY'
from pathlib import Path
import re
import sys

value = None
for line_number, line in enumerate(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(), 1):
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        raise SystemExit(f"malformed .env line {line_number}")
    key, candidate = line.split("=", 1)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or candidate != candidate.strip():
        raise SystemExit(f"malformed .env line {line_number}")
    if key == "BACKUP_HELPER_IMAGE":
        if value is not None or not candidate:
            raise SystemExit("BACKUP_HELPER_IMAGE must occur exactly once with a non-empty value")
        value = candidate
if value is None:
    raise SystemExit("missing BACKUP_HELPER_IMAGE")
print(value)
PY
)"
case "$BACKUP_HELPER_IMAGE" in
  *@sha256:*) ;;
  *) printf 'BACKUP_HELPER_IMAGE must be digest-pinned\n' >&2; exit 1 ;;
esac
docker compose -f /home/kang/docker/open-webui/compose.yaml stop open-webui
cp -- "$BACKUP_DIR/compose.yaml" /home/kang/docker/open-webui/compose.yaml
docker run --rm \
  -v open-webui-data:/data \
  -v "$BACKUP_DIR:/backup:ro" \
  "$BACKUP_HELPER_IMAGE" sh -eu -c 'cp /backup/webui.db /data/webui.db'
unset BACKUP_HELPER_IMAGE
trap - EXIT
docker compose -f /home/kang/docker/open-webui/compose.yaml config --quiet
docker compose -f /home/kang/docker/open-webui/compose.yaml up -d --wait --wait-timeout 300 --no-deps open-webui
```

3. Verify Open WebUI and direct SearXNG, while leaving the Firecrawl stack and Funnel unchanged:

```bash
set -euo pipefail
healthy=0
for (( attempt=1; attempt<=60; attempt++ )); do
  if curl --fail --silent --connect-timeout 5 --max-time 10 http://127.0.0.1:3000/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 5
done
if (( ! healthy )); then
  printf 'FAIL: Open WebUI did not become healthy\n' >&2
  docker compose -f /home/kang/docker/open-webui/compose.yaml ps open-webui >&2
  docker compose -f /home/kang/docker/open-webui/compose.yaml logs --tail=100 open-webui >&2
  exit 1
fi
curl --fail --silent --show-error --connect-timeout 5 --max-time 10 http://127.0.0.1:3000/health >/dev/null
docker compose -f /home/kang/docker/open-webui/compose.yaml logs --since=5m open-webui searxng
tailscale serve status
```

The restored database is the pre-cutover database, so it restores the prior SearXNG retrieval settings and unrelated Open WebUI rows together. Do not manually delete rows from `webui.db` unless a separate migration is reviewed and backed up.

## Full Firecrawl rollback without deleting volumes

Use this after an upgrade or configuration change fails. It restores the repository revision and images, not the data. A data replacement is a separate, explicitly confirmed restore procedure.

```bash
set -euo pipefail
cd /home/kang/docker/firecrawl
ROLLBACK_REF='KNOWN_GOOD_REF'
test -n "$ROLLBACK_REF"
git status --short --branch
scripts/backup.sh
git switch --detach "$ROLLBACK_REF"
scripts/compose.sh config --quiet
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build nuq-postgres
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build playwright-service
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build api
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d --wait --wait-timeout 300 nuq-postgres redis rabbitmq playwright-service api gateway
scripts/verify-local.sh
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
scripts/resource-guard.sh post
```

This rollback intentionally uses `stop`/`up` and retains `firecrawl-postgres-data`, `firecrawl-redis-data`, and `firecrawl-rabbitmq-data`. Never add `-v`, remove the volumes, or alter ports `443` and `8443`. If the candidate changed a database schema incompatibly, stop and use the separately confirmed restore procedure rather than improvising a migration.

## Complete acceptance suite

Run from `/home/kang/docker/firecrawl` after any recovery, upgrade, rollback, or Funnel change:

```bash
cd /home/kang/docker/firecrawl
python -m unittest discover -s deploy/tests -v
scripts/compose.sh config --quiet
scripts/verify-local.sh
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
scripts/resource-guard.sh post
git diff --check
scripts/compose.sh ps
docker ps --format '{{.Names}}\t{{.Status}}'
tailscale serve status --json > state/tailscale-live.json
free -h
```

Acceptance requires all automated commands to pass, at least 6 GiB available RAM, no active FoundationDB container, all Firecrawl services healthy, and existing Nextcloud/Open WebUI/Open Terminal/SearXNG services healthy. A browser Open WebUI search remains a separate manual criterion: do not mark it complete until a user confirms that results appeared and Firecrawl logs showed search plus page-scrape activity.
