# Task 4 Report — Resource, Verification, and MCP Scripts

## Status

`DONE`

Implemented Task 4 on `local/the-dream-land-deployment`. No containers or live services were started or called; all endpoint, Tailscale, Compose-log, and MCP checks were exercised with local mocks/overrides only. No global configuration, external state, subagents, or push was used.

## RED evidence

Command run before creating the four scripts:

```bash
python -m unittest deploy.tests.test_scripts -v
```

Exact outcome:

```text
test_funnel_verifier_preserves_443_and_8443_entries_exactly (deploy.tests.test_scripts.DeploymentScriptTests.test_funnel_verifier_preserves_443_and_8443_entries_exactly) ... FAIL
test_mcp_verifier_uses_secret_and_calls_search_with_mock_mcp (deploy.tests.test_scripts.DeploymentScriptTests.test_mcp_verifier_uses_secret_and_calls_search_with_mock_mcp) ... FAIL
test_resource_guard_enforces_exact_pre_and_post_thresholds (deploy.tests.test_scripts.DeploymentScriptTests.test_resource_guard_enforces_exact_pre_and_post_thresholds) ... FAIL
test_shell_scripts_are_strict_and_syntax_checked (deploy.tests.test_scripts.DeploymentScriptTests.test_shell_scripts_are_strict_and_syntax_checked) ... FAIL
test_verification_scripts_do_not_print_api_key (deploy.tests.test_scripts.DeploymentScriptTests.test_verification_scripts_do_not_print_api_key) ... ERROR

======================================================================
ERROR: test_verification_scripts_do_not_print_api_key (deploy.tests.test_scripts.DeploymentScriptTests.test_verification_scripts_do_not_print_api_key)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/kang/docker/firecrawl/deploy/tests/test_scripts.py", line 47, in test_verification_scripts_do_not_print_api_key
    text = script.read_text(encoding="utf-8")
  File "/usr/lib64/python3.14/pathlib/__init__.py", line 787, in read_text
    with self.open(mode, buffering, encoding, errors, newline) as f:
         ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib64/python3.14/pathlib/__init__.py", line 771, in open
    return io.open(self, mode, buffering, encoding, errors, newline)
FileNotFoundError: [Errno 2] No such file or directory: '/home/kang/docker/firecrawl/scripts/verify-local.sh'

----------------------------------------------------------------------
Ran 5 tests in 0.015s

FAILED (failures=4, errors=1)
```

The failures were due to the required scripts being absent.

## GREEN evidence

Focused command after implementation and before commit:

```bash
python -m unittest deploy.tests.test_scripts -v
```

Exact outcome:

```text
test_funnel_verifier_preserves_443_and_8443_entries_exactly (deploy.tests.test_scripts.DeploymentScriptTests.test_funnel_verifier_preserves_443_and_8443_entries_exactly) ... ok
test_local_verifier_checks_auth_search_scrape_and_logs_without_live_services (deploy.tests.test_scripts.DeploymentScriptTests.test_local_verifier_checks_auth_search_scrape_and_logs_without_live_services) ... ok
test_mcp_verifier_uses_secret_and_calls_search_with_mock_mcp (deploy.tests.test_scripts.DeploymentScriptTests.test_mcp_verifier_uses_secret_and_calls_search_with_mock_mcp) ... ok
test_resource_guard_enforces_exact_pre_and_post_thresholds (deploy.tests.test_scripts.DeploymentScriptTests.test_resource_guard_enforces_exact_pre_and_post_thresholds) ... ok
test_shell_scripts_are_strict_and_syntax_checked (deploy.tests.test_scripts.DeploymentScriptTests.test_shell_scripts_are_strict_and_syntax_checked) ... ok
test_verification_scripts_do_not_print_api_key (deploy.tests.test_scripts.DeploymentScriptTests.test_verification_scripts_do_not_print_api_key) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.151s

OK
```

Post-commit focused command also passed with 6 tests (`OK`, 0.161s).

Syntax checks:

```bash
bash -n scripts/resource-guard.sh scripts/verify-local.sh scripts/verify-funnel.sh
python -m py_compile scripts/verify-mcp.py deploy/tests/test_scripts.py
```

Outcome: exit code `0`, no stdout/stderr.

## Implemented behavior

- `resource-guard.sh`: strict Bash, exact `pre=3 GiB` and `post=6 GiB` available-RAM thresholds, `MEM_AVAILABLE_KIB` override, non-zero failure below threshold, and aggregate `Mem:`/`Swap:` output only from `free -h`.
- `verify-local.sh`: sources `secrets/api.env` without tracing; checks health `200`, readiness `401/401/200`, authenticated `/v2/search` with `Firecrawl self hosting` and non-empty web results, authenticated `/v2/scrape` for `https://example.com` and non-empty Markdown, and `scripts/compose.sh logs --since=5m api` for `Using searxng search`. Response/log files are temporary children of `verification-output/` and removed by an exit trap; output is named checks/statuses only.
- `verify-funnel.sh`: checks public readiness `401` without a key and `200` with the key, then compares baseline/current `TCP`, `Web`, and `AllowFunnel` entries for ports `443` and `8443` exactly using Python.
- `verify-mcp.py`: reads `FIRECRAWL_API_KEY` from `secrets/api.env`, starts `npx -y firecrawl-mcp` through the `mcp` client, requires `firecrawl_search`, calls it with the specified query/limit, and outputs only tool count plus `PASS` on success.
- `deploy/tests/test_scripts.py`: strict-mode/syntax/no-tracing/no-key-output checks, exact RAM override tests, fully mocked local verification including cleanup and all required status/search/scrape/log checks, mocked Funnel route-preservation checks including a changed-handler rejection, and a mocked MCP tool call with secret-output assertions.

## Self-review

- `git diff --cached --check` passed before commit.
- `git show --check --stat --oneline HEAD` passed after commit.
- Shell scripts are executable (`0755`); Python verifier/tests are syntax-checked.
- Final `git status --short --branch` is clean on `local/the-dream-land-deployment`.
- No response bodies, credentials, or live-service output were printed by the mocked verification runs.

## Files

- Created `scripts/resource-guard.sh`
- Created `scripts/verify-local.sh`
- Created `scripts/verify-funnel.sh`
- Created `scripts/verify-mcp.py`
- Created `deploy/tests/test_scripts.py`

## Commit

```text
ccf8adadd3e49b1f59584e2fceb77fea1411860d
test: add deployment safety and verification scripts
```

## Concerns

None. Runtime verification against actual containers, Tailscale, and the installed Hermes venv MCP package remains intentionally deferred to the later deployment task because this task explicitly forbids live-service calls.

## Fix round 1 — Important findings

### Scope and implementation

Fixed all five Important findings from `task-4-findings-round-1.md`:

- **I1:** `verify-mcp.py` now has the exact Hermes venv shebang and checks `sys.executable` against `/usr/local/lib/hermes-agent/venv/bin/python`. MCP imports moved inside the guarded verification path. Tests cover wrong-interpreter execution and a missing dependency under Hermes `-S`; both produce only `FAIL` on stderr with no traceback or secret.
- **I2:** `verify-mcp.py` passes a bounded `BoundedStderr` sink to `stdio_client(..., errlog=...)`. The MCP fake emits a child warning containing the test secret; the successful contract asserts exact `tools: 1\\nPASS\\n` stdout and empty stderr.
- **I3:** `verify-funnel.sh` now validates both documents before comparison and requires all six exact `TCP`, `Web`, and `AllowFunnel` entries for `443` and `8443`, with type/non-empty checks appropriate to each section. Tests cover all six missing-entry mutations, malformed sections/values, an empty status, and a changed handler.
- **I4:** Local and Funnel curl mocks now require exact method, URL/path, headers, content type, JSON body, auth value, and Tailscale command. Search/scrape payloads and the public readiness URL are asserted exactly; permissive suffix/header matching was removed from the tests.
- **I5:** Resource-guard tests now enforce `pre` at `3145728` KiB (3 GiB) and `post` at `6291456` KiB (6 GiB), each with immediately-below, exact, and immediately-above values, plus invalid-mode exit `2`. The implementation constants remain unchanged.

Covering files:

- `deploy/tests/test_scripts.py`
- `scripts/verify-funnel.sh`
- `scripts/verify-mcp.py`

`verify-local.sh` and `scripts/resource-guard.sh` required no production change in this round; the tightened tests now enforce their existing correct auth and threshold behavior.

### RED evidence (tests-first)

Command run immediately after adding the regressions and before the script fixes:

```bash
python -m unittest deploy.tests.test_scripts -v
```

Exact result: four failures, with the route comparator accepting an empty status (`AssertionError: 0 == 0`), the wrong-interpreter run emitting a `ModuleNotFoundError` traceback instead of `FAIL`, the shebang remaining `#!/usr/bin/env python3`, and the MCP success mock returning `FAIL`; the command ended with:

```text
Ran 8 tests in 0.959s
FAILED (failures=4)
```

### GREEN and verification evidence

Focused command:

```bash
python -m unittest deploy.tests.test_scripts -v
```

Exact clean output:

```text
Ran 8 tests in 0.936s

OK
```

Full deploy test suite:

```bash
python -m unittest discover -s deploy/tests -v
```

Exact clean output:

```text
Ran 18 tests in 1.192s

OK
```

Additional verification command:

```bash
bash -n scripts/*.sh
python -m py_compile scripts/verify-mcp.py deploy/tests/test_scripts.py
git diff --check
```

Exact clean result: no stdout or stderr; exit code `0`.

### Self-review

- Test-first RED was observed for the new MCP, route, and strict-contract regressions before implementation.
- `git diff --cached --check` passed before the implementation commit.
- `git show --check --stat --oneline HEAD` passed after the implementation commit.
- No live services, containers, Tailscale state, global configuration, or external systems were touched.
- Final implementation commit is limited to the focused test and Funnel/MCP changes.

### Commit and concerns

Implementation commit:

```text
494ded7dd20a43a80a4aeff217fdc59b613b7c2c
fix: harden deployment verification regressions
```

Concerns: runtime verification against actual containers, Tailscale, public endpoints, and the installed Hermes MCP child remains intentionally deferred to Task 6/runtime verification. No other concerns.
