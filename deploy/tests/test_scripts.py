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
HERMES_PYTHON = Path("/usr/local/lib/hermes-agent/venv/bin/python")
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
            for mode, below, exact, above in (
                ("pre", "3145727", "3145728", "3145729"),
                ("post", "6291455", "6291456", "6291457"),
            ):
                for available, expected in ((below, False), (exact, True), (above, True)):
                    environment["MEM_AVAILABLE_KIB"] = available
                    result = subprocess.run(
                        ["bash", str(guard), mode],
                        cwd=REPO_ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, expected, f"{mode} {available}")
                    if expected:
                        self.assertIn("Mem:", result.stdout)
                        self.assertIn("Swap:", result.stdout)
                        self.assertNotIn("MEM_AVAILABLE_KIB", result.stdout)
                    else:
                        self.assertIn("resource guard failed", result.stderr)

            invalid = subprocess.run(
                ["bash", str(guard), "invalid"],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("usage:", invalid.stderr)

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
                    #!/usr/bin/env python3
                    import json
                    import sys

                    args = sys.argv[1:]
                    output = args[args.index('--output') + 1]
                    method = args[args.index('--request') + 1]
                    url = args[-1]
                    headers = [args[index + 1] for index, value in enumerate(args[:-1]) if value == '-H']
                    body = args[args.index('--data') + 1] if '--data' in args else None
                    expected_auth = 'Authorization: Bearer local-secret-that-must-not-be-printed'
                    expected = {
                        ('GET', 'http://example.test:3002/healthz', (), None): (200, {}),
                        ('GET', 'http://example.test:3002/v0/health/readiness', (), None): (401, {}),
                        ('GET', 'http://example.test:3002/v0/health/readiness', ('Authorization: Bearer wrong',), None): (401, {}),
                        ('GET', 'http://example.test:3002/v0/health/readiness', (expected_auth,), None): (200, {}),
                        ('POST', 'http://example.test:3002/v2/search', ('Content-Type: application/json', expected_auth), '{"query":"Firecrawl self hosting","sources":["web"]}'): (200, {'data': {'web': [{'url': 'https://example.com'}]}}),
                        ('POST', 'http://example.test:3002/v2/scrape', ('Content-Type: application/json', expected_auth), '{"url":"https://example.com","formats":["markdown"]}'): (200, {'data': {'markdown': '# Example'}}),
                    }
                    key = (method, url, tuple(headers), body)
                    if key not in expected:
                        raise SystemExit('unexpected curl request: ' + repr(key))
                    status, payload = expected[key]
                    with open(output, 'w', encoding='utf-8') as stream:
                        json.dump(payload, stream)
                    print(status, end='')
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
                    "FIRECRAWL_VERIFICATION_OUTPUT_DIR": str(output_directory),
                    "FIRECRAWL_COMPOSE_SCRIPT": str(compose),
                    "FIRECRAWL_LOCAL_URL": "http://example.test:3002",
                }
            )
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
                    #!/usr/bin/env python3
                    import sys

                    args = sys.argv[1:]
                    output = args[args.index('--output') + 1]
                    method = args[args.index('--request') + 1]
                    url = args[-1]
                    headers = [args[index + 1] for index, value in enumerate(args[:-1]) if value == '-H']
                    expected = {
                        ('GET', 'https://example.test:10000/v0/health/readiness', ()): '401',
                        ('GET', 'https://example.test:10000/v0/health/readiness', ('Authorization: Bearer test-secret-that-must-not-be-printed',)): '200',
                    }
                    key = (method, url, tuple(headers))
                    if key not in expected:
                        raise SystemExit('unexpected curl request: ' + repr(key))
                    with open(output, 'w', encoding='utf-8') as stream:
                        stream.write('{}\\n')
                    print(expected[key], end='')
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (fake_bin / "curl").chmod(0o700)
            (fake_bin / "tailscale").write_text(
                "#!/usr/bin/env python3\nimport os\nimport sys\nassert sys.argv[1:] == ['funnel', 'status', '--json']\nprint(open(os.environ['MOCK_TAILSCALE_JSON'], encoding='utf-8').read(), end='')\n",
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

            for section, port in (
                ("TCP", "443"),
                ("TCP", "8443"),
                ("Web", "443"),
                ("Web", "8443"),
                ("AllowFunnel", "443"),
                ("AllowFunnel", "8443"),
            ):
                missing = json.loads(json.dumps(baseline))
                del missing[section][port]
                current_path.write_text(json.dumps(missing), encoding="utf-8")
                missing_result = subprocess.run(
                    ["bash", str(funnel), str(baseline_path)],
                    cwd=REPO_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(missing_result.returncode, 0, f"missing {section} {port}")
                self.assertNotIn(secret, missing_result.stdout + missing_result.stderr)

            for malformed in (
                {**baseline, "Web": []},
                {**baseline, "AllowFunnel": {"443": "false", "8443": True}},
                {**baseline, "TCP": {"443": None, "8443": "127.0.0.1:8443"}},
            ):
                current_path.write_text(json.dumps(malformed), encoding="utf-8")
                malformed_result = subprocess.run(
                    ["bash", str(funnel), str(baseline_path)],
                    cwd=REPO_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(malformed_result.returncode, 0)
                self.assertNotIn(secret, malformed_result.stdout + malformed_result.stderr)

            current_path.write_text(json.dumps({}), encoding="utf-8")
            empty_result = subprocess.run(
                ["bash", str(funnel), str(current_path)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(empty_result.returncode, 0)

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
                    async def stdio_client(server, *, errlog):
                        errlog.write('child warning with mcp-secret-that-must-not-be-printed\\n')
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
                [str(HERMES_PYTHON), str(verifier)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "tools: 1\nPASS\n")
            self.assertEqual(result.stderr, "")
            self.assertNotIn(secret, result.stdout + result.stderr)

            text = verifier.read_text(encoding="utf-8")
            self.assertIn("call_tool(", text)
            self.assertIn('"firecrawl_search"', text)
            self.assertIn('"FIRECRAWL_API_KEY": key', text)

    def test_mcp_verifier_rejects_wrong_interpreter_and_missing_dependency_secret_safe(self) -> None:
        verifier = SCRIPTS_DIR / "verify-mcp.py"
        secret = "interpreter-secret-that-must-not-be-printed"
        with tempfile.TemporaryDirectory() as temporary_directory:
            secret_path = Path(temporary_directory) / "api.env"
            secret_path.write_text(f"FIRECRAWL_API_KEY={secret}\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "FIRECRAWL_API_ENV_FILE": str(secret_path),
                    "PYTHONPATH": "",
                }
            )

            wrong_interpreter = subprocess.run(
                [sys.executable, str(verifier)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(wrong_interpreter.returncode, 0)
            self.assertEqual(wrong_interpreter.stdout, "")
            self.assertEqual(wrong_interpreter.stderr, "FAIL\n")
            self.assertNotIn(secret, wrong_interpreter.stdout + wrong_interpreter.stderr)

            missing_dependency = subprocess.run(
                [str(HERMES_PYTHON), "-S", str(verifier)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing_dependency.returncode, 0)
            self.assertEqual(missing_dependency.stdout, "")
            self.assertEqual(missing_dependency.stderr, "FAIL\n")
            self.assertNotIn(secret, missing_dependency.stdout + missing_dependency.stderr)

    def test_mcp_verifier_selects_hermes_interpreter_in_executable_contract(self) -> None:
        text = (SCRIPTS_DIR / "verify-mcp.py").read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "#!/usr/local/lib/hermes-agent/venv/bin/python")
        self.assertIn("/usr/local/lib/hermes-agent/venv/bin/python", text)
        self.assertNotRegex(text, r"(?m)^from mcp(?:\.| )", msg="mcp must be imported inside the guarded path")


if __name__ == "__main__":
    unittest.main()
