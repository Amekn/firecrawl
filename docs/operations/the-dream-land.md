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

Start stateful services first, then the application services. Wait for the health states before calling the verification scripts:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh up -d nuq-postgres redis rabbitmq
scripts/compose.sh up -d playwright-service api gateway
scripts/compose.sh ps
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Stop only Firecrawl services, in reverse dependency order:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
```

For a controlled Firecrawl restart, use the same stop/start sequence rather than restarting the entire Compose project:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d nuq-postgres redis rabbitmq playwright-service api gateway
```

Compose may report `up` before the gateway listener is ready. Poll `scripts/compose.sh ps` until `api`, `gateway`, `nuq-postgres`, `redis`, and `rabbitmq` are healthy, then run:

```bash
cd /home/kang/docker/firecrawl
scripts/verify-local.sh
scripts/resource-guard.sh post
```

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

Key rotation is a coordinated change because both the gateway and Open WebUI use the key. Schedule a short outage, make a fresh Firecrawl and Open WebUI backup, and stop only the gateway and Open WebUI before replacing the key.

1. Record the current git revision and create a Firecrawl backup:

```bash
cd /home/kang/docker/firecrawl
git rev-parse HEAD
scripts/backup.sh
```

2. Stop the two consumers. Do not stop SearXNG, Nextcloud, Hermes, or other services:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway
cd /home/kang/docker/open-webui
docker compose stop open-webui
```

3. Generate a new 256-bit hex key into a mode-`600` temporary file and atomically replace only `api.env`. The key is never printed:

```bash
cd /home/kang/docker/firecrawl
umask 077
temporary="$(mktemp secrets/api.env.XXXXXX)"
python3 -c 'import secrets; print("FIRECRAWL_API_KEY=" + secrets.token_hex(32))' > "$temporary"
chmod 600 "$temporary"
mv -f -- "$temporary" secrets/api.env
stat -c '%a %n' secrets/api.env
```

4. Start Open WebUI and update its persisted five-key retrieval configuration from the container environment. The helper source is piped in; the new key is not a command-line argument and is not printed:

```bash
cd /home/kang/docker/open-webui
docker compose up -d --no-deps open-webui
cd /home/kang/docker/firecrawl
docker compose -f /home/kang/docker/open-webui/compose.yaml \
  --env-file /home/kang/docker/open-webui/.env \
  --env-file /home/kang/docker/firecrawl/secrets/api.env \
  exec -T open-webui sh -lc \
  'FIRECRAWL_API_BASE_URL=http://firecrawl-gateway:8080 \
   OPEN_WEBUI_DB_PATH=/app/backend/data/webui.db \
   python3 -' < scripts/configure-open-webui.py
scripts/compose.sh up -d gateway
```

If the Open WebUI container does not contain Python, use the repository's existing migration procedure to run `scripts/configure-open-webui.py` against the mounted Open WebUI database; do not put the key in a command argument or temporary world-readable file.

5. Verify the new key without exposing it, then run the local and Open WebUI checks:

```bash
cd /home/kang/docker/firecrawl
scripts/verify-local.sh
scripts/resource-guard.sh post
cd /home/kang/docker/open-webui
curl --fail --silent --show-error http://127.0.0.1:3000/health >/dev/null
docker compose logs --since=5m open-webui | grep -F 'firecrawl' || true
```

A rotation is complete only when gateway readiness is `200` with the new key, the old key is rejected, persisted Open WebUI settings report `web.loader.firecrawl_api_key=set`, and the browser/manual search is confirmed separately.

## Cold backup and non-destructive inspection

Create a cold backup of all three persistent Firecrawl volumes. The script stops and restarts Firecrawl services only:

```bash
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

Replace `CANDIDATE_REF` only after reviewing its Compose, migrations, image tags, health checks, resource settings, and release notes. Create or switch to a dedicated local branch; do not modify global Git configuration.

2. Back up and record the current revision:

```bash
cd /home/kang/docker/firecrawl
git rev-parse HEAD > state/firecrawl-before-upgrade.commit
scripts/backup.sh
scripts/resource-guard.sh pre
scripts/compose.sh config --quiet
```

3. Rebuild source images one at a time with the pre-build resource guard between each build. Direct images may be pulled only after review:

```bash
cd /home/kang/docker/firecrawl
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build nuq-postgres
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build playwright-service
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build api
scripts/resource-guard.sh pre
```

4. Stop and start Firecrawl only, preserving the existing volumes:

```bash
cd /home/kang/docker/firecrawl
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d nuq-postgres redis rabbitmq playwright-service api gateway
```

5. Wait for health, then rerun the complete repository and runtime gates:

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

Do not upgrade through an unreviewed floating `latest`, do not recreate unrelated services, and do not run `docker compose down -v`. If any gate fails, stop the Firecrawl application services and follow the full rollback procedure below.

## Disable only Firecrawl Funnel port 10000

This disables public Firecrawl access while preserving the `443` Nextcloud and `8443` Open WebUI routes. Do not use `tailscale serve reset` or an unqualified Funnel command:

```bash
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
tailscale funnel --bg --yes --https=10000 http://127.0.0.1:3002
cd /home/kang/docker/firecrawl
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
```

## Roll Open WebUI back to direct SearXNG

The Open WebUI cutover backup contains a timestamped `compose.yaml` and SQLite `webui.db`. Use the backup made immediately before the Firecrawl cutover, not an unverified copy. This procedure changes Open WebUI only; it does not stop Firecrawl or modify Tailscale.

1. Set the approved backup path and verify its files and hashes:

```bash
cd /home/kang/docker/open-webui
export OPEN_WEBUI_ROLLBACK_CONFIRM=YES
BACKUP_DIR='backups/open-webui/YYYYMMDDTHHMMSSZ'
test "$OPEN_WEBUI_ROLLBACK_CONFIRM" = YES
test -s "$BACKUP_DIR/compose.yaml"
test -s "$BACKUP_DIR/webui.db"
sha256sum -c "$BACKUP_DIR/SHA256SUMS"
```

2. Stop only Open WebUI, restore the timestamped Compose/DB backup, and start only Open WebUI:

```bash
docker compose stop open-webui
cp -- "$BACKUP_DIR/compose.yaml" compose.yaml
docker run --rm \
  -v open-webui-data:/data \
  -v "$PWD/$BACKUP_DIR:/backup:ro" \
  alpine:3.20 sh -eu -c 'cp /backup/webui.db /data/webui.db'
docker compose config --quiet
docker compose up -d --no-deps open-webui
```

3. Verify Open WebUI and direct SearXNG, while leaving the Firecrawl stack and Funnel unchanged:

```bash
until curl --fail --silent http://127.0.0.1:3000/health >/dev/null; do sleep 5; done
curl --fail --silent --show-error http://127.0.0.1:3000/health >/dev/null
docker compose logs --since=5m open-webui searxng
tailscale serve status
```

The restored database is the pre-cutover database, so it restores the prior SearXNG retrieval settings and unrelated Open WebUI rows together. Do not manually delete rows from `webui.db` unless a separate migration is reviewed and backed up.

## Full Firecrawl rollback without deleting volumes

Use this after an upgrade or configuration change fails. It restores the repository revision and images, not the data. A data replacement is a separate, explicitly confirmed restore procedure.

```bash
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
scripts/compose.sh up -d nuq-postgres redis rabbitmq playwright-service api gateway
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
