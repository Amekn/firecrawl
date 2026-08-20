# Task 3 Report — Bearer Authentication Gateway

## Result

Implemented Task 3 on `local/the-dream-land-deployment` with strict RED/GREEN TDD. No containers, external services, global configuration, or pushes were used.

## RED evidence

Command:

```bash
python -m unittest deploy.tests.test_gateway -v
```

Outcome: **FAIL**, 2 tests failed because `deploy/nginx/default.conf.template` was missing. The failure message was:

```text
AssertionError: False is not true : missing gateway template: /home/kang/docker/firecrawl/deploy/nginx/default.conf.template
```

## GREEN evidence

Command:

```bash
python -m unittest deploy.tests.test_gateway -v
```

Outcome: **PASS**, 2 tests ran and passed (`OK`). The tests verify:

- Exact `"Bearer ${FIRECRAWL_API_KEY}" 1;` match.
- `return 401` gate.
- Authorization stripping with `proxy_set_header Authorization "";`.
- `proxy_pass http://api:3002;` upstream.
- `limit_req_zone` and `rate=60r/m`.
- Exact `/healthz` location.
- `proxy_read_timeout 360s`.
- No `proxy_pass` to localhost and no literal 64-hex secret.

Additional regression command:

```bash
python -m unittest discover -s deploy/tests -v
```

Outcome: **PASS**, 10 tests ran and passed (`OK`).

## Files

- Created `deploy/nginx/default.conf.template` with the specified Bearer-auth gateway, unauthenticated `/healthz`, API upstream, rate limit, header stripping, and timeout settings.
- Created `deploy/tests/test_gateway.py` with static template assertions and negative secret/localhost checks.

## Self-review

Command:

```bash
git diff --cached --check
```

Outcome: clean; no whitespace errors.

The staged review contained exactly the two requested files and 69 insertions. Post-commit status was clean on `local/the-dream-land-deployment`.

## Commit

```text
c6e1b5a03a9f8d885a4e3fcecd5441b6d01b0f31
feat: add Bearer-auth Firecrawl gateway
```

## Concerns

None. The requested focused and deploy test suites pass. No push or external-state changes were performed.

## Fix round 1 — case-sensitive exact credential matching

### Finding addressed

The original plain-string Nginx `map` key was replaced with an anchored, case-sensitive regex. The focused gateway test now requires the exact `~^Bearer ${FIRECRAWL_API_KEY}$` rule, rejects the old plain-string entry, and rejects the case-insensitive `~*` form.

### RED evidence

After updating `deploy/tests/test_gateway.py` and before updating the template, the focused test failed because the existing plain-string map entry did not satisfy the required regex. This preserves test-first evidence for the fix.

### Clean verification outputs

Focused gateway tests:

```bash
python -m unittest deploy.tests.test_gateway -v
```

```text
test_gateway_template_contains_required_auth_proxy_controls (deploy.tests.test_gateway.GatewayTemplateTests.test_gateway_template_contains_required_auth_proxy_controls) ... ok
test_gateway_template_has_no_literal_secret_or_localhost_upstream (deploy.tests.test_gateway.GatewayTemplateTests.test_gateway_template_has_no_literal_secret_or_localhost_upstream) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.000s

OK
```

Deploy test suite:

```bash
python -m unittest discover -s deploy/tests -v
```

```text
test_api_has_no_host_port_and_gateway_is_loopback_only (test_compose.ComposeInvariantTests.test_api_has_no_host_port_and_gateway_is_loopback_only) ... ok
test_api_networks_and_required_external_network (test_compose.ComposeInvariantTests.test_api_networks_and_required_external_network) ... ok
test_api_runtime_environment_and_persistent_volumes (test_compose.ComposeInvariantTests.test_api_runtime_environment_and_persistent_volumes) ... ok
test_direct_images_and_backup_helper_are_digest_pinned (test_compose.ComposeInvariantTests.test_direct_images_and_backup_helper_are_digest_pinned) ... ok
test_foundationdb_services_are_profiled (test_compose.ComposeInvariantTests.test_foundationdb_services_are_profiled) ... ok
test_no_non_gateway_service_has_host_published_ports (test_compose.ComposeInvariantTests.test_no_non_gateway_service_has_host_published_ports) ... ok
test_gateway_template_contains_required_auth_proxy_controls (test_gateway.GatewayTemplateTests.test_gateway_template_contains_required_auth_proxy_controls) ... ok
test_gateway_template_has_no_literal_secret_or_localhost_upstream (test_gateway.GatewayTemplateTests.test_gateway_template_has_no_literal_secret_or_localhost_upstream) ... ok
test_existing_secret_permissions_are_restricted_without_regeneration (test_secrets.SecretGenerationTests.test_existing_secret_permissions_are_restricted_without_regeneration) ... ok
test_generates_private_hex_secrets_and_is_idempotent (test_secrets.SecretGenerationTests.test_generates_private_hex_secrets_and_is_idempotent) ... ok

----------------------------------------------------------------------
Ran 10 tests in 0.177s

OK
```

### Self-review

- `deploy/nginx/default.conf.template`: only the credential map entry changed; all existing directives remain present.
- `deploy/tests/test_gateway.py`: the regression assertions require the anchored case-sensitive `~` regex and reject both the old plain-string entry and `~*` form.
- `git diff --check` completed successfully with no output.
- No containers, external services, global Git configuration, or pushes were used.

### Fix-round commit

The final commit SHA is reported with the task result after commit completion.
