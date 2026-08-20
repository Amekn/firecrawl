from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SHELL_SCRIPTS = tuple(sorted(SCRIPTS_DIR.glob("*.sh")))
VERIFICATION_SCRIPTS = (
    SCRIPTS_DIR / "verify-local.sh",
    SCRIPTS_DIR / "verify-funnel.sh",
    SCRIPTS_DIR / "verify-mcp.py",
)


class DeploymentScriptTests(unittest.TestCase):
    def test_shell_scripts_are_strict_and_syntax_checked(self) -> None:
        for script in SHELL_SCRIPTS:
            self.assertTrue(script.is_file(), f"missing script: {script}")
            self.assertTrue(script.stat().st_mode & stat.S_IXUSR, script.name)
            text = script.read_text(encoding="utf-8")
            self.assertGreaterEqual(len(text.splitlines()), 2)
            self.assertEqual(text.splitlines()[1], "set -euo pipefail", script.name)
            self.assertNotRegex(text, r"(?m)^\s*set\s+-x(?:\s|$)", script.name)
            result = subprocess.run(
                ["bash", "-n", str(script)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_verification_scripts_do_not_print_api_key(self) -> None:
        for script in VERIFICATION_SCRIPTS:
            text = script.read_text(encoding="utf-8")
            self.assertNotRegex(
                text,
                r"(?im)\b(?:echo|printf|print)\b[^\n]*FIRECRAWL_API_KEY",
                script.name,
            )

    def test_resource_guard_enforces_exact_pre_and_post_thresholds(self) -> None:
        guard = SCRIPTS_DIR / "resource-guard.sh"
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_bin = Path(temporary_directory)
            free = fake_bin / "free"
            free.write_text(
                "#!/usr/bin/env bash\nprintf '              total        used        free      shared  buff/cache   available\\nMem:           15Gi        1Gi        8Gi        0Gi        6Gi       14Gi\\nSwap:           2Gi        0Gi        2Gi\\n'\n",
                encoding="utf-8",
            )
            free.chmod(0o700)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            for mode, low, high in (
                ("pre", "2097152", "7340032"),
                ("post", "2097152", "7340032"),
            ):
                environment["MEM_AVAILABLE_KIB"] = low
                failed = subprocess.run(
                    ["bash", str(guard), mode],
                    cwd=REPO_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(failed.returncode, 0, mode)
                self.assertIn("resource guard failed", failed.stderr)

                environment["MEM_AVAILABLE_KIB"] = high
                passed = subprocess.run(
                    ["bash", str(guard), mode],
                    cwd=REPO_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(passed.returncode, 0, passed.stderr)
                self.assertIn("Mem:", passed.stdout)
                self.assertIn("Swap:", passed.stdout)
                self.assertNotIn("MEM_AVAILABLE_KIB", passed.stdout)

    def test_local_verifier_checks_auth_search_scrape_and_logs_without_live_services(self) -> None:
        verifier = SCRIPTS_DIR / "verify-local.sh"
        secret = "local-secret-that-must-not-be-printed"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            secret_path = root / "api.env"
            secret_path.write_text(f"FIRECRAWL_API_KEY={secret}\n", encoding="utf-8")
            secret_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            output_directory = root / "verification-output"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "curl").write_text(
                textwrap.dedent(
                    """
                    #!/usr/bin/env bash
                    set -euo pipefail
                    output=''
                    auth=''
                    url=''
                    while (($#)); do
                      case "$1" in
                        --output) output="$2"; shift 2 ;;
                        -H) auth="$2"; shift 2 ;;
                        *) url="$1"; shift ;;
                      esac
                    done
                    case "$url" in
                      */healthz) printf '{}\\n' > "$output"; printf '200' ;;
                      */v0/health/readiness)
                        printf '{}\\n' > "$output"
                        if [[ -z "$auth" ]]; then printf '401'; elif [[ "$auth" == "$EXPECTED_AUTH" ]]; then printf '200'; else printf '401'; fi
                        ;;
                      */v2/search) printf '{"data":{"web":[{"url":"https://example.com"}]}}\\n' > "$output"; printf '200' ;;
                      */v2/scrape) printf '{"data":{"markdown":"# Example"}}\\n' > "$output"; printf '200' ;;
                      *) printf '{}\\n' > "$output"; printf '404' ;;
                    esac
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (fake_bin / "curl").chmod(0o700)
            compose = root / "compose.sh"
            compose.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'Using searxng search\\n'\n",
                encoding="utf-8",
            )
            compose.chmod(0o700)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "FIRECRAWL_API_ENV_FILE": str(secret_path),
                    "EXPECTED_AUTH": f"Authorization: Bearer {secret}",
                    "FIRECRAWL_VERIFICATION_OUTPUT_DIR": str(output_directory),
                    "FIRECRAWL_COMPOSE_SCRIPT": str(compose),
                    "FIRECRAWL_LOCAL_URL": "http://example.test:3002",
                }
            )
            probe = subprocess.run(
                [
                    str(fake_bin / "curl"),
                    "--silent",
                    "--show-error",
                    "--output",
                    str(root / "probe"),
                    "--write-out",
                    "%{http_code}",
                    "--request",
                    "GET",
                    "http://example.test:3002/healthz",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stdout, "200")
            result = subprocess.run(
                ["bash", str(verifier)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "healthz: 200\n"
                "readiness without key: 401\n"
                "readiness with wrong key: 401\n"
                "readiness with key: 200\n"
                "search: 200\n"
                "search results: PASS\n"
                "scrape: 200\n"
                "scrape Markdown: PASS\n"
                "searxng logs: PASS\n",
            )
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertEqual(list(output_directory.iterdir()), [])

    def test_funnel_verifier_preserves_443_and_8443_entries_exactly(self) -> None:
        funnel = SCRIPTS_DIR / "verify-funnel.sh"
        baseline = {
            "TCP": {"443": "127.0.0.1:443", "8443": "127.0.0.1:8443"},
            "Web": {
                "443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:443"}}},
                "8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8443"}}},
            },
            "AllowFunnel": {"443": False, "8443": True},
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline_path = root / "baseline.json"
            current_path = root / "current.json"
            secret_path = root / "api.env"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            current_path.write_text(json.dumps(baseline), encoding="utf-8")
            secret = "test-secret-that-must-not-be-printed"
            secret_path.write_text(f"FIRECRAWL_API_KEY={secret}\n", encoding="utf-8")
            secret_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "curl").write_text(
                textwrap.dedent(
                    """
                    #!/usr/bin/env bash
                    set -euo pipefail
                    output=''
                    auth=''
                    while (($#)); do
                      case "$1" in
                        --output) output="$2"; shift 2 ;;
                        -H) auth="$2"; shift 2 ;;
                        *) shift ;;
                      esac
                    done
                    [[ -z "$output" ]] || printf '{}\\n' > "$output"
                    if [[ "$auth" == *'Bearer '* ]]; then
                      printf '200'
                    else
                      printf '401'
                    fi
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (fake_bin / "curl").chmod(0o700)
            (fake_bin / "tailscale").write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\ncat \"$MOCK_TAILSCALE_JSON\"\n",
                encoding="utf-8",
            )
            (fake_bin / "tailscale").chmod(0o700)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "FIRECRAWL_API_ENV_FILE": str(secret_path),
                    "FIRECRAWL_FUNNEL_URL": "https://example.test:10000",
                    "MOCK_TAILSCALE_JSON": str(current_path),
                }
            )
            result = subprocess.run(
                ["bash", str(funnel), str(baseline_path)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("401", result.stdout)
            self.assertIn("200", result.stdout)
            self.assertNotIn(secret, result.stdout + result.stderr)

            changed = dict(baseline)
            changed["Web"] = dict(baseline["Web"])
            changed["Web"]["443"] = {"Handlers": {"/": {"Proxy": "http://changed"}}}
            current_path.write_text(json.dumps(changed), encoding="utf-8")
            rejected = subprocess.run(
                ["bash", str(funnel), str(baseline_path)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertNotIn(secret, rejected.stdout + rejected.stderr)

    def test_mcp_verifier_uses_secret_and_calls_search_with_mock_mcp(self) -> None:
        verifier = SCRIPTS_DIR / "verify-mcp.py"
        secret = "mcp-secret-that-must-not-be-printed"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            secret_path = root / "api.env"
            secret_path.write_text(f"FIRECRAWL_API_KEY={secret}\n", encoding="utf-8")
            fake_packages = root / "fake_packages"
            (fake_packages / "mcp" / "client").mkdir(parents=True)
            (fake_packages / "mcp" / "__init__.py").write_text(
                textwrap.dedent(
                    """
                    from types import SimpleNamespace

                    class StdioServerParameters:
                        def __init__(self, **kwargs):
                            self.__dict__.update(kwargs)

                    class ClientSession:
                        def __init__(self, read, write):
                            self.read = read
                            self.write = write

                        async def __aenter__(self):
                            return self

                        async def __aexit__(self, exc_type, exc, traceback):
                            return False

                        async def initialize(self):
                            return None

                        async def list_tools(self):
                            return SimpleNamespace(tools=[SimpleNamespace(name='firecrawl_search')])

                        async def call_tool(self, name, arguments):
                            assert name == 'firecrawl_search'
                            assert arguments == {'query': 'Firecrawl self hosting', 'limit': 2}
                            assert self.read.env['FIRECRAWL_API_KEY'] == 'mcp-secret-that-must-not-be-printed'
                            return SimpleNamespace(isError=False)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (fake_packages / "mcp" / "client" / "__init__.py").write_text("", encoding="utf-8")
            (fake_packages / "mcp" / "client" / "stdio.py").write_text(
                textwrap.dedent(
                    """
                    from contextlib import asynccontextmanager

                    @asynccontextmanager
                    async def stdio_client(server):
                        yield type('Read', (), {'env': server.env})(), object()
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(fake_packages),
                    "FIRECRAWL_API_ENV_FILE": str(secret_path),
                    "FIRECRAWL_MCP_URL": "https://example.test:10000",
                }
            )
            result = subprocess.run(
                [sys.executable, str(verifier)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "tools: 1\nPASS\n")
            self.assertNotIn(secret, result.stdout + result.stderr)

            text = verifier.read_text(encoding="utf-8")
            self.assertIn("call_tool(", text)
            self.assertIn('"firecrawl_search"', text)
            self.assertIn('"FIRECRAWL_API_KEY": key', text)


if __name__ == "__main__":
    unittest.main()
