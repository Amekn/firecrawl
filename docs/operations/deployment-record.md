# Local Firecrawl deployment record

## Result

**DONE_WITH_CONCERNS — the final whole-branch fix wave passed the complete automated/runtime/network/backup gates. Inherited optional-variable warnings and the documented external-download provenance limitation remain concerns; no blocking acceptance failure remains.**

This record retains the historical deployment attempts and concerns below. The authoritative runtime source remains `053e71397ee378fdefa7a4098fb9b68af5d964ed` on branch `local/the-dream-land-deployment`; the final documentation head after this follow-up is documentation-only and is not a runtime revision. Existing Compose unset-variable warnings remain documented as non-blocking optional/default behavior; no secret value or raw Tailscale JSON is recorded.

## Final whole-branch fix wave

**Result: DONE_WITH_CONCERNS.** The final fix wave was applied after the source fix commit, with fresh backups and bounded rollback gates. No rollback was needed because every final network/runtime/acceptance gate passed.

### Source, timing, and generated files

- Runtime source commit: `053e71397ee378fdefa7a4098fb9b68af5d964ed` (backup-stream privacy correction included).
- Final documentation head: the later docs commit containing this record, the external README update reference, and the final report; it is documentation-only and must not be used as the deployed runtime revision.
- Fresh fixed Firecrawl backup: `/home/kang/docker/firecrawl/backups/20260820T152048Z/`.
- Fresh final-fix network-segmentation rollback backup (preserves Firecrawl retrieval; not a direct-SearXNG rollback source): `/home/kang/docker/firecrawl/backups/open-webui/20260820T150716Z/`.
- Final acceptance snapshot: `2026-08-20T15:22:20Z` (local `2026-08-21T03:22:20+12:00`). Final runtime evidence was recorded at `2026-08-20T15:23:19Z` in ignored `state/final-fix-runtime-evidence.txt`.
- `.env` and `secrets/*` are ignored generated/local-only files; ignored `state/` evidence files remain local-only; their values are not recorded.

### Fresh backup evidence

- Firecrawl backup directory mode `700`; `manifest.txt` and `SHA256SUMS` mode `600`; all three archives mode `600`.
- Firecrawl archive SHA-256: `postgres.tar.gz` `7bfe7b90f696294827182189daa97171dc404a1a5a63382498bc4ad0d53e56e2`; `rabbitmq.tar.gz` `856fb5c12523d6f44b1bec52e912153d885f817cea952cde7cb30933af9ec945`; `redis.tar.gz` `64786ef96d4214ae5bd904952cb85564cc0be91ced037b77a0e9f5cc459e209d`.
- Firecrawl `SHA256SUMS` and manifest archive-hash entries verified; all three `tar -tzf` listings passed. The fixed backup restarted stateful then application tiers with `--wait --wait-timeout 300`, ran local verification, and ran the post resource guard before printing success.
- Open WebUI backup directory mode `700`; `compose.yaml`, `webui.db`, and `SHA256SUMS` mode `600`; SQLite online backup passed `PRAGMA integrity_check=ok`; checksums passed. `compose.yaml` SHA-256: `fc4c0e01c78f7503ebec2b368eb31d0a75a0ea2d479b75eed640f41b056b406d`; `webui.db` SHA-256: `1f97ec98de26f98b65de2962c26a0d806bc9532ad9a3ed917ce79962708d1789`.

### Source image provenance

- `firecrawl-nuq-postgres` image ID/digest: `sha256:3eec9c6240ed0e7f2949293f9573dd393015d273cfeb7c9e50f250ead7c2450b`.
- `firecrawl-playwright-service` image ID/digest: `sha256:ea984f1740dd210fe115cf33841a4491af602566327937e8c52eab2dbf5eaf69`.
- `firecrawl-api` image ID/digest: `sha256:3e88b75d9ff48f6ad04cd40589a3e2a399b679c8071d33aa1773df11d2b1d6e7`.
- Reviewed immutable build bases resolved and were used: Node `node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436`; PostgreSQL `postgres:17@sha256:e38411452a464af89e5adadb8d223bf53b898d47d6ef918b2d58c08707350449`; Go `golang:1.24@sha256:d2d2bc1c84f7e60d7d2438a3836ae7d0c847f4888464e7ec9ba3a1339a1ee804`.
- Builds were sequential with pre-resource guards between `nuq-postgres`, `playwright-service`, and `api`; named volumes were preserved. Versioned external build downloads remain a separate provenance limitation; no invented checksums are claimed.

### Network and runtime acceptance

- `firecrawl-search-network`: `internal=true`, exact members `firecrawl-api-1,searxng`.
- `open-webui-network`: API absent; members were gateway, Open WebUI, and SearXNG. Open WebUI could not resolve `api`; authenticated gateway reachability returned `200`; API→SearXNG health returned `200`.
- External `/home/kang/docker/open-webui/compose.yaml`: only SearXNG was added to external `firecrawl-search` (`name: firecrawl-search-network`); Open WebUI was not attached. External merged-Compose test passed.
- All six Firecrawl services were running/healthy as applicable after source-image recreation; FoundationDB was absent; all three named volumes remained present and attached.
- Local verification passed health/readiness `401/401/200`, search, Markdown scrape, and SearXNG evidence. Open WebUI health and read-only five-setting persisted configuration passed; only `firecrawl_api_key=set` was reported.
- Funnel verification passed public `401/200` and exact route preservation. Live Tailscale status hash remained `a9d86c3303e38addf567acff6630570778f0a4dba0bf3c48ca71a7883813d4d9`; no 443/8443 route change was made. The historical browser criterion was not re-invented; safe internal Open WebUI/gateway/search/scrape checks passed.
- MCP verifier passed exact pinned adapter/search with `tools: 27` and `PASS`.
- Final post resource guard passed with approximately 8.1 GiB available RAM and 2.0 GiB swap used of 8.0 GiB; rapid-growth gate is `131072 KiB/minute`.

### Historical timing clarification and concerns

- Initial Task 8 verifier timestamp: `2026-08-21T00:50:39+12:00` (historical pre-final-MCP-fix evidence). Final verifier timestamp: `2026-08-21T03:22:20+12:00`.
- The pre-existing Compose warning inventory remains intentionally documented as optional/out-of-scope or PostgreSQL-default behavior; warning elimination was not required by this wave.
- The API Dockerfile's versioned external build downloads remain a separate provenance limitation despite immutable base pins; the runbook records this explicitly.

## Source and timing

- Firecrawl git describe before the initial attempt: `v2.11.162-14-gbcdc66d`
- Source commit before the initial attempt: `bcdc66de0c6ff518dff61b1ee0721a7791337c37`
- Historical Task 6 first-successful configuration commit: `b8ecea16a6e397ccd82f783c7b00e524524ae0c2`
- Branch: `local/the-dream-land-deployment`
- Initial pre-state capture: `2026-08-20T22:47:55+12:00`
- Initial stateful-service start: `2026-08-20T23:08:01+12:00`
- Initial runtime/gateway start attempt: `2026-08-20T23:08:27+12:00`
- Final successful API/gateway health: `2026-08-20T23:38:46+12:00`
- Initial failure cleanup: only the newly-created API and Playwright containers were stopped; stateful Firecrawl services remained running.

## Generated files

- `.env`, `secrets/api.env`, and `secrets/stack.env` were generated with real values and verified mode `600`.
- Secret contents, environment values, credentials, and response bodies are intentionally not recorded here.

## Pinned images

Direct runtime images:

- `redis:alpine@sha256:978f0e01593e65eed801f2402944efcd936d43b5027e4908a7897baf88ed6241`
- `rabbitmq:3-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69`
- `nginxinc/nginx-unprivileged:1.29.1-alpine@sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e`

Built local images:

- `firecrawl-nuq-postgres@sha256:53b89c3365d5041d0418cd6ed91cbcc836cc14cdedb3eb78e98bfeabf8389440`
- `firecrawl-playwright-service@sha256:3e7382fc90f5da0cf770e1b0dc2771eaeeae851498b9bf1386fff3a0b5d1d5ff`
- `firecrawl-api@sha256:6dc645e110c4939e960ffe1d4418c1170d98fbf910d33334ae4fd9f6feb04595`

Build base digests observed:

- `postgres:17@sha256:e38411452a464af89e5adadb8d223bf53b898d47d6ef918b2d58c08707350449`
- `node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436`

## Gates and verification

- Final deploy unit tests: **PASS**, 29 tests.
- Final merged Compose config: **PASS**; the unset-variable warnings are enumerated and classified below.
- Final pre resource guards: **PASS** at every required static, pull, build, recreation, and staged-start checkpoint; available RAM remained above the configured threshold.
- Direct image pulls: **PASS**, sequentially for Redis, RabbitMQ, and gateway.
- Source builds: **PASS**, sequentially for NuQ PostgreSQL, Playwright, and API. The first foreground API build call timed out in the tool after partial progress; the retried background build completed successfully and its resource guard passed.
- Stateful health: **PASS** — NuQ PostgreSQL, Redis, and RabbitMQ healthy; FoundationDB absent from the active local profile.
- Final API/gateway health: **PASS** at `2026-08-20T23:38:46+12:00` — Playwright running, API running/healthy, and gateway running/healthy, all with restart count 0.
- Local verification (`scripts/verify-local.sh`): **PASS** — healthz 200, readiness 401/401/200, search results, scrape Markdown, and SearXNG evidence.
- Post resource guard (`scripts/resource-guard.sh post`): **PASS** — 8.7 GiB available RAM; swap approximately 2.8 GiB used of 8 GiB.

## Compose unset-variable warning inventory

The final read-only `scripts/compose.sh config --quiet` check emitted repeated warnings of the form `variable is not set; defaulting to a blank string`. The names below are the complete **20-name deduplicated inventory**; Compose repeated some names because they are interpolated in more than one merged service. Every warning is classified as either intentionally optional/out-of-scope for this local acceptance or PostgreSQL-default behavior. No warning caused the Compose config gate or final runtime gates to fail.

| Unset variable | Classification | Local deployment interpretation |
|---|---|---|
| `ALLOW_LOCAL_WEBHOOKS` | Intentionally optional / out-of-scope | Webhook policy setting; no webhook integration was required by Task 6 acceptance. |
| `AUTUMN_SECRET_KEY` | Intentionally optional / out-of-scope | Optional Autumn integration secret; not used by this local stack. |
| `BULL_AUTH_KEY` | Intentionally optional / out-of-scope | Optional Bull dashboard/auth integration; not used by this local stack. |
| `MODEL_EMBEDDING_NAME` | Intentionally optional / out-of-scope | Optional model/embedding configuration; no AI provider was required by local acceptance. |
| `MODEL_NAME` | Intentionally optional / out-of-scope | Optional model configuration; no AI provider was required by local acceptance. |
| `OLLAMA_BASE_URL` | Intentionally optional / out-of-scope | Optional Ollama provider endpoint; not used by this local stack. |
| `OPENAI_API_KEY` | Intentionally optional / out-of-scope | Optional OpenAI credential; intentionally absent and not needed for local acceptance. |
| `OPENAI_BASE_URL` | Intentionally optional / out-of-scope | Optional OpenAI-compatible endpoint; not used by this local stack. |
| `PROXY_PASSWORD` | Intentionally optional / out-of-scope | Optional outbound proxy credential; direct local connectivity was used. |
| `PROXY_SERVER` | Intentionally optional / out-of-scope | Optional outbound proxy; direct local connectivity was used. |
| `PROXY_USERNAME` | Intentionally optional / out-of-scope | Optional outbound proxy credential; direct local connectivity was used. |
| `SEARXNG_CATEGORIES` | Intentionally optional / out-of-scope | Optional SearXNG tuning; the configured endpoint and SearXNG activity check passed without it. |
| `SEARXNG_ENGINES` | Intentionally optional / out-of-scope | Optional SearXNG tuning; the configured endpoint and SearXNG activity check passed without it. |
| `SELF_HOSTED_WEBHOOK_URL` | Intentionally optional / out-of-scope | Optional self-hosted webhook integration; not required by local acceptance. |
| `SLACK_WEBHOOK_URL` | Intentionally optional / out-of-scope | Optional Slack notification integration; not used by this local stack. |
| `SUPABASE_ANON_TOKEN` | Intentionally optional / out-of-scope | Optional Supabase integration credential; not used by this local stack. |
| `SUPABASE_SERVICE_TOKEN` | Intentionally optional / out-of-scope | Optional Supabase integration credential; not used by this local stack. |
| `SUPABASE_URL` | Intentionally optional / out-of-scope | Optional Supabase integration endpoint; not used by this local stack. |
| `TEST_API_KEY` | Intentionally optional / out-of-scope | Optional test/integration credential; not required by the verified local checks. |
| `NUQ_BACKEND` | PostgreSQL-default behavior | Blank selects the default PostgreSQL queue path; the `nuq-postgres` service was healthy and the FoundationDB profile was not enabled. |

Source interpolation sites are the bare optional references in `docker-compose.yaml:38-59,70-74`. In the local deployment, `POSTGRES_USER` and `POSTGRES_PASSWORD` are intentionally supplied through the generated `secrets/stack.env`; `POSTGRES_DB=postgres`, `POSTGRES_HOST`, and `POSTGRES_PORT` retain their documented defaults. No secret values are recorded.

## Historical initial attempt — container outcome

| Service | Container ID | Final state | Health |
|---|---|---|---|
| `nuq-postgres` | `ff9b9b3d603c45d96f95b7fcc3b3b760becdc799f1f452b06bc9a9e0e1babf70` | running | healthy |
| `redis` | `9931509ea26c024a6105512f03e221f9167128fc658eb51df9a58d908b415577` | running | healthy |
| `rabbitmq` | `5eb93c002d535b35f29d2897fcecbc4e41dc52cb910e14a968d5f7f8d7b192b1` | running | healthy |
| `playwright-service` | `2e5887e29a04e6dac1eea4a568f2c36a5112c9e65f29b15eb91fe1a53d6bac17` | exited (1) | no healthcheck |
| `api` | `8bc4a53caa5c99ec9f58a2620fce1cff72b39dec6012ce5ca2935c2188339157` | exited (137) | unhealthy; restart loop observed |
| `gateway` | `9b77945aa74d8db832e094c2fc54bf9b9dad599e6ca723afcc7891cfac368724` | created | not started |

## Historical initial attempt — memory and swap

| Snapshot | Available RAM | Swap used / total |
|---|---:|---:|
| Pre-deployment (`state/pre-deploy-resources.txt`) | 10 GiB | 2.8 / 8.0 GiB |
| After API build/resource checkpoint | 11 GiB | 2.9 / 8.0 GiB |
| During failed API startup | 8 GiB | 2.9 / 8.0 GiB |
| Final raw snapshot after stopping failed runtime containers | 10 GiB | 2.9 / 8.0 GiB |

The post guard was intentionally not invoked, so the final raw snapshot is not a post-guard PASS claim.

## Historical initial attempt — concerns and follow-up

- API startup repeatedly spawned the configured NuQ worker set and worker processes exited with status 137; the API health check never became healthy. The API container was limited to 3 GiB and reached approximately 2.5 GiB during diagnosis.
- The deployment configuration exposes `NUM_WORKERS_PER_QUEUE`, but the API harness also uses a separate `NUQ_WORKER_COUNT` setting whose default is five. This was not changed during the aborted deployment; review and explicitly configure the runtime worker count or memory budget before retrying.
- Compose emitted repeated warnings for unset optional variables. They did not fail static validation, but should be reviewed before a production retry.
- No Open WebUI, Tailscale, Funnel, or existing Nextcloud container was started, stopped, restarted, or modified. The pre/post Tailscale serve JSON snapshots were byte-for-byte unchanged, and the existing container IDs/statuses remained healthy.
- Port `127.0.0.1:3002` is unused after cleanup. Stateful Firecrawl containers and their named volumes remain present; no `docker compose down` or volume deletion was performed.

## Historical controlled retry — NuQ worker-count fix

**Historical BLOCKED attempt — API recovered, but the gateway health gate failed.**

The retry changed exactly one runtime setting: `NUQ_WORKER_COUNT: "1"` was added to `api.environment` in `compose.the-dream-land.yaml`. No memory limit, CPU limit, concurrency value, or other resource setting was changed.

- TDD RED: the new Compose invariant for `NUQ_WORKER_COUNT == "1"` failed before the Compose change with `KeyError: 'NUQ_WORKER_COUNT'`.
- TDD GREEN: the focused invariant passed; the full deploy suite passed, 28 tests; merged Compose config passed.
- Resource guards: `scripts/resource-guard.sh pre` passed before runtime recreation and before gateway start. The post guard was not run because the runtime health gate failed.
- API: healthy, restart count 0, container `46ba000d0be9`; inspected environment contained exactly `NUQ_WORKER_COUNT=1`.
- API harness: safe logs and process inspection showed one `nuq-worker-0` process (`node dist/src/services/worker/nuq-worker.js`), plus the separate queue, extract, prefetch, and reconciler processes.
- Playwright: running during the retry, approximately 188 MiB of its 2 GiB limit, restart count 0.
- API memory: approximately 1.55 GiB of its unchanged 3 GiB limit; host available RAM remained approximately 8.7–9.3 GiB during gateway health polling.
- Gateway: container `12d767583d46` stayed running but unhealthy. The healthcheck reproduced `wget: can't connect to remote host (127.0.0.1): Connection refused`; the gateway log reported `/etc/nginx/templates exists, but /etc/nginx/conf.d is not writable`. `nginx -t` passed, but no listener was available on the healthcheck address. This is the observed retry blocker; no alternate setting was attempted.
- Cleanup: only the newly recreated `api`, `playwright-service`, and `gateway` containers were stopped. NuQ PostgreSQL, Redis, and RabbitMQ remained healthy.
- `scripts/verify-local.sh` was not run because the gateway health gate failed.
- Existing Nextcloud, Open WebUI, Open Terminal, SearXNG, and stateful Firecrawl container identities/images/ports were unchanged and healthy. Tailscale serve JSON was byte-for-byte unchanged (SHA-256 `93aeda22a532473e5116a138f5e1c260f2317b5ee81a26ed43967c57cafb8070`).
- That retry was therefore **BLOCKED**, with no further retry permitted under that one-variable retry rule; the separately scoped gateway tmpfs remediation recorded below became the authoritative final attempt.

## Final controlled retry — gateway tmpfs permissions

**DONE_WITH_CONCERNS — the gateway retry passed all runtime gates.** Compose still emits repeated warnings for unset optional variables; they did not affect the verified deployment.

### Diagnosis and one-variable fix

The prior gateway retry used the pinned unprivileged Nginx image (uid/gid 101) with default tmpfs mounts. Its entrypoint reported that `/etc/nginx/conf.d` was not writable, so Nginx generated no usable listener even though `nginx -t` passed. The controlled fix changed only the three gateway `tmpfs` entries in `compose.the-dream-land.yaml` and added the matching Compose invariant in `deploy/tests/test_compose.py`:

```text
/tmp:uid=101,gid=101,mode=1777
/var/cache/nginx:uid=101,gid=101,mode=0755
/etc/nginx/conf.d:uid=101,gid=101,mode=0755
```

No image, `read_only`, capabilities, ports, resources, API settings, or Nginx template changed. The source commit before this retry was `2a2163210d98150741bbc0103f04ff93357fb431`.

### TDD and static/config gates

- RED: `python3 -m unittest deploy.tests.test_compose.ComposeInvariantTests.test_gateway_tmpfs_entries_are_uid_gid_and_mode_pinned -v` failed as expected because Compose rendered `['/tmp', '/var/cache/nginx', '/etc/nginx/conf.d']` instead of the required option-pinned entries.
- GREEN: the focused invariant passed.
- Full deploy suite: **PASS**, 29 tests.
- Static checks: `python3 -m compileall -q deploy/tests` and `git diff --check`: **PASS**.
- Merged Compose config: **PASS**; rendered gateway tmpfs entries matched the required list. Compose emitted only the existing unset-optional-variable warnings.

### Runtime and acceptance gates

- `scripts/resource-guard.sh pre`: **PASS** before recreation and before each staged new-runtime start. Available RAM ranged from 10 GiB before start to 8.6–9 GiB during startup; swap remained approximately 2.8–2.9 GiB used of 8 GiB.
- Only `playwright-service`, `api`, and `gateway` were removed/recreated, using `--no-deps`; NuQ PostgreSQL, Redis, and RabbitMQ were not recreated.
- Final new-runtime state: Playwright running (restart count 0); API running/healthy (restart count 0); gateway running/healthy (restart count 0).
- Gateway runtime tmpfs inspection exactly matched the three required path/options; the container ran as uid/gid 101 and actual mount ownership was 101:101 with modes 1777/0755/0755.
- Generated `/etc/nginx/conf.d/default.conf` was non-empty. `nginx -t` passed, `nginx -T` contained `listen 8080;` and `proxy_pass http://api:3002;`, and gateway logs contained no write/config error markers.
- `scripts/verify-local.sh`: **PASS** — healthz 200, unauthenticated and wrong-key readiness 401, keyed readiness 200, search 200 with results, scrape 200 with Markdown, and SearXNG log marker present.
- `scripts/resource-guard.sh post`: **PASS** — 8.7 GiB available RAM; swap approximately 2.8 GiB used of 8 GiB.

Final runtime memory snapshot: Playwright `215 MiB / 2 GiB`, API `1.562 GiB / 3 GiB`, gateway `11.79 MiB / 128 MiB`. Final container IDs were `653e6acac228754110f3b34565d578ca0c536b50a0e8b411ce1e58e9076a85f4` (Playwright), `a3f2be411c692ceaf4c99290f55fe1db0f41c561bf57525c2f97cd737999bad2` (API), and `ee4ea0abd54356dafd3c35e315a250397d9691cbf84653adc16a6dbe343dc342` (gateway).

### Protected-state verification

- NuQ PostgreSQL, Redis, RabbitMQ, all Nextcloud containers, Open WebUI, Open Terminal, and SearXNG retained identical pre/post container IDs, images, and statuses; stateful Firecrawl services remained healthy.
- Tailscale serve JSON was byte-for-byte unchanged: pre/post SHA-256 `93aeda22a532473e5116a138f5e1c260f2317b5ee81a26ed43967c57cafb8070`.
- No Open WebUI, Tailscale, Funnel, existing-service, or volume mutation was performed.

## Task 7 — Open WebUI Firecrawl cutover

**DONE_WITH_CONCERNS — the scoped Open WebUI cutover passed its runtime and safety gates.** The concern is inherited from Task 6: the Firecrawl Compose configuration continues to emit the previously documented optional-variable warnings; they did not fail validation or runtime verification.

- Completed at `2026-08-20T12:10:15Z` (`2026-08-21T00:10:15+1200` local).
- External file changed: `/home/kang/docker/open-webui/compose.yaml`. Only the `open-webui` service `env_file` and `environment` entries were changed. `searxng` remains defined, running, healthy, and unchanged.
- Added `../firecrawl/secrets/api.env` as an `open-webui` env file and configured Firecrawl search/loader settings, internal gateway URL, 120-second timeout, five results, and two concurrent requests. Secret contents are not recorded.
- Direct-SearXNG rollback intentionally uses the Task 7 pre-Firecrawl backup `/home/kang/docker/firecrawl/backups/open-webui/20260820T120549Z/` because it restores SearXNG retrieval. The fresh final-fix backup `/home/kang/docker/firecrawl/backups/open-webui/20260820T150716Z/` is the rollback point for the later network-segmentation change and preserves Firecrawl retrieval; it is not a direct-SearXNG rollback source.
- Before cutover, created and retained the mode-0700 historical Task 7 rollback backup at `/home/kang/docker/firecrawl/backups/open-webui/20260820T120549Z/` (not under `/home/kang/docker/open-webui/`). It contains non-empty `webui.db` and `compose.yaml`, plus `SHA256SUMS`. The SQLite copy was made with SQLite's backup API inside the running `open-webui` container, copied out, and passed `PRAGMA integrity_check`.
- Existing retained-backup hashes: `webui.db` `fd02fca6560de7217c760d723b9041fc0e973b0e8b857882b5f0e3025f4dfb49`; `compose.yaml` `1279d5635625aeda41481efba554b76e35db8d4fd3c9e44a460b1a72a274d8db`.
- Repository helper/test verification: focused migration test passed; full deploy suite passed, 31 tests; Python compile and `git diff --check` passed.
- Cutover actions used `docker compose config --quiet`, `docker compose up -d --no-deps open-webui`, the stdin-fed migration helper, and an explicit `docker compose restart open-webui`; no other Compose service was restarted.
- Effective persisted settings after restart were verified without exposing the key: `web.search.engine=firecrawl`, `web.loader.engine=firecrawl`, `web.loader.firecrawl_api_url=http://firecrawl-gateway:8080`, `web.loader.firecrawl_timeout=120`, and `web.loader.firecrawl_api_key=set`.
- Host Open WebUI health returned 200; internal Bearer-authenticated Firecrawl readiness returned 200; `scripts/verify-local.sh` passed health, readiness, search, scrape, and SearXNG evidence checks; `scripts/resource-guard.sh post` passed with 9.0 GiB available RAM.
- 16 of 17 protected non-Open-WebUI container identities and restart counts were independently matched. The surviving historical running-container snapshot excluded `nextcloud-aio-watchtower`, so its historical identity comparison is unavailable; its current expected `exited (0)` state and restart count 0 were verified. This qualification does not imply watchtower was changed. Hermes dashboard, gateway, and language-server processes remained running.
- Tailscale serve JSON remained byte-identical, SHA-256 `93aeda22a532473e5116a138f5e1c260f2317b5ee81a26ed43967c57cafb8070`. No Funnel or Tailscale command was issued.

## Task 8 — Firecrawl Funnel port 10000 and MCP verification

**DONE — the scoped Funnel route, route-preservation checks, public authentication checks, MCP search call, protected-service checks, and the permanent committed MCP verifier fix all passed.**

- Completed at `2026-08-21T00:50:39+12:00` local. No secret value or raw status JSON was recorded.
- Re-ran `scripts/verify-local.sh`: **PASS** — healthz 200, no-key and wrong-key readiness 401, keyed readiness 200, search results, scrape Markdown, and SearXNG evidence.
- Re-ran `scripts/resource-guard.sh post`: **PASS** — 8.8 GiB available RAM; swap 2.1 GiB used of 8.0 GiB.
- The authoritative pre-deploy Tailscale status snapshot and the live pre-change snapshot were byte-identical: SHA-256 `93aeda22a532473e5116a138f5e1c260f2317b5ee81a26ed43967c57cafb8070`. Both contained only the protected 443 and 8443 routes before the change.
- Issued only `tailscale funnel --bg --yes --https=10000 http://127.0.0.1:3002`; the command reported the new public endpoint and completed successfully. Immediately saved `state/post-firecrawl-tailscale.json` and ran `scripts/verify-funnel.sh state/pre-deploy-tailscale.json`.
- Post-deploy status hash: `a9d86c3303e38addf567acff6630570778f0a4dba0bf3c48ca71a7883813d4d9`; a subsequent live status snapshot had the same hash.
- Route preservation: **PASS**. Port 443 retained `HTTPS`, proxy `http://127.0.0.1:11000`, and no `AllowFunnel` entry (tailnet-only). Port 8443 retained `HTTPS`, proxy `http://127.0.0.1:3000`, and its host-qualified `AllowFunnel` entry. Port 10000 added `HTTPS`, proxy `http://127.0.0.1:3002`, and its host-qualified `AllowFunnel` entry.
- Public Firecrawl authentication: **PASS** — `https://the-dream-land.taile6fad0.ts.net:10000/v0/health/readiness` returned 401 without a key and 200 with the configured Bearer key. The key value was never printed.
- The pre-fix mandated `/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py` returned `FAIL` before adapter initialization because `BoundedStderr` was an in-memory `StringIO` and the installed MCP client called `fileno()`. The fake-client descriptor contract was strengthened first and the focused test went **RED** with that failure. The committed fix now opens a scoped text handle to `os.devnull`; the focused MCP tests then passed **GREEN**, with no secret output.
- Post-fix verification: the exact `/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py` command returned exactly `tools: 27` followed by `PASS` on stdout and empty stderr, including a successful `firecrawl_search` call. The child diagnostic sink is a real descriptor and cannot forward or accumulate warnings.
- Post-fix repository gates: the full deploy suite passed **34 tests**; `python -m py_compile scripts/verify-mcp.py deploy/tests/test_scripts.py` passed; and `git diff --check` passed.
- Post-fix route/auth/service/resource checks: `scripts/verify-funnel.sh state/pre-deploy-tailscale.json` passed public readiness 401/200 and route preservation; Open WebUI 8443 `/health` and Nextcloud 443 `/status.php` returned success; `scripts/resource-guard.sh post` passed with 8.6 GiB available RAM. No Tailscale mutation command was issued.
- Existing service checks: **PASS** — `curl --fail --silent --show-error https://the-dream-land.taile6fad0.ts.net:8443/health` and `curl --fail --silent --show-error https://the-dream-land.taile6fad0.ts.net/status.php` both returned zero. The former verified public Funnel-enabled Open WebUI; the latter verified tailnet-only Nextcloud 443 from the host.
- Container/process check: all active Firecrawl, Nextcloud, Open WebUI, Open Terminal, and SearXNG containers remained running/healthy; the expected one-shot `nextcloud-aio-watchtower` remained `Exited (0)`. Hermes dashboard, Hermes gateway, and the Pyright language-server processes were present. No unrelated service was restarted.
- No rollback was needed or run because route preservation and public authentication both passed. Ports 443 and 8443 were not modified.

## Historical Task 9 — backup, stop/start recovery, operations documentation, and final acceptance

**Historical pre-final-fix acceptance: DONE_WITH_CONCERNS — all automated and manual criteria PASS; inherited optional-variable warnings and deferred minor concerns remain.** Completed at `2026-08-21T01:36:51+12:00` local on historical deployed commit `9511633eb42110fadd11919591dd44fc5b1e7df7`; browser acceptance was confirmed at `2026-08-21T02:14:58+12:00`. The authoritative runtime source for the later final-fix state remains `053e71397ee378fdefa7a4098fb9b68af5d964ed`; the final documentation head after this follow-up is documentation-only.

### Cold backup

- Exact command executed: `scripts/backup.sh`.
- Backup path: `/home/kang/docker/firecrawl/backups/20260820T132923Z/`.
- The backup script stopped and restarted only Firecrawl services; it did not run restore.
- `manifest.txt`, `SHA256SUMS`, and all three expected non-empty archives are present. Archive sizes and SHA-256 hashes:

| Archive | Size | SHA-256 | Tar listing entries |
|---|---:|---|---:|
| `postgres.tar.gz` | 5,756,445 bytes | `b49fc83c106444c81a68bf2761bb378b121c634fc41213d8439b89a29a71df02` | 1,049 |
| `redis.tar.gz` | 405 bytes | `d74236ef0b343f9bb0f8f4a0a5d980a8926e5c59a18ed4a5f2a23c32c1e73710` | 2 |
| `rabbitmq.tar.gz` | 167,604 bytes | `c9a3f28729cade41461850a9cde659f876bce6dcec0d5fd1dc745c37570e6366` | 73 |

- `tar -tzf` inspection passed for every archive; no production restore was run.
- The literal brief command `sha256sum -c "$latest/SHA256SUMS"` was executed from the repository root and returned nonzero because `SHA256SUMS` contains archive basenames while the shell working directory was not the backup directory. The corrected, equivalent verification `cd "$latest" && sha256sum -c SHA256SUMS` returned `postgres.tar.gz: OK`, `rabbitmq.tar.gz: OK`, and `redis.tar.gz: OK`. This is a relative-path defect in the brief command, not a backup integrity failure.

### Firecrawl-only stop/start recovery and persistence

The required non-secret indicators were captured before and after the exact recovery commands. PostgreSQL reported `accepting connections`, database `postgres`, and `0` public tables; Redis reported `PONG` and `dbsize 7`; RabbitMQ ping succeeded and the four expected queues all reported `0` ready and `0` unacknowledged messages. The named volume mountpoints remained:

- `firecrawl-postgres-data` → `/var/lib/docker/volumes/firecrawl-postgres-data/_data`
- `firecrawl-redis-data` → `/var/lib/docker/volumes/firecrawl-redis-data/_data`
- `firecrawl-rabbitmq-data` → `/var/lib/docker/volumes/firecrawl-rabbitmq-data/_data`

The exact authorized recovery commands were executed:

```bash
scripts/compose.sh stop gateway api playwright-service redis rabbitmq nuq-postgres
scripts/compose.sh up -d nuq-postgres redis rabbitmq playwright-service api gateway
scripts/verify-local.sh
scripts/resource-guard.sh post
```

The immediate verification observed `healthz: ERROR` while the newly-started gateway was still in `starting`; no unrelated service was changed. After polling the five Firecrawl health states, the required verification was rerun and passed: healthz `200`, no-key/wrong-key readiness `401`, keyed readiness `200`, search `200` with non-empty results, scrape `200` with Markdown, SearXNG log marker, and post resource guard. Final Firecrawl service states were API/gateway/NuQ PostgreSQL/Redis/RabbitMQ `running healthy`, Playwright `running`, all exit codes `0`.

### Documentation and external README

- Created `docs/operations/the-dream-land.md` with exact status/log, start/stop/restart, local/Funnel/MCP verification, safe key retrieval over local TTY or trusted SSH, key rotation and persisted Open WebUI update, cold backup and confirmation-gated restore, reviewed-tag upgrade/rebuild, Funnel `10000` disable/re-enable, direct-SearXNG Open WebUI rollback, and full Firecrawl rollback without volume deletion guidance.
- Updated external `/home/kang/docker/open-webui/README.md` separately (not part of the Firecrawl commit): routing table now maps `10000` to the loopback Firecrawl gateway at `127.0.0.1:3002`; it identifies SearXNG as Firecrawl's internal provider and documents `../firecrawl/secrets/api.env` as the secret location without embedding a value. Existing warnings about deliberate Funnel exposure, loopback-only backends, and root-path applications were preserved.

### Complete automated acceptance

All requested automated gates passed after the documentation changes:

| Criterion | Result |
|---|---|
| `python -m unittest discover -s deploy/tests -v` | **PASS** — 34 tests |
| `scripts/compose.sh config --quiet` | **PASS**; existing optional-variable warnings only |
| `scripts/verify-local.sh` | **PASS** — health/readiness/auth/search/scrape/SearXNG |
| `scripts/verify-funnel.sh state/pre-deploy-tailscale.json` | **PASS** — public `401`/`200`, protected route preservation |
| `/usr/local/lib/hermes-agent/venv/bin/python scripts/verify-mcp.py` | **PASS** — `tools: 27`, `PASS` |
| `scripts/resource-guard.sh post` | **PASS** — 8.5 GiB available RAM; 2.1/8.0 GiB swap used |
| `git diff --check` | **PASS** |
| Compose/container status | **PASS** — Firecrawl, Open WebUI, Nextcloud, Open Terminal, and SearXNG healthy/running; expected one-shot watchtower state unchanged |
| FoundationDB absence | **PASS** — no active FoundationDB container |
| Resource threshold | **PASS** — `free -h` reported 15 GiB total and 8.5 GiB available |
| Tailscale status capture | **PASS** — live status saved privately; post-route status hash remains `a9d86c3303e38addf567acff6630570778f0a4dba0bf3c48ca71a7883813d4d9`; baseline protected-route hash is `93aeda22a532473e5116a138f5e1c260f2317b5ee81a26ed43967c57cafb8070` |
| Browser Open WebUI search | **PASS** — exact query and visible sourced-result confirmation recorded below; safe Firecrawl SearXNG search and page-scrape/Playwright markers confirmed |

### Manual browser acceptance

- Exact browser query: `What is Firecrawl self-hosting?`
- Visible result confirmation: the user confirmed that Open WebUI visibly displayed sourced results.
- Confirmation timestamp: `2026-08-21T02:14:58+12:00`.
- Safe controller read-only Firecrawl log markers confirmed SearXNG search plus page-scrape/Playwright success: `Using searxng search`; `runWebScraper called`; `running scrapeURL`; `Scraping URL`; `Scraping via playwright`; `Scrape via playwright deemed successful`.

No secrets, raw Tailscale JSON, or response bodies were added to this record. No restore was run, no Tailscale route was altered during Task 9, no unrelated service was restarted, no global Git configuration was changed, and no push was performed.
