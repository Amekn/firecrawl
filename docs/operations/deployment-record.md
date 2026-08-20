# Local Firecrawl deployment record

## Result

**BLOCKED — runtime health gate failed before local verification.**

This record documents the Task 6 local deployment attempt. The stateful services started healthy, but the API did not become healthy and the gateway was not started. Open WebUI and Tailscale were not modified or started by this attempt.

## Source and timing

- Firecrawl git describe: `v2.11.162-14-gbcdc66d`
- Source commit before deployment: `bcdc66de0c6ff518dff61b1ee0721a7791337c37`
- Branch: `local/the-dream-land-deployment`
- Pre-state capture: `2026-08-20T22:47:55+12:00`
- Stateful-service start: `2026-08-20T23:08:01+12:00`
- Runtime/gateway start attempt: `2026-08-20T23:08:27+12:00`
- Failure cleanup: only the newly-created API and Playwright containers were stopped; stateful Firecrawl services remain running.

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

- Deploy unit tests: **PASS**, 28 tests.
- Merged Compose config: **PASS**; Compose emitted warnings for unset optional variables only.
- Pre resource guard: **PASS** at every required static, pull, and build checkpoint; available RAM remained at or above 10 GiB at those checkpoints.
- Direct image pulls: **PASS**, sequentially for Redis, RabbitMQ, and gateway.
- Source builds: **PASS**, sequentially for NuQ PostgreSQL, Playwright, and API. The first foreground API build call timed out in the tool after partial progress; the retried background build completed successfully and its resource guard passed.
- Stateful health: **PASS** — NuQ PostgreSQL, Redis, and RabbitMQ healthy; FoundationDB absent.
- API/gateway health: **FAIL** — API remained unhealthy through the health wait; gateway remained created and never started.
- Local verification (`scripts/verify-local.sh`): **NOT RUN** because the required runtime health gate failed.
- Post resource guard (`scripts/resource-guard.sh post`): **NOT RUN** because local verification was not reached.

## Container outcome

| Service | Container ID | Final state | Health |
|---|---|---|---|
| `nuq-postgres` | `ff9b9b3d603c45d96f95b7fcc3b3b760becdc799f1f452b06bc9a9e0e1babf70` | running | healthy |
| `redis` | `9931509ea26c024a6105512f03e221f9167128fc658eb51df9a58d908b415577` | running | healthy |
| `rabbitmq` | `5eb93c002d535b35f29d2897fcecbc4e41dc52cb910e14a968d5f7f8d7b192b1` | running | healthy |
| `playwright-service` | `2e5887e29a04e6dac1eea4a568f2c36a5112c9e65f29b15eb91fe1a53d6bac17` | exited (1) | no healthcheck |
| `api` | `8bc4a53caa5c99ec9f58a2620fce1cff72b39dec6012ce5ca2935c2188339157` | exited (137) | unhealthy; restart loop observed |
| `gateway` | `9b77945aa74d8db832e094c2fc54bf9b9dad599e6ca723afcc7891cfac368724` | created | not started |

## Memory and swap

| Snapshot | Available RAM | Swap used / total |
|---|---:|---:|
| Pre-deployment (`state/pre-deploy-resources.txt`) | 10 GiB | 2.8 / 8.0 GiB |
| After API build/resource checkpoint | 11 GiB | 2.9 / 8.0 GiB |
| During failed API startup | 8 GiB | 2.9 / 8.0 GiB |
| Final raw snapshot after stopping failed runtime containers | 10 GiB | 2.9 / 8.0 GiB |

The post guard was intentionally not invoked, so the final raw snapshot is not a post-guard PASS claim.

## Concerns and follow-up

- API startup repeatedly spawned the configured NuQ worker set and worker processes exited with status 137; the API health check never became healthy. The API container was limited to 3 GiB and reached approximately 2.5 GiB during diagnosis.
- The deployment configuration exposes `NUM_WORKERS_PER_QUEUE`, but the API harness also uses a separate `NUQ_WORKER_COUNT` setting whose default is five. This was not changed during the aborted deployment; review and explicitly configure the runtime worker count or memory budget before retrying.
- Compose emitted repeated warnings for unset optional variables. They did not fail static validation, but should be reviewed before a production retry.
- No Open WebUI, Tailscale, Funnel, or existing Nextcloud container was started, stopped, restarted, or modified. The pre/post Tailscale serve JSON snapshots were byte-for-byte unchanged, and the existing container IDs/statuses remained healthy.
- Port `127.0.0.1:3002` is unused after cleanup. Stateful Firecrawl containers and their named volumes remain present; no `docker compose down` or volume deletion was performed.

## Task 6 continuation: one-variable controlled retry

**BLOCKED — API recovered, but the gateway health gate failed.**

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
- The retry is therefore **BLOCKED**, with no further retry permitted under the one-variable controlled-retry rule.
