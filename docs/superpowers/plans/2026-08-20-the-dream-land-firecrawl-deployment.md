# The-Dream-Land Firecrawl Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy an authenticated, persistent, resource-limited Firecrawl `v2.11.162` stack on `the-dream-land`, integrate Open WebUI through internal Docker networking, and expose Firecrawl through Tailscale Funnel port `10000` without disturbing Nextcloud, Open WebUI, or Hermes.

**Architecture:** Firecrawl API/workers, Playwright, Redis, RabbitMQ, and NuQ PostgreSQL run on a private Docker network. An unprivileged Nginx gateway is the only host-published service, validates a generated Bearer key, and binds to `127.0.0.1:3002`; Tailscale Funnel `:10000` forwards to it. Firecrawl uses the existing internal SearXNG service, while Open WebUI reaches the gateway over `open-webui-network`.

**Tech Stack:** Docker Compose v5.3.1, Firecrawl v2.11.162, Nginx Unprivileged 1.29.1 Alpine, Redis, RabbitMQ, NuQ PostgreSQL, Python 3 stdlib tests, Bash operational scripts, Tailscale 1.98.8, Open WebUI v0.11.0.

**Spec:** `docs/superpowers/specs/2026-08-20-the-dream-land-firecrawl-deployment-design.md`

## Global Constraints

- Target host is `the-dream-land`; do not restart or destabilize Hermes Gateway, Nextcloud AIO, Open WebUI, Docker, or Tailscale.
- Firecrawl source stays pinned to Git tag `v2.11.162` on branch `local/the-dream-land-deployment`.
- Existing Tailscale handlers remain: `443` → Nextcloud tailnet-only and `8443` → Open WebUI Funnel.
- New public endpoint is exactly `https://the-dream-land.taile6fad0.ts.net:10000`.
- Firecrawl and every dependency except `gateway` have no host-published port.
- `gateway` publishes only `127.0.0.1:3002:8080`.
- SearXNG remains running and internal on `open-webui-network`.
- Fire Engine, Supabase authentication, FoundationDB, AI extraction, Ollama, and cloud API credentials are out of scope.
- Generate an independent 256-bit hexadecimal Bearer key and strong PostgreSQL password; never print either value.
- Secret files are mode `0600`, excluded from Git, and split into `secrets/api.env` and `secrets/stack.env`.
- Initial concurrency is one worker, one crawl request, one job, and one browser.
- Hard caps: API 1.5 CPU/3 GiB, Playwright 1 CPU/2 GiB, PostgreSQL 0.5 CPU/768 MiB, RabbitMQ 0.5 CPU/512 MiB, Redis 0.25 CPU/256 MiB, gateway 0.1 CPU/128 MiB.
- Abort before Open WebUI/Tailscale changes if available RAM falls below 3 GiB or swap rises rapidly; require at least 6 GiB available after idle settlement.
- PostgreSQL, Redis, and RabbitMQ use named persistent volumes and cold backup/restore scripts.
- Open WebUI is backed up before its Compose file or persisted retrieval config is changed.
- Do not deliver the generated API key through Telegram; retrieve it locally or over trusted SSH.
- Use repository-local Git identity only; do not modify global Git configuration.

## File Map

| File | Responsibility |
|---|---|
| `.gitignore` | Ignore generated secrets, deployment `.env`, backups, state snapshots, and verification output. |
| `.env.example` | Non-secret Compose values, concurrency, network endpoint, and pinned backup-helper image. |
| `deploy/examples/api.env.example` | Harmless 64-hex test API key. |
| `deploy/examples/stack.env.example` | Harmless test PostgreSQL password. |
| `deploy/nginx/default.conf.template` | Bearer authentication, rate limiting, health endpoint, and Firecrawl reverse proxy. |
| `compose.the-dream-land.yaml` | Resource limits, persistence, gateway, network joins, health checks, image pins, and FoundationDB profiles. |
| `scripts/generate-secrets.sh` | Idempotently create `.env`, `api.env`, and `stack.env` without printing values. |
| `scripts/compose.sh` | Consistently load base Compose, overlay, `.env`, and stack secrets. |
| `scripts/resource-guard.sh` | Enforce pre-start/build and post-start memory thresholds. |
| `scripts/verify-local.sh` | Test gateway health, 401 paths, readiness, search, scrape, and SearXNG selection. |
| `scripts/verify-funnel.sh` | Test public 401/readiness and preserve existing Tailscale route configuration. |
| `scripts/verify-mcp.py` | Spawn the official Firecrawl MCP adapter and call search through Funnel. |
| `scripts/backup.sh` | Cold archive the PostgreSQL, Redis, and RabbitMQ named volumes with hashes/manifest. |
| `scripts/restore.sh` | Safety-backup, replace named-volume contents, restart, and verify. |
| `deploy/tests/test_secrets.py` | Test secret generation, permissions, idempotency, and non-disclosure. |
| `deploy/tests/test_compose.py` | Test merged Compose invariants and resource/network/persistence policy. |
| `deploy/tests/test_gateway.py` | Test Nginx template authorization and proxy invariants statically. |
| `deploy/tests/test_scripts.py` | Test shell syntax, required safety gates, and backup/restore refusal behavior. |
| `docs/operations/the-dream-land.md` | Exact start, stop, update, key retrieval, backup, restore, rollback, and health commands. |
| `docs/operations/deployment-record.md` | Non-secret verified versions, image digests, route hashes, resource snapshots, and acceptance results. |

Pinned direct images for this plan:

```text
nginxinc/nginx-unprivileged:1.29.1-alpine@sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e
redis:alpine@sha256:978f0e01593e65eed801f2402944efcd936d43b5027e4908a7897baf88ed6241
rabbitmq:3-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69
alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1
```

---

### Task 1: Secret and Environment Scaffolding

**Files:**
- Modify: `.gitignore:4-6`
- Create: `.env.example`
- Create: `deploy/examples/api.env.example`
- Create: `deploy/examples/stack.env.example`
- Create: `scripts/generate-secrets.sh`
- Create: `deploy/tests/test_secrets.py`

**Interfaces:**
- Consumes: repository root discovered from `scripts/generate-secrets.sh`.
- Produces: `.env`, `secrets/api.env` containing `FIRECRAWL_API_KEY`, and `secrets/stack.env` containing `POSTGRES_PASSWORD`.

- [ ] **Step 1: Write the failing secret-generation tests**

Create `deploy/tests/test_secrets.py` with `unittest` cases that run the generator against a temporary `FIRECRAWL_ROOT` and assert:

```python
api = root / "secrets/api.env"
stack = root / "secrets/stack.env"
assert re.fullmatch(r"FIRECRAWL_API_KEY=[0-9a-f]{64}\n", api.read_text())
assert re.fullmatch(r"POSTGRES_PASSWORD=[0-9a-f]{64}\n", stack.read_text())
assert stat.S_IMODE(api.stat().st_mode) == 0o600
assert stat.S_IMODE(stack.stat().st_mode) == 0o600
assert result.stdout == ""
```

Run the script twice and assert the second run leaves both file hashes unchanged.

- [ ] **Step 2: Run the test and confirm failure**

Run:

```bash
python -m unittest deploy.tests.test_secrets -v
```

Expected: FAIL because `scripts/generate-secrets.sh` and example files do not exist.

- [ ] **Step 3: Add ignore rules and examples**

Append exactly:

```gitignore
# the-dream-land deployment state
/secrets/
/backups/
/state/
/verification-output/
```

Create `.env.example`:

```dotenv
COMPOSE_PROJECT_NAME=firecrawl
INTERNAL_PORT=3002
POSTGRES_USER=firecrawl
POSTGRES_DB=postgres
USE_DB_AUTHENTICATION=false
NUM_WORKERS_PER_QUEUE=1
CRAWL_CONCURRENT_REQUESTS=1
MAX_CONCURRENT_JOBS=1
BROWSER_POOL_SIZE=1
SEARXNG_ENDPOINT=http://searxng:8080
BLOCK_MEDIA=true
LOGGING_LEVEL=info
FIRECRAWL_API_ENV_FILE=./secrets/api.env
BACKUP_HELPER_IMAGE=alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1
```

Create `deploy/examples/api.env.example` with 64 zeroes and `deploy/examples/stack.env.example` with 64 ones. These are test fixtures only and must be labeled as non-secret examples.

- [ ] **Step 4: Implement the generator**

`scripts/generate-secrets.sh` must:

```bash
#!/usr/bin/env bash
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_ROOT="${FIRECRAWL_ROOT:-$REPO_ROOT}"
install -d -m 700 "$TARGET_ROOT/secrets"
[[ -f "$TARGET_ROOT/.env" ]] || install -m 600 "$REPO_ROOT/.env.example" "$TARGET_ROOT/.env"
python3 - "$TARGET_ROOT" <<'PY'
from pathlib import Path
import secrets, sys
root = Path(sys.argv[1])
for path, key in (
    (root / "secrets/api.env", "FIRECRAWL_API_KEY"),
    (root / "secrets/stack.env", "POSTGRES_PASSWORD"),
):
    if not path.exists():
        path.write_text(f"{key}={secrets.token_hex(32)}\n")
        path.chmod(0o600)
PY
```

Do not print paths or values.

- [ ] **Step 5: Run tests and syntax checks**

Run:

```bash
chmod +x scripts/generate-secrets.sh
bash -n scripts/generate-secrets.sh
python -m unittest deploy.tests.test_secrets -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example deploy/examples scripts/generate-secrets.sh deploy/tests/test_secrets.py
git commit -m "chore: add deployment secret scaffolding"
```

---

### Task 2: Compose Overlay and Static Invariant Tests

**Files:**
- Create: `compose.the-dream-land.yaml`
- Create: `scripts/compose.sh`
- Create: `deploy/tests/test_compose.py`

**Interfaces:**
- Consumes: `.env`, `secrets/stack.env`, `secrets/api.env`, upstream `docker-compose.yaml`, existing external network `open-webui-network`.
- Produces: merged Compose model with services `gateway`, `api`, `playwright-service`, `redis`, `rabbitmq`, and `nuq-postgres`; persistent volumes `firecrawl-postgres-data`, `firecrawl-redis-data`, and `firecrawl-rabbitmq-data`.

- [ ] **Step 1: Write failing Compose invariant tests**

`deploy/tests/test_compose.py` must run:

```python
cmd = [
    "docker", "compose",
    "--env-file", ".env.example",
    "--env-file", "deploy/examples/stack.env.example",
    "-f", "docker-compose.yaml",
    "-f", "compose.the-dream-land.yaml",
    "config", "--format", "json",
]
env["FIRECRAWL_API_ENV_FILE"] = "./deploy/examples/api.env.example"
model = json.loads(subprocess.run(cmd, check=True, text=True, capture_output=True, env=env).stdout)
```

Assert:

```python
assert model["services"]["api"].get("ports", []) == []
assert model["services"]["gateway"]["ports"] == [{
    "mode": "ingress", "target": 8080, "published": "3002",
    "protocol": "tcp", "host_ip": "127.0.0.1"
}]
assert set(model["services"]["api"]["networks"]) == {"backend", "open-webui"}
assert model["networks"]["open-webui"]["external"] is True
assert model["services"]["foundationdb"]["profiles"] == ["foundationdb"]
assert model["services"]["foundationdb-init"]["profiles"] == ["foundationdb"]
assert model["services"]["api"]["environment"]["SEARXNG_ENDPOINT"] == "http://searxng:8080"
assert model["services"]["api"]["environment"]["NUM_WORKERS_PER_QUEUE"] == "1"
assert "postgres-data" in model["volumes"]
assert "redis-data" in model["volumes"]
assert "rabbitmq-data" in model["volumes"]
```

Also assert image strings equal the four pinned digests in the plan and no non-gateway service has host-published ports.

- [ ] **Step 2: Run tests and confirm failure**

```bash
python -m unittest deploy.tests.test_compose -v
```

Expected: FAIL because the overlay and wrapper do not exist.

- [ ] **Step 3: Create the Compose wrapper**

`scripts/compose.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for required in "$ROOT/.env" "$ROOT/secrets/stack.env"; do
  [[ -f "$required" ]] || { printf 'missing required file: %s\n' "$required" >&2; exit 2; }
done
exec docker compose \
  --env-file "$ROOT/.env" \
  --env-file "$ROOT/secrets/stack.env" \
  -f "$ROOT/docker-compose.yaml" \
  -f "$ROOT/compose.the-dream-land.yaml" \
  "$@"
```

- [ ] **Step 4: Create the overlay**

Implement `compose.the-dream-land.yaml` with these exact policies:

```yaml
services:
  playwright-service:
    restart: unless-stopped
    cpus: 1.0
    mem_limit: 2g
    memswap_limit: 2g

  api:
    restart: unless-stopped
    ports: !reset []
    cpus: 1.5
    mem_limit: 3g
    memswap_limit: 3g
    environment:
      NUM_WORKERS_PER_QUEUE: "1"
      CRAWL_CONCURRENT_REQUESTS: "1"
      MAX_CONCURRENT_JOBS: "1"
      BROWSER_POOL_SIZE: "1"
      MAX_CPU: "0.70"
      MAX_RAM: "0.75"
      SEARXNG_ENDPOINT: http://searxng:8080
    networks:
      - backend
      - open-webui
    depends_on:
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      nuq-postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3002/v0/health/readiness').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 15s
      timeout: 5s
      retries: 12
      start_period: 90s

  redis:
    image: redis:alpine@sha256:978f0e01593e65eed801f2402944efcd936d43b5027e4908a7897baf88ed6241
    restart: unless-stopped
    cpus: 0.25
    mem_limit: 256m
    memswap_limit: 256m
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10

  rabbitmq:
    image: rabbitmq:3-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69
    restart: unless-stopped
    cpus: 0.5
    mem_limit: 512m
    memswap_limit: 512m
    volumes:
      - rabbitmq-data:/var/lib/rabbitmq

  nuq-postgres:
    restart: unless-stopped
    cpus: 0.5
    mem_limit: 768m
    memswap_limit: 768m
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s

  foundationdb:
    profiles: ["foundationdb"]

  foundationdb-init:
    profiles: ["foundationdb"]

  gateway:
    image: nginxinc/nginx-unprivileged:1.29.1-alpine@sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e
    restart: unless-stopped
    env_file:
      - ${FIRECRAWL_API_ENV_FILE:-./secrets/api.env}
    environment:
      NGINX_ENVSUBST_FILTER: ^FIRECRAWL_API_KEY$
    ports:
      - "127.0.0.1:3002:8080"
    volumes:
      - ./deploy/nginx/default.conf.template:/etc/nginx/templates/default.conf.template:ro,Z
    networks:
      backend: {}
      open-webui:
        aliases: ["firecrawl-gateway"]
    depends_on:
      api:
        condition: service_healthy
    cpus: 0.1
    mem_limit: 128m
    memswap_limit: 128m
    pids_limit: 128
    read_only: true
    tmpfs:
      - /tmp
      - /var/cache/nginx
      - /etc/nginx/conf.d
    security_opt:
      - no-new-privileges:true
    cap_drop: ["ALL"]
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8080/healthz | grep -qx ok"]
      interval: 15s
      timeout: 3s
      retries: 5
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"

networks:
  open-webui:
    name: open-webui-network
    external: true

volumes:
  postgres-data:
    name: firecrawl-postgres-data
  redis-data:
    name: firecrawl-redis-data
  rabbitmq-data:
    name: firecrawl-rabbitmq-data
```

If Compose normalizes the expected JSON port shape differently, adjust only the test's representation—not the required host IP, target, or published port.

- [ ] **Step 5: Run Compose tests**

```bash
chmod +x scripts/compose.sh
python -m unittest deploy.tests.test_compose -v
docker compose --env-file .env.example --env-file deploy/examples/stack.env.example \
  -f docker-compose.yaml -f compose.the-dream-land.yaml config --quiet
```

Expected: PASS and no interpolation warning for required settings.

- [ ] **Step 6: Commit**

```bash
git add compose.the-dream-land.yaml scripts/compose.sh deploy/tests/test_compose.py
git commit -m "feat: add production Firecrawl compose overlay"
```

---

### Task 3: Bearer Authentication Gateway

**Files:**
- Create: `deploy/nginx/default.conf.template`
- Create: `deploy/tests/test_gateway.py`

**Interfaces:**
- Consumes: `FIRECRAWL_API_KEY`, upstream `api:3002`, external Bearer header.
- Produces: unauthenticated `GET /healthz`; authenticated proxy for every other path; HTTP `401` for missing/wrong keys.

- [ ] **Step 1: Write failing gateway-template tests**

Read the template as text and assert it contains:

```python
assert '"Bearer ${FIRECRAWL_API_KEY}" 1;' in text
assert "return 401" in text
assert "proxy_set_header Authorization \"\";" in text
assert "proxy_pass http://api:3002;" in text
assert "limit_req_zone" in text and "rate=60r/m" in text
assert "location = /healthz" in text
assert "proxy_read_timeout 360s" in text
```

Also reject `proxy_pass` to localhost and any literal 64-hex secret.

- [ ] **Step 2: Run tests and confirm failure**

```bash
python -m unittest deploy.tests.test_gateway -v
```

Expected: FAIL because the template does not exist.

- [ ] **Step 3: Implement the template**

Create:

```nginx
limit_req_zone $binary_remote_addr zone=firecrawl_limit:10m rate=60r/m;

map $http_authorization $firecrawl_authorized {
    default 0;
    "Bearer ${FIRECRAWL_API_KEY}" 1;
}

server {
    listen 8080;
    server_name _;
    client_max_body_size 16m;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok\n";
    }

    location / {
        if ($firecrawl_authorized = 0) { return 401; }
        limit_req zone=firecrawl_limit burst=20 nodelay;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Authorization "";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 15s;
        proxy_send_timeout 360s;
        proxy_read_timeout 360s;
        proxy_buffering off;
        proxy_pass http://api:3002;
    }
}
```

- [ ] **Step 4: Run tests**

```bash
python -m unittest deploy.tests.test_gateway -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/nginx/default.conf.template deploy/tests/test_gateway.py
git commit -m "feat: add Bearer-auth Firecrawl gateway"
```

---

### Task 4: Resource, Verification, and MCP Scripts

**Files:**
- Create: `scripts/resource-guard.sh`
- Create: `scripts/verify-local.sh`
- Create: `scripts/verify-funnel.sh`
- Create: `scripts/verify-mcp.py`
- Create: `deploy/tests/test_scripts.py`

**Interfaces:**
- Consumes: `/proc/meminfo`, `free`, `tailscale ... status --json`, `secrets/api.env`, Firecrawl endpoints.
- Produces: non-secret pass/fail output and exit codes; no response body or credential is retained outside `verification-output/`.

- [ ] **Step 1: Write failing script-safety tests**

Tests must assert:

- every shell script passes `bash -n`;
- each shell script starts with `set -euo pipefail`;
- no script uses `set -x`;
- verification scripts never print `$FIRECRAWL_API_KEY`;
- resource guard exits non-zero when `MEM_AVAILABLE_KIB=2097152` and succeeds at `MEM_AVAILABLE_KIB=7340032`;
- Funnel verification compares baseline `443` and `8443` handlers exactly;
- MCP verifier reads key from `secrets/api.env` and never prints it.

- [ ] **Step 2: Run tests and confirm failure**

```bash
python -m unittest deploy.tests.test_scripts -v
```

Expected: FAIL because scripts are absent.

- [ ] **Step 3: Implement the resource guard**

`resource-guard.sh` accepts mode `pre` or `post` and test overrides:

```bash
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
```

After the threshold check, print only aggregate memory and swap values from `free -h`; never print environment variables.

- [ ] **Step 4: Implement local verification**

`verify-local.sh` must:

1. source `secrets/api.env` without tracing;
2. verify `GET http://127.0.0.1:3002/healthz` returns `200`;
3. verify readiness with no key returns `401`;
4. verify readiness with `Bearer wrong` returns `401`;
5. verify readiness with the correct key returns `200`;
6. POST `/v2/search` for `Firecrawl self hosting` and use Python to assert at least one web result;
7. POST `/v2/scrape` for `https://example.com` and assert non-empty Markdown;
8. inspect `scripts/compose.sh logs --since=5m api` for `Using searxng search`;
9. remove temporary response files with a trap.

Print only named checks and status codes.

- [ ] **Step 5: Implement Funnel and MCP verification**

`verify-funnel.sh` takes a baseline status JSON path, verifies public no-key `401` and correct-key readiness `200`, then uses Python to assert the current `443` and `8443` `TCP`, `Web`, and `AllowFunnel` entries match the baseline exactly.

`verify-mcp.py` uses `/usr/local/lib/hermes-agent/venv`'s `mcp` package:

```python
server = StdioServerParameters(
    command="npx",
    args=["-y", "firecrawl-mcp"],
    env={**os.environ, "FIRECRAWL_API_URL": URL, "FIRECRAWL_API_KEY": key},
)
async with stdio_client(server) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert "firecrawl_search" in {t.name for t in tools.tools}
        result = await session.call_tool("firecrawl_search", {"query": "Firecrawl self hosting", "limit": 2})
        assert not result.isError
```

Output only tool count and PASS.

- [ ] **Step 6: Run tests**

```bash
chmod +x scripts/resource-guard.sh scripts/verify-local.sh scripts/verify-funnel.sh
python -m unittest deploy.tests.test_scripts -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/resource-guard.sh scripts/verify-local.sh scripts/verify-funnel.sh scripts/verify-mcp.py deploy/tests/test_scripts.py
git commit -m "test: add deployment safety and verification scripts"
```

---

### Task 5: Persistent Backup and Restore

**Files:**
- Create: `scripts/backup.sh`
- Create: `scripts/restore.sh`
- Modify: `deploy/tests/test_scripts.py`

**Interfaces:**
- Consumes: named volumes `firecrawl-postgres-data`, `firecrawl-redis-data`, `firecrawl-rabbitmq-data`; pinned `BACKUP_HELPER_IMAGE`.
- Produces: `backups/YYYYMMDDTHHMMSSZ/`, where the directory name comes from `date -u +%Y%m%dT%H%M%SZ`, containing three `.tar.gz` archives, `manifest.txt`, and `SHA256SUMS`.

- [ ] **Step 1: Add failing backup/restore safety tests**

Assert:

```python
assert "--leave-stopped" in backup_text
assert "git rev-parse HEAD" in backup_text
assert "sha256sum" in backup_text
assert "pre-restore" in restore_text
assert "--confirm" in restore_text
assert "docker volume inspect" in backup_text
assert "docker run --rm" in backup_text
```

Run `restore.sh` with no arguments and assert non-zero without calling Docker by placing a failing fake `docker` first in `PATH`.

- [ ] **Step 2: Run tests and confirm failure**

```bash
python -m unittest deploy.tests.test_scripts -v
```

Expected: FAIL because backup/restore scripts do not exist.

- [ ] **Step 3: Implement cold backup**

`backup.sh` must:

- run `resource-guard.sh pre`;
- accept optional `--leave-stopped`;
- stop `gateway api playwright-service`, then `redis rabbitmq nuq-postgres`;
- archive each volume read-only with the pinned Alpine helper;
- write `git rev-parse HEAD`, `git describe --tags --always`, Compose version, volume names, and UTC timestamp to `manifest.txt`;
- generate `SHA256SUMS`;
- restart in order unless `--leave-stopped` was supplied;
- use a trap to restart after unexpected failure when not leaving stopped.

Archive command shape:

```bash
docker run --rm \
  -v "${volume}:/source:ro" \
  -v "${backup_dir}:/backup" \
  "$BACKUP_HELPER_IMAGE" \
  sh -eu -c "cd /source && tar -czf /backup/${archive} ."
```

- [ ] **Step 4: Implement restore**

`restore.sh BACKUP_DIR --confirm` must:

- validate manifest, archives, and `sha256sum -c`;
- call `backup.sh --leave-stopped --output "backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"`;
- refuse if any Firecrawl container remains running;
- clear each named volume with the pinned helper;
- restore each archive;
- start `nuq-postgres redis rabbitmq`, wait healthy, then `playwright-service api gateway`;
- call `verify-local.sh` and `resource-guard.sh post`.

- [ ] **Step 5: Run tests and syntax checks**

```bash
chmod +x scripts/backup.sh scripts/restore.sh
bash -n scripts/backup.sh scripts/restore.sh
python -m unittest deploy.tests.test_scripts -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/backup.sh scripts/restore.sh deploy/tests/test_scripts.py
git commit -m "feat: add Firecrawl volume backup and restore"
```

---

### Task 6: Build and Start the Local Firecrawl Stack

**Files:**
- Create generated ignored files: `.env`, `secrets/api.env`, `secrets/stack.env`
- Create ignored snapshots: `state/pre-deploy-tailscale.json`, `state/pre-deploy-resources.txt`
- Create: `docs/operations/deployment-record.md`

**Interfaces:**
- Consumes: Tasks 1–5 files, host Docker daemon, external `open-webui-network`, port `3002`.
- Produces: healthy local Firecrawl stack and authenticated loopback API; does not modify Open WebUI or Tailscale.

- [ ] **Step 1: Capture immutable pre-deployment state**

```bash
mkdir -p state verification-output
chmod 700 state verification-output
tailscale serve status --json > state/pre-deploy-tailscale.json
{ date -Is; free -h; uptime; docker stats --no-stream; docker system df; } > state/pre-deploy-resources.txt
```

Verify port `3002` is unused and `open-webui-network` exists. Expected: no listener on `127.0.0.1:3002` and network present.

- [ ] **Step 2: Generate real secrets and validate permissions**

```bash
scripts/generate-secrets.sh
stat -c '%a %n' .env secrets/api.env secrets/stack.env
```

Expected: all three files mode `600`; do not display contents.

- [ ] **Step 3: Run all static tests and merged-config checks**

```bash
python -m unittest discover -s deploy/tests -v
scripts/compose.sh config --quiet
scripts/resource-guard.sh pre
```

Expected: PASS and at least 3 GiB available.

- [ ] **Step 4: Pull pinned direct images sequentially**

```bash
scripts/compose.sh pull redis
scripts/resource-guard.sh pre
scripts/compose.sh pull rabbitmq
scripts/resource-guard.sh pre
scripts/compose.sh pull gateway
```

Expected: each pull succeeds; no existing container restarts.

- [ ] **Step 5: Build source images sequentially**

```bash
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build nuq-postgres
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build playwright-service
scripts/resource-guard.sh pre
COMPOSE_PARALLEL_LIMIT=1 scripts/compose.sh build api
scripts/resource-guard.sh pre
```

Expected: builds succeed and memory guard never trips. If it trips, stop; do not proceed to Open WebUI or Funnel.

- [ ] **Step 6: Start stateful services**

```bash
scripts/compose.sh up -d nuq-postgres redis rabbitmq
scripts/compose.sh ps
```

Wait until all three report healthy. FoundationDB must not appear in `docker ps`.

- [ ] **Step 7: Start Playwright, API, and gateway**

```bash
scripts/compose.sh up -d playwright-service api gateway
scripts/compose.sh ps
```

Wait for API and gateway health. Run:

```bash
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Expected: all local checks PASS and at least 6 GiB remains available.

- [ ] **Step 8: Record non-secret results and commit**

Write `docs/operations/deployment-record.md` with Firecrawl tag, local commit, pinned image digests, start timestamp, container health, before/after available RAM and swap, and local verification PASS. Do not include keys, passwords, response bodies, IP tokens, or raw environment.

```bash
git add docs/operations/deployment-record.md
git commit -m "docs: record local Firecrawl deployment"
```

---

### Task 7: Cut Open WebUI Over to Firecrawl

**Files:**
- Modify external file: `/home/kang/docker/open-webui/compose.yaml:8-34`
- Create ignored backups beneath `backups/open-webui/YYYYMMDDTHHMMSSZ/`, using `date -u +%Y%m%dT%H%M%SZ`, containing `compose.yaml` and `webui.db`
- Create: `scripts/configure-open-webui.py`
- Modify: `docs/operations/deployment-record.md`

**Interfaces:**
- Consumes: healthy `firecrawl-gateway`, `secrets/api.env`, Open WebUI SQLite table `config(key,value,updated_at)`.
- Produces: effective Open WebUI settings selecting Firecrawl search and loader; existing SearXNG remains running.

- [ ] **Step 1: Write a failing config-migration unit test**

Create a temporary SQLite `config` table with the current rows and test a pure function:

```python
updates = desired_config("http://firecrawl-gateway:8080", "secret")
assert updates["web.search.engine"] == "firecrawl"
assert updates["web.loader.engine"] == "firecrawl"
assert updates["web.loader.firecrawl_api_url"] == "http://firecrawl-gateway:8080"
assert updates["web.loader.firecrawl_api_key"] == "secret"
assert updates["web.loader.firecrawl_timeout"] == "120"
```

Test that `apply_updates()` uses JSON encoding and preserves unrelated rows.

- [ ] **Step 2: Run test and confirm failure**

```bash
python -m unittest deploy.tests.test_open_webui_config -v
```

Expected: FAIL because `scripts/configure-open-webui.py` does not exist.

- [ ] **Step 3: Implement the migration helper**

The helper must expose `desired_config(base_url, api_key) -> dict[str, object]` and `apply_updates(connection, updates, now)`. CLI mode reads `FIRECRAWL_API_KEY` from environment, updates only these five keys, and prints key names but never values.

SQL shape:

```sql
INSERT INTO config(key, value, updated_at) VALUES (?, ?, ?)
ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
```

- [ ] **Step 4: Back up Open WebUI consistently**

Create timestamped directory mode `0700`. Use Python's SQLite backup API inside the running container to create `/app/backend/data/webui-pre-firecrawl.db`, then `docker cp` that backup out. Copy `compose.yaml` and compute SHA-256 hashes. Confirm both backup files are non-empty.

- [ ] **Step 5: Patch Open WebUI Compose**

Under `open-webui.env_file`, add:

```yaml
      - ../firecrawl/secrets/api.env
```

Replace the direct SearXNG client variables with:

```yaml
      ENABLE_WEB_SEARCH: "true"
      WEB_SEARCH_ENGINE: firecrawl
      WEB_LOADER_ENGINE: firecrawl
      FIRECRAWL_API_BASE_URL: "http://firecrawl-gateway:8080"
      FIRECRAWL_TIMEOUT: "120"
      WEB_SEARCH_RESULT_COUNT: "5"
      WEB_SEARCH_CONCURRENT_REQUESTS: "2"
```

Do not remove the `searxng` service.

- [ ] **Step 6: Validate and restart only Open WebUI**

```bash
cd /home/kang/docker/open-webui
docker compose config --quiet
docker compose up -d --no-deps open-webui
```

Wait for `open-webui` healthy. Confirm Nextcloud containers, SearXNG, Hermes processes, and existing Tailscale status remain healthy/unchanged.

- [ ] **Step 7: Apply persisted retrieval configuration and restart**

Run the helper inside Open WebUI's Python environment with the key available from container env; do not pass the key on the command line. Restart only Open WebUI. Query and print only safe effective values plus `firecrawl_api_key=set`.

Expected:

```text
web.search.engine=firecrawl
web.loader.engine=firecrawl
web.loader.firecrawl_api_url=http://firecrawl-gateway:8080
web.loader.firecrawl_timeout=120
web.loader.firecrawl_api_key=set
```

- [ ] **Step 8: Verify network and health**

From Open WebUI's container, make a Bearer-authenticated readiness request using the environment key without printing it. Expected `200`. Run host Open WebUI health and Firecrawl local verification again.

- [ ] **Step 9: Commit repository-side helper and record**

```bash
git add scripts/configure-open-webui.py deploy/tests/test_open_webui_config.py docs/operations/deployment-record.md
git commit -m "feat: integrate Open WebUI with Firecrawl"
```

The external Compose change is documented in the deployment record because `/home/kang/docker/open-webui` is not a Git repository.

---

### Task 8: Add Tailscale Funnel Port 10000 and Verify MCP

**Files:**
- Modify external Tailscale Serve/Funnel state
- Modify: `docs/operations/deployment-record.md`

**Interfaces:**
- Consumes: healthy loopback gateway and `state/pre-deploy-tailscale.json`.
- Produces: public `https://the-dream-land.taile6fad0.ts.net:10000` with Bearer authentication; unchanged `443` and `8443` handlers.

- [ ] **Step 1: Re-run local and resource gates**

```bash
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Expected: PASS; do not enable Funnel otherwise.

- [ ] **Step 2: Add only Funnel port 10000**

```bash
tailscale funnel --bg --yes --https=10000 http://127.0.0.1:3002
```

Immediately save current status:

```bash
tailscale funnel status --json > state/post-firecrawl-tailscale.json
```

- [ ] **Step 3: Verify route preservation and public auth**

```bash
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
```

Expected:

- `443` handler unchanged and tailnet-only;
- `8443` handler unchanged and Funnel-enabled;
- new `10000` handler points to `http://127.0.0.1:3002` and is Funnel-enabled;
- no-key readiness returns `401`;
- correct key returns `200`.

If preservation fails, run `tailscale funnel --https=10000 off` and stop.

- [ ] **Step 4: Verify official MCP adapter through Funnel**

```bash
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
```

Expected: tool list includes `firecrawl_search`, search call succeeds, and the key is not printed.

- [ ] **Step 5: Verify existing public/private services**

```bash
curl --fail --silent --show-error https://the-dream-land.taile6fad0.ts.net:8443/health >/dev/null
curl --fail --silent --show-error https://the-dream-land.taile6fad0.ts.net/status.php >/dev/null
```

Expected: both commands return zero. If either fails, stop and diagnose without changing its Tailscale route. Confirm all containers and Hermes processes remain running.

- [ ] **Step 6: Record and commit**

Add the `10000` route, route-preservation result, public auth result, and MCP result to the deployment record; include hashes of pre/post Tailscale JSON but not the raw files.

```bash
git add docs/operations/deployment-record.md
git commit -m "docs: record Firecrawl Funnel verification"
```

---

### Task 9: Exercise Backup, Restart Recovery, Rollback Documentation, and Final Acceptance

**Files:**
- Create: `docs/operations/the-dream-land.md`
- Modify: `/home/kang/docker/open-webui/README.md`
- Modify: `docs/operations/deployment-record.md`

**Interfaces:**
- Consumes: complete deployed stack and accepted Funnel route.
- Produces: verified backup archive, successful stop/start recovery, complete operator runbook, final acceptance record.

- [ ] **Step 1: Create and inspect a real cold backup**

```bash
scripts/backup.sh
latest="$(python3 -c 'from pathlib import Path; candidates=[p for p in Path("backups").iterdir() if p.is_dir() and p.name[:1].isdigit()]; print(max(candidates, key=lambda p:p.stat().st_mtime))')"
sha256sum -c "$latest/SHA256SUMS"
```

Expected: three non-empty archives, manifest, and all hashes OK. Do not run restore against production merely to prove archive extraction; inspect each with `tar -tzf`.

- [ ] **Step 2: Test stop/start persistence**

Capture non-secret queue/database health indicators, then:

```bash
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d nuq-postgres redis rabbitmq playwright-service api gateway
scripts/verify-local.sh
scripts/resource-guard.sh post
```

Expected: all checks PASS and named volumes remain attached.

- [ ] **Step 3: Write the operator runbook**

`docs/operations/the-dream-land.md` must contain exact commands for:

- status and logs;
- start/stop/restart;
- local and Funnel verification;
- retrieving the key locally with `sudo -u kang`/SSH-safe guidance but not embedding it;
- rotating the key: stop gateway/Open WebUI, regenerate `api.env`, restart both, update persisted Open WebUI key, re-run verification;
- backup and restore with required confirmations;
- Firecrawl upgrade procedure: new branch/tag review, rebuild sequentially, preserve volumes, rerun all tests;
- disabling only Funnel `10000`;
- rolling Open WebUI back to direct SearXNG using the timestamped Compose/DB backup;
- full Firecrawl rollback without deleting volumes.

- [ ] **Step 4: Update Open WebUI README routing table**

Add Firecrawl on port `10000`, describe SearXNG as Firecrawl's internal search provider, and document that the Firecrawl secret resides in `../firecrawl/secrets/api.env`. Preserve the existing warnings about Funnel exposure and root-path applications.

- [ ] **Step 5: Run the complete acceptance suite**

```bash
python -m unittest discover -s deploy/tests -v
scripts/compose.sh config --quiet
scripts/verify-local.sh
scripts/verify-funnel.sh state/pre-deploy-tailscale.json
/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py
scripts/resource-guard.sh post
git diff --check
```

Also verify:

```bash
scripts/compose.sh ps
docker ps --format '{{.Names}}\t{{.Status}}'
tailscale serve status --json
free -h
```

Expected: all automated checks PASS, FoundationDB absent, at least 6 GiB RAM available, and all existing services healthy.

- [ ] **Step 6: Request the one manual Open WebUI acceptance test**

Ask the user to run one Open WebUI web search from the browser. Expected: results appear and Firecrawl API logs show search plus page-scrape activity. Do not claim this criterion complete until the user confirms it.

- [ ] **Step 7: Finalize deployment record and commit**

Record every acceptance criterion as PASS or explicitly manual-pending, include final resource snapshot and backup path/hash, and keep secrets absent.

```bash
git add docs/operations/the-dream-land.md docs/operations/deployment-record.md
git commit -m "docs: finalize Firecrawl operations and acceptance"
git status --short --branch
git log --oneline --decorate -10
```

Expected: clean repository, local branch only, no push performed.
