# The-Dream-Land Firecrawl Deployment Design

**Status:** Approved in chat on 2026-08-20  
**Target host:** `the-dream-land`  
**Deployment root:** `/home/kang/docker/firecrawl`  
**Firecrawl release:** `v2.11.162`  

## 1. Purpose

Deploy a single-user, self-hosted Firecrawl service for Open WebUI, Zed, and other business devices without disrupting the existing Nextcloud, Open WebUI, Hermes, or Tailscale services.

Firecrawl will provide one authenticated interface for web search, scraping, mapping, and crawling. The existing SearXNG container remains an internal search provider. Fire Engine is excluded because it is not part of the self-hosted Firecrawl distribution.[1][21]

## 2. Goals

- Run the complete open-source Firecrawl dependency stack in Docker.
- Pin Firecrawl source and deployment behavior to release `v2.11.162`.
- Use SearXNG internally for search and DuckDuckGo only as Firecrawl's fallback.
- Expose Firecrawl over public HTTPS through a dedicated Tailscale Funnel listener on port `10000`.
- Require a strong static Bearer API key for every Firecrawl API request.
- Let Open WebUI use Firecrawl for both search and page loading.
- Let Zed and other external clients use the same Firecrawl endpoint and Bearer key.
- Persist PostgreSQL, Redis, and RabbitMQ state.
- Include tested backup, restore, verification, rollback, and resource-safety procedures.
- Preserve the existing Nextcloud and Open WebUI routes unchanged.

## 3. Non-goals

- Do not remove SearXNG.
- Do not deploy Fire Engine or claim cloud-only anti-bot behavior.
- Do not expose Firecrawl's PostgreSQL, Redis, RabbitMQ, Playwright, worker, or unauthenticated API ports.
- Do not move Nextcloud or Open WebUI below URL subpaths.
- Do not replace Tailscale Funnel with another ingress product.
- Do not add Supabase solely to use Firecrawl's database authentication.
- Do not enable FoundationDB as the queue backend.
- Do not configure AI-backed extraction, Ollama, or another model provider in this deployment.

## 4. Existing environment and constraints

The host has 14 logical CPUs, 15 GiB RAM, 8 GiB swap, and approximately 385 GiB free disk at design time. The host already runs Nextcloud AIO, Open WebUI, Open Terminal, SearXNG, Hermes Gateway, Hermes Dashboard, Docker, and Tailscale. At the design snapshot, 10 GiB RAM was available and 2.3 GiB swap was occupied.

Existing routing must remain:

| External URL | Exposure | Local backend |
|---|---|---|
| `https://the-dream-land.taile6fad0.ts.net` | Tailscale Serve, tailnet-only | Nextcloud on port `11000` |
| `https://the-dream-land.taile6fad0.ts.net:8443` | Tailscale Funnel, public | Open WebUI on `127.0.0.1:3000` |
| `https://the-dream-land.taile6fad0.ts.net:10000` | New Tailscale Funnel, public | Firecrawl gateway on `127.0.0.1:3002` |

Tailscale Funnel permits HTTPS listeners on ports `443`, `8443`, and `10000`, so port `10000` provides an independent root-path API without changing the two existing listeners.[12][13]

## 5. Rejected routing design

A single public hostname with `/openwebui`, `/nextcloud`, and `/firecrawl` paths was considered and rejected.

Open WebUI `v0.11.0` has no SvelteKit base-path configuration and community reports document broken root-relative assets and API paths when mounted below a proxy prefix.[16][19]

Standard Nextcloud can be configured with `overwritewebroot`, but Nextcloud AIO's managed domain validation does not cleanly support subdirectory deployment and its maintainers recommend a separate hostname instead.[17][18]

Dedicated ports preserve each application's root-path assumption and keep Nextcloud tailnet-only.

## 6. Selected architecture

```text
Business devices / Zed
        |
        | HTTPS :10000 + Authorization: Bearer <key>
        v
Tailscale Funnel :10000
        |
        v
127.0.0.1:3002
        |
        v
firecrawl-gateway (Nginx)
        |
        | private Docker backend network
        v
firecrawl-api/workers ---- playwright-service
        |                  redis
        |                  rabbitmq
        |                  nuq-postgres
        |
        | external open-webui-network
        v
searxng:8080

Open WebUI -- Bearer key --> firecrawl-gateway:8080
```

### Component boundaries

- **Nginx gateway:** authenticates clients, applies a conservative request-rate envelope, strips the external credential before proxying, and is the only Firecrawl service with a host port.
- **Firecrawl API/workers:** provides API orchestration and queue workers. It remains internally unauthenticated because the gateway is the sole ingress.
- **Playwright service:** renders JavaScript-heavy pages with one page of concurrency.
- **Redis:** cache and rate-limit state.
- **RabbitMQ:** worker messaging.
- **NuQ PostgreSQL:** durable queue/job state.
- **SearXNG:** remains in the existing Open WebUI Compose project and is reachable only through `open-webui-network`.
- **Tailscale Funnel:** terminates public TLS and forwards only port `10000` to the loopback gateway.

The pinned Firecrawl search implementation uses Fire Engine when configured, then SearXNG when `SEARXNG_ENDPOINT` is set, and finally DuckDuckGo when SearXNG returns no results. This deployment leaves Fire Engine unset and configures SearXNG.[22]

## 7. Docker and source layout

The repository is a shallow checkout of Firecrawl `v2.11.162` on branch `local/the-dream-land-deployment`.

Local deployment artifacts will be additive and isolated from upstream application code:

```text
/home/kang/docker/firecrawl/
├── docker-compose.yaml                 # upstream pinned release
├── compose.the-dream-land.yaml         # local production overlay
├── .env                                # non-secret deployment settings, mode 0600
├── secrets/
│   ├── api.env                         # generated client Bearer key, mode 0600
│   └── stack.env                       # PostgreSQL and stack-only secrets, mode 0600
├── deploy/nginx/
│   └── default.conf.template           # Bearer gateway and proxy policy
├── scripts/
│   ├── compose.sh                      # loads deployment and stack env files
│   ├── backup.sh
│   ├── restore.sh
│   ├── verify-local.sh
│   └── verify-funnel.sh
├── backups/                            # ignored timestamped archives
└── docs/superpowers/
```

The overlay will:

- remove the upstream API host-port publication;
- add the Nginx gateway and its loopback-only publication;
- attach Firecrawl API and gateway to the required networks;
- add named volumes for PostgreSQL, Redis, and RabbitMQ;
- add resource limits, health checks, restart policies, and bounded logs;
- place FoundationDB services behind a non-default `foundationdb` profile;
- retain the upstream application source and Docker build contexts.

Third-party base images used directly by the deployment overlay will be version-and-digest pinned during implementation.

All operational scripts will invoke Compose through `scripts/compose.sh`. The wrapper supplies the upstream file, local overlay, `.env`, and `secrets/stack.env` consistently so PostgreSQL interpolation cannot silently fall back to development defaults.

## 8. Authentication and secret handling

A new 256-bit hexadecimal API key will be generated locally. It will not reuse the Firecrawl Cloud key or any existing Open WebUI/provider credential. A separate strong PostgreSQL password will also be generated.

The credentials will be separated by trust boundary:

```text
/home/kang/docker/firecrawl/secrets/api.env
/home/kang/docker/firecrawl/secrets/stack.env
```

`api.env` contains only `FIRECRAWL_API_KEY` and is shared with the Nginx gateway and Open WebUI. `stack.env` contains the PostgreSQL password and any future stack-only secret; it is never mounted into or loaded by Open WebUI.

Requirements:

- owner: `kang`;
- mode: `0600`;
- ignored by Git;
- never printed in command output, logs, commits, the design document, or Telegram;
- shared with Open WebUI through an `env_file` reference rather than duplicated.

The gateway accepts only the exact header:

```http
Authorization: Bearer <generated-key>
```

Open WebUI `v0.11.0` already formats Firecrawl credentials as this Bearer header.[23] The gateway returns `401` before proxying when the header is absent or incorrect. It removes `Authorization` before forwarding to Firecrawl.

The gateway also provides:

- a non-sensitive `/healthz` endpoint;
- approximately 60 requests per minute with a short burst allowance;
- a bounded request-body size appropriate for search/scrape/crawl requests;
- long read/send timeouts for asynchronous or browser-backed work;
- disabled response buffering where streaming or long-running requests require it;
- bounded JSON logs.

## 9. Client integration

### Open WebUI

The Open WebUI service remains in `/home/kang/docker/open-webui` and joins no new host network. Its Compose configuration will reference only `../firecrawl/secrets/api.env` and set:

```env
WEB_SEARCH_ENGINE=firecrawl
WEB_LOADER_ENGINE=firecrawl
FIRECRAWL_API_BASE_URL=http://firecrawl-gateway:8080
FIRECRAWL_TIMEOUT=120
```

`FIRECRAWL_API_KEY` comes from `api.env`; Open WebUI never receives `stack.env` or the PostgreSQL password.

The gateway joins `open-webui-network` with alias `firecrawl-gateway`. Open WebUI therefore avoids a public Funnel round trip.

Open WebUI stores some web-search settings in its database and persisted values can override environment defaults. Before cutover, the implementation will back up the Open WebUI data volume and inspect the effective persisted retrieval configuration. It will update persisted values only if the existing SearXNG selection remains active after the Compose change.

### Zed and other business devices

External MCP clients use Firecrawl's MCP adapter with:

```env
FIRECRAWL_API_URL=https://the-dream-land.taile6fad0.ts.net:10000
FIRECRAWL_API_KEY=<generated-key>
```

The official Firecrawl MCP server supports a custom `FIRECRAWL_API_URL` for self-hosted APIs, while Zed supports custom local and remote MCP servers.[4][8]

The secret will be retrieved through a trusted host/SSH path, not delivered in chat.

## 10. Resource policy

The initial deployment is deliberately serial because this is a shared 15 GiB host with one user.

### Concurrency

```env
NUM_WORKERS_PER_QUEUE=1
CRAWL_CONCURRENT_REQUESTS=1
MAX_CONCURRENT_JOBS=1
BROWSER_POOL_SIZE=1
```

### Service caps

| Service | CPU cap | RAM cap |
|---|---:|---:|
| Firecrawl API/workers | 1.5 | 3 GiB |
| Playwright | 1.0 | 2 GiB |
| NuQ PostgreSQL | 0.5 | 768 MiB |
| RabbitMQ | 0.5 | 512 MiB |
| Redis | 0.25 | 256 MiB |
| Nginx gateway | 0.1 | 128 MiB |

These values are maximums, not reservations.

### Resource gates

- Build source images sequentially.
- Capture RAM, swap, and load before and after each build/startup stage.
- Abort without changing Open WebUI or Tailscale if available RAM falls below 3 GiB or swap begins increasing rapidly.
- Require at least 6 GiB available RAM after Firecrawl settles idle.
- Do not enable Funnel `:10000` before local functional and resource tests pass.

## 11. Persistence and backups

Named volumes will persist:

- `/var/lib/postgresql/data` for NuQ PostgreSQL;
- `/data` for Redis;
- `/var/lib/rabbitmq` for RabbitMQ.

The backup workflow is a cold, consistent snapshot:

1. Stop the gateway, API/workers, and Playwright.
2. Stop the three stateful services.
3. Archive each named volume independently into a timestamped directory beneath `backups/`.
4. Record deployment commit, Firecrawl tag, archive hashes, and volume names in a manifest.
5. Restart stateful services, then API/Playwright, then gateway.
6. Run authenticated readiness and search smoke tests.

The restore workflow:

1. Requires an explicit target backup path.
2. Refuses to run while Firecrawl containers are active.
3. Creates a pre-restore safety archive of current volumes.
4. Clears and restores each target volume.
5. Starts services in dependency order.
6. Runs local authenticated verification before Funnel traffic is considered healthy.

Backups are ignored by Git and remain on the local filesystem. Off-host backup is outside this implementation's scope.

## 12. Staged deployment

1. Validate source tag, branch, Docker/Compose versions, free ports, networks, and current Tailscale routes.
2. Create ignored `api.env` and `stack.env` files and generate independent secrets.
3. Write the Compose overlay, gateway template, scripts, and documentation.
4. Validate merged Compose output without starting containers.
5. Build Firecrawl images sequentially while monitoring host resources.
6. Start PostgreSQL, Redis, and RabbitMQ; verify health.
7. Start Playwright and Firecrawl API; verify internal readiness.
8. Start the gateway; verify authentication failure and success paths locally.
9. Verify real `/v2/search` and `/v2/scrape` requests.
10. Back up Open WebUI and modify its Firecrawl client configuration.
11. Verify Open WebUI health and internal gateway reachability.
12. Configure Tailscale Funnel `:10000` without modifying `443` or `8443`.
13. Verify the public Funnel endpoint and local MCP adapter.
14. Run backup archive creation and inspect manifests/hashes.
15. Stop/start the Firecrawl stack and verify state recovery.

## 13. Verification and acceptance criteria

The implementation is complete only when all conditions hold:

- Merged Compose configuration validates.
- Required containers are running or healthy; FoundationDB is not running.
- Existing Nextcloud and Open WebUI containers remain healthy.
- Existing Tailscale `443` and `8443` handlers are byte-for-byte unchanged in the status JSON except for unrelated runtime metadata.
- Missing API key returns `401`.
- Incorrect API key returns `401`.
- Correct API key reaches Firecrawl readiness.
- Authenticated `/v2/search` returns web results and logs confirm SearXNG selection.
- Authenticated `/v2/scrape` returns non-empty Markdown from a real page.
- Open WebUI can resolve and reach `firecrawl-gateway` over Docker DNS.
- Open WebUI's effective web-search and loader configuration selects Firecrawl.
- Public `https://the-dream-land.taile6fad0.ts.net:10000` rejects unauthenticated requests and accepts the correct key.
- A local Firecrawl MCP adapter can list tools and complete a search against the Funnel endpoint.
- Available RAM remains at least 6 GiB after idle settlement.
- The backup script creates readable archives, hashes, and a manifest.
- A Firecrawl stop/start cycle preserves state and returns all services to health.

A final interactive Open WebUI web-search check from the user's browser is required because the agent does not possess the user's Open WebUI session credentials.

## 14. Error handling and rollback

### Startup/build failure

- Stop only the new Firecrawl services.
- Preserve build logs and generated local configuration.
- Do not modify Open WebUI or Tailscale until local Firecrawl verification succeeds.

### Resource pressure

- Stop gateway, API, and Playwright immediately.
- Keep stateful volumes intact.
- Re-measure host memory/swap and lower concurrency or caps before retrying.

### Open WebUI cutover failure

- Restore the timestamped Open WebUI Compose/config backup.
- Restart only Open WebUI.
- Confirm direct SearXNG search remains available.

### Funnel failure

- Remove only the `:10000` Funnel handler.
- Confirm handlers for `443` and `8443` remain unchanged.
- Continue using the internal Firecrawl endpoint from Open WebUI while diagnosing external access.

### Full rollback

- Disable Funnel `:10000`.
- Restore Open WebUI's previous direct-SearXNG configuration.
- Stop and remove Firecrawl containers without deleting volumes.
- Leave `/home/kang/docker/firecrawl`, secrets, backups, and volumes for diagnosis unless the user explicitly requests deletion.

## 15. Maintainability

- Upgrades require reviewing the target Firecrawl release's Compose contract and self-host notes before changing the pinned tag.[1][20]
- Local deployment changes remain isolated in the overlay, scripts, gateway template, and documentation.
- Every upgrade must re-run authentication, search, scrape, resource, persistence, Funnel, and rollback checks.
- SearXNG, Open WebUI, Nginx, Redis, RabbitMQ, and other directly referenced images remain version/digest pinned and are updated deliberately.
- No dependency or admin port may be added to host publication without a new design review.

## Sources

[1] https://docs.firecrawl.dev/contributing/self-host
[4] https://zed.dev/docs/ai/mcp
[8] https://github.com/firecrawl/firecrawl-mcp-server
[12] https://tailscale.com/kb/1223/funnel
[13] https://tailscale.com/kb/1312/serve
[16] https://github.com/open-webui/open-webui/discussions/6650
[17] https://github.com/nextcloud/all-in-one/discussions/839
[18] https://docs.nextcloud.com/server/stable/admin_manual/configuration_server/reverse_proxy_configuration.html
[19] https://github.com/open-webui/open-webui/blob/v0.11.0/svelte.config.js
[20] https://github.com/firecrawl/firecrawl/blob/v2.11.162/docker-compose.yaml
[21] https://github.com/firecrawl/firecrawl/blob/v2.11.162/SELF_HOST.md
[22] https://github.com/firecrawl/firecrawl/blob/v2.11.162/apps/api/src/search/index.ts
[23] https://github.com/open-webui/open-webui/blob/v0.11.0/backend/open_webui/retrieval/web/firecrawl.py
