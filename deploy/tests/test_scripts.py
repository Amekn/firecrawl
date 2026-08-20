from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
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
    @contextmanager
    def _temporary_dotenv(self):
        env_file = REPO_ROOT / ".env"
        previous = env_file.read_bytes() if env_file.exists() else None
        env_file.write_text("BACKUP_HELPER_IMAGE=mock/helper:task5\n", encoding="utf-8")
        try:
            yield
        finally:
            if previous is None:
                env_file.unlink(missing_ok=True)
            else:
                env_file.write_bytes(previous)

    def _mock_runtime(self, root: Path, running: str = "") -> tuple[dict[str, str], Path]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log = root / "mock.log"
        docker = fake_bin / "docker"
        docker.write_text(
            textwrap.dedent(
                r"""
                #!/usr/bin/env python3
                import os
                import io
                from pathlib import Path
                import re
                import tarfile
                import sys

                args = sys.argv[1:]
                log = Path(os.environ["MOCK_LOG"])
                with log.open("a", encoding="utf-8") as stream:
                    stream.write("docker " + " ".join(args) + "\n")

                def mount_path(suffix):
                    for index, value in enumerate(args[:-1]):
                        if value == "-v" and args[index + 1].endswith(suffix):
                            return args[index + 1][:-len(suffix)]
                    raise SystemExit("missing mount " + suffix)

                if args[:2] == ["ps", "--filter"]:
                    if os.environ.get("MOCK_DOCKER_PS_FAIL"):
                        raise SystemExit(int(os.environ["MOCK_DOCKER_PS_FAIL"]))
                    running = os.environ.get("MOCK_RUNNING_CONTAINERS", "")
                    if running:
                        print(running)
                    raise SystemExit(0)
                if args[:2] == ["volume", "inspect"]:
                    raise SystemExit(0)
                if args[:1] == ["inspect"]:
                    print(os.environ.get("MOCK_HEALTH", "healthy"))
                    raise SystemExit(0)
                if args[:2] == ["run", "--rm"]:
                    command = args[-1]
                    if "tar -czf - ." in command:
                        archive = io.BytesIO()
                        with tarfile.open(fileobj=archive, mode="w:gz") as stream:
                            info = tarfile.TarInfo("mock-data.txt")
                            payload = b"mock backup data\n"
                            info.size = len(payload)
                            stream.addfile(info, io.BytesIO(payload))
                        sys.stdout.buffer.write(archive.getvalue())
                        raise SystemExit(0)
                    if "tar -czf /backup/" in command:
                        if os.environ.get("MOCK_REQUIRE_ARCHIVE_STREAM"):
                            raise SystemExit(77)
                        archive = re.search(r"/backup/([a-z-]+\.tar\.gz)", command).group(1)
                        backup_path = Path(mount_path(":/backup")) / archive
                        with tarfile.open(backup_path, "w:gz") as stream:
                            info = tarfile.TarInfo("mock-data.txt")
                            payload = b"mock backup data\n"
                            info.size = len(payload)
                            stream.addfile(info, __import__("io").BytesIO(payload))
                        backup_path.chmod(0o644)
                        raise SystemExit(0)
                    if "tar -tzf /backup/" in command:
                        if os.environ.get("MOCK_DOCKER_FAIL_STAGE") == "preflight":
                            raise SystemExit(41)
                        archive = re.search(r"/backup/([a-z-]+\.tar\.gz)", command).group(1)
                        try:
                            with tarfile.open(Path(mount_path(":/backup:ro")) / archive, "r:gz") as stream:
                                stream.getnames()
                        except (OSError, tarfile.TarError):
                            raise SystemExit(42)
                        raise SystemExit(0)
                    if "find /target" in command:
                        with log.open("a", encoding="utf-8") as stream:
                            stream.write("docker-clear\n")
                        if os.environ.get("MOCK_DOCKER_FAIL_STAGE") == "clear":
                            raise SystemExit(43)
                        raise SystemExit(0)
                    if "tar -xzf /backup/" in command:
                        with log.open("a", encoding="utf-8") as stream:
                            stream.write("docker-extract\n")
                        if os.environ.get("MOCK_DOCKER_FAIL_STAGE") == "extract":
                            raise SystemExit(44)
                        raise SystemExit(0)
                raise SystemExit(0)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        docker.chmod(0o700)

        compose = root / "compose.sh"
        compose.write_text(
            textwrap.dedent(
                r"""
                #!/usr/bin/env python3
                import os
                from pathlib import Path
                import sys

                args = sys.argv[1:]
                log = Path(os.environ["MOCK_LOG"])
                with log.open("a", encoding="utf-8") as stream:
                    stream.write("compose " + " ".join(args) + "\n")
                if args[:1] == ["version"]:
                    print("mock-compose-v1")
                    raise SystemExit(0)
                if args[:1] == ["ps"]:
                    print("mock-container-" + args[-1])
                    raise SystemExit(0)
                if args[:1] == ["up"] and "nuq-postgres" in args and os.environ.get("MOCK_COMPOSE_FAIL_STAGE") in {"stateful-up", "start"}:
                    raise SystemExit(51)
                if args[:1] == ["stop"] and os.environ.get("MOCK_COMPOSE_FAIL_STAGE") == "cleanup-stop":
                    raise SystemExit(52)
                if args[:1] == ["up"] and "nuq-postgres" not in args and os.environ.get("MOCK_COMPOSE_FAIL_STAGE") == "application-up":
                    raise SystemExit(53)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        compose.chmod(0o700)

        resource_guard = root / "resource-guard.sh"
        resource_guard.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'resource-%s\\n' \"$1\" >> \"$MOCK_LOG\"\n",
            encoding="utf-8",
        )
        resource_guard.chmod(0o700)

        verifier = root / "verify-local.sh"
        verifier.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'verify\\n' >> \"$MOCK_LOG\"\nif [[ \"${MOCK_DOCKER_FAIL_STAGE:-}\" == verify ]]; then exit 61; fi\n",
            encoding="utf-8",
        )
        verifier.chmod(0o700)

        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{fake_bin}:{environment['PATH']}",
                "MOCK_LOG": str(log),
                "MOCK_RUNNING_CONTAINERS": running,
                "FIRECRAWL_COMPOSE_SCRIPT": str(compose),
                "FIRECRAWL_RESOURCE_GUARD_SCRIPT": str(resource_guard),
                "FIRECRAWL_VERIFY_LOCAL_SCRIPT": str(verifier),
                "FIRECRAWL_HEALTH_TIMEOUT_SECONDS": "2",
                "FIRECRAWL_WAIT_TIMEOUT_SECONDS": "2",
            }
        )
        return environment, log

    @contextmanager
    def _backup_fixture(self, *, malformed: bool = False, missing_checksum: bool = False, extra_checksum: bool = False):
        backup_root = REPO_ROOT / "backups"
        root_existed = backup_root.exists()
        backup_root.mkdir(mode=0o700, exist_ok=True)
        before = set(backup_root.iterdir())
        temporary = tempfile.TemporaryDirectory(prefix="task5-", dir=backup_root)
        backup_dir = Path(temporary.name)
        archive_names = ("postgres.tar.gz", "redis.tar.gz", "rabbitmq.tar.gz")
        try:
            for archive in archive_names:
                archive_path = backup_dir / archive
                if malformed:
                    archive_path.write_bytes(b"not a tar archive\n")
                else:
                    with tarfile.open(archive_path, "w:gz") as stream:
                        info = tarfile.TarInfo("fixture.txt")
                        payload = b"fixture data\n"
                        info.size = len(payload)
                        stream.addfile(info, __import__("io").BytesIO(payload))
            if extra_checksum:
                extra = backup_dir / "unexpected.tar.gz"
                with tarfile.open(extra, "w:gz") as stream:
                    info = tarfile.TarInfo("unexpected.txt")
                    payload = b"unexpected\n"
                    info.size = len(payload)
                    stream.addfile(info, __import__("io").BytesIO(payload))
            (backup_dir / "manifest.txt").write_text(
                "Git commit: fixture\n"
                "Git describe: fixture\n"
                "Compose version: fixture\n"
                "Volume: firecrawl-postgres-data -> postgres.tar.gz\n"
                "Volume: firecrawl-redis-data -> redis.tar.gz\n"
                "Volume: firecrawl-rabbitmq-data -> rabbitmq.tar.gz\n"
                "UTC timestamp: 20260820T000000Z\n",
                encoding="utf-8",
            )
            checksummed = archive_names[:2] if missing_checksum else archive_names
            if extra_checksum:
                checksummed += ("unexpected.tar.gz",)
            checksum_lines = []
            for archive in checksummed:
                digest = hashlib.sha256((backup_dir / archive).read_bytes()).hexdigest()
                checksum_lines.append(f"{digest}  {archive}")
            (backup_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
            yield backup_dir, Path("backups") / backup_dir.name
        finally:
            temporary.cleanup()
            for child in set(backup_root.iterdir()) - before:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            if not root_existed and backup_root.exists() and not any(backup_root.iterdir()):
                backup_root.rmdir()

    def _run_script(self, script: Path, args: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), *args],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _log_lines(self, log: Path) -> list[str]:
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

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

    def test_backup_and_restore_scripts_have_cold_backup_safety_controls(self) -> None:
        backup = SCRIPTS_DIR / "backup.sh"
        restore = SCRIPTS_DIR / "restore.sh"
        backup_text = backup.read_text(encoding="utf-8")
        restore_text = restore.read_text(encoding="utf-8")

        for text, name in ((backup_text, "backup.sh"), (restore_text, "restore.sh")):
            self.assertIn('source "$ROOT/.env"', text, name)
            self.assertIn("BACKUP_HELPER_IMAGE", text, name)
            self.assertNotRegex(text, r"(?m)^\s*set\s+-x(?:\s|$)", name)

        self.assertIn("--leave-stopped", backup_text)
        self.assertIn("--output", backup_text)
        self.assertIn('git -C "$ROOT" rev-parse HEAD', backup_text)
        self.assertIn("sha256sum", backup_text)
        self.assertIn("pre-restore", restore_text)
        self.assertIn("--confirm", restore_text)
        self.assertIn("docker volume inspect", backup_text)
        self.assertIn("docker run --rm", backup_text)

    def test_restore_without_arguments_rejects_before_calling_docker(self) -> None:
        restore = SCRIPTS_DIR / "restore.sh"
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_bin = Path(temporary_directory) / "bin"
            fake_bin.mkdir()
            docker_called = Path(temporary_directory) / "docker-called"
            (fake_bin / "docker").write_text(
                "#!/usr/bin/env bash\nprintf 'docker called\\n' > %s\nexit 99\n" % docker_called,
                encoding="utf-8",
            )
            (fake_bin / "docker").chmod(0o700)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            result = subprocess.run(
                ["bash", str(restore)],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(docker_called.exists(), result.stdout + result.stderr)

    def test_restore_invalid_argument_forms_reject_before_calling_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_bin = Path(temporary_directory) / "bin"
            fake_bin.mkdir()
            docker_called = Path(temporary_directory) / "docker-called"
            (fake_bin / "docker").write_text(
                "#!/usr/bin/env bash\nprintf 'docker called\\n' > %s\nexit 99\n" % docker_called,
                encoding="utf-8",
            )
            (fake_bin / "docker").chmod(0o700)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            for arguments in (("--confirm",), ("backups/missing",), ("backups/missing", "--confirm", "extra"), ("backups/missing", "wrong")):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        ["bash", str(SCRIPTS_DIR / "restore.sh"), *arguments],
                        cwd=REPO_ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(docker_called.exists(), result.stdout + result.stderr)

    def test_mocked_backup_and_restore_flow_covers_artifacts_order_and_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            with self._backup_fixture() as (backup_dir, backup_argument):
                output_argument = backup_argument.with_name(backup_dir.name + "-output")
                output_dir = REPO_ROOT / output_argument
                backup = self._run_script(
                    SCRIPTS_DIR / "backup.sh",
                    ["--leave-stopped", "--output", str(output_argument)],
                    environment,
                )
                self.assertEqual(backup.returncode, 0, backup.stderr)
                self.assertEqual(output_dir.stat().st_mode & 0o777, 0o700)
                self.assertEqual(
                    sorted(path.name for path in output_dir.glob("*.tar.gz")),
                    ["postgres.tar.gz", "rabbitmq.tar.gz", "redis.tar.gz"],
                )
                self.assertTrue((output_dir / "manifest.txt").is_file())
                self.assertTrue((output_dir / "SHA256SUMS").is_file())
                lines = self._log_lines(log)
                self.assertLess(lines.index("compose stop gateway api playwright-service"), lines.index("compose stop redis rabbitmq nuq-postgres"))
                self.assertFalse(any(line.startswith("compose up") for line in lines))

                restore = self._run_script(
                    SCRIPTS_DIR / "restore.sh",
                    [str(output_argument), "--confirm"],
                    environment,
                )
                self.assertEqual(restore.returncode, 0, restore.stderr)
                lines = self._log_lines(log)
                ps_index = next(index for index, line in enumerate(lines) if line.startswith("docker ps "))
                safety_backup_index = next(index for index, line in enumerate(lines[ps_index + 1:], ps_index + 1) if line == "resource-pre")
                clear_index = lines.index("docker-clear")
                stateful_up_index = next(index for index, line in enumerate(lines[clear_index + 1:], clear_index + 1) if line == "compose up -d nuq-postgres redis rabbitmq")
                application_up_index = next(index for index, line in enumerate(lines[stateful_up_index + 1:], stateful_up_index + 1) if line == "compose up -d --wait --wait-timeout 2 playwright-service api gateway")
                self.assertLess(ps_index, safety_backup_index)
                self.assertLess(safety_backup_index, clear_index)
                self.assertLess(clear_index, stateful_up_index)
                self.assertLess(stateful_up_index, application_up_index)
                self.assertIn("compose ps -q nuq-postgres", lines)
                self.assertIn("compose ps -q redis", lines)
                self.assertIn("compose ps -q rabbitmq", lines)
                self.assertIn("verify", lines)
                self.assertIn("resource-post", lines)

    def test_restore_refuses_active_containers_before_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory), running="gateway-1")
            with self._backup_fixture() as (_, backup_argument):
                result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
            self.assertNotEqual(result.returncode, 0)
            lines = self._log_lines(log)
            self.assertTrue(any(line.startswith("docker ps ") for line in lines))
            self.assertFalse(any(line.startswith("compose ") for line in lines), lines)
            self.assertNotIn("resource-pre", lines)
            self.assertNotIn("docker-clear", lines)

    def test_restore_aborts_when_active_container_probe_fails_before_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            environment["MOCK_DOCKER_PS_FAIL"] = "47"
            with self._backup_fixture() as (_, backup_argument):
                result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = self._log_lines(log)
            self.assertTrue(any(line.startswith("docker ps ") for line in lines), lines)
            self.assertNotIn("resource-pre", lines)
            self.assertFalse(any(line.startswith("compose ") for line in lines), lines)
            self.assertNotIn("docker-clear", lines)
            self.assertNotIn("docker-extract", lines)
            self.assertFalse(any(line.startswith("docker volume inspect ") for line in lines), lines)

        for fixture_options in (
            {"missing_checksum": True},
            {"extra_checksum": True},
            {"malformed": True},
        ):
            with self.subTest(fixture_options=fixture_options), tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
                environment, log = self._mock_runtime(Path(temporary_directory))
                with self._backup_fixture(**fixture_options) as (_, backup_argument):
                    result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                lines = self._log_lines(log)
                self.assertFalse(any(line == "docker-clear" for line in lines), lines)
                self.assertFalse(any(line.startswith("compose stop") for line in lines), lines)

    def test_backup_rejects_unsafe_output_paths_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            backup_root = REPO_ROOT / "backups"
            backup_root.mkdir(mode=0o700, exist_ok=True)
            outside = Path(temporary_directory) / "outside"
            outside.mkdir()
            symlink = backup_root / "task5-symlink"
            symlink.symlink_to(outside, target_is_directory=True)
            existing = backup_root / "task5-existing"
            shutil.rmtree(existing, ignore_errors=True)
            existing.mkdir(mode=0o700)
            try:
                invalid_paths = (
                    "backups/../task5-traversal",
                    str(outside),
                    "backups/task5-symlink",
                    "backups/task5-delimiter:name",
                    "backups/task5-delimiter\nname",
                    "backups/task5-existing",
                )
                for invalid_path in invalid_paths:
                    with self.subTest(invalid_path=invalid_path):
                        result = self._run_script(SCRIPTS_DIR / "backup.sh", ["--output", invalid_path], environment)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(self._log_lines(log), [], invalid_path)
            finally:
                symlink.unlink(missing_ok=True)
                shutil.rmtree(existing)
                if backup_root.exists() and not any(backup_root.iterdir()):
                    backup_root.rmdir()

    def test_restore_rejects_unsafe_input_paths_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            traversal_target = REPO_ROOT / "task5-restore-traversal-fixture"
            with self._backup_fixture() as (backup_dir, backup_argument):
                outside = Path(temporary_directory) / "outside-backup"
                shutil.copytree(backup_dir, outside)
                symlink = REPO_ROOT / "backups" / "task5-restore-symlink"
                symlink.symlink_to(outside, target_is_directory=True)
                delimiter = REPO_ROOT / "backups" / "task5-restore:delimiter"
                shutil.copytree(backup_dir, delimiter)
                non_directory = REPO_ROOT / "backups" / "task5-restore-file"
                non_directory.write_text("not a directory\n", encoding="utf-8")
                shutil.copytree(backup_dir, traversal_target)
                invalid_paths = (
                    "backups/../task5-restore-traversal-fixture",
                    str(outside),
                    "backups/task5-restore-symlink",
                    "backups/task5-restore:delimiter",
                    "backups/task5-restore-delimiter\nname",
                    "backups/task5-restore-file",
                )
                try:
                    for invalid_path in invalid_paths:
                        with self.subTest(invalid_path=invalid_path):
                            log.write_text("", encoding="utf-8")
                            result = self._run_script(SCRIPTS_DIR / "restore.sh", [invalid_path, "--confirm"], environment)
                            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                            self.assertEqual(self._log_lines(log), [], invalid_path)
                finally:
                    symlink.unlink(missing_ok=True)
                    shutil.rmtree(delimiter, ignore_errors=True)
                    non_directory.unlink(missing_ok=True)
                    shutil.rmtree(traversal_target, ignore_errors=True)

    def test_backup_restart_failure_is_not_masked_by_application_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            environment["MOCK_COMPOSE_FAIL_STAGE"] = "stateful-up"
            with self._backup_fixture() as (backup_dir, backup_argument):
                output_argument = backup_argument.with_name(backup_dir.name + "-restart")
                result = self._run_script(SCRIPTS_DIR / "backup.sh", ["--output", str(output_argument)], environment)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = self._log_lines(log)
            self.assertIn("compose up -d --wait --wait-timeout 2 nuq-postgres redis rabbitmq", lines)
            self.assertNotIn("compose up -d --wait --wait-timeout 2 playwright-service api gateway", lines)

    def test_backup_normal_restart_waits_verifies_runs_post_guard_and_records_archive_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            environment["MOCK_REQUIRE_ARCHIVE_STREAM"] = "1"
            with self._backup_fixture() as (backup_dir, backup_argument):
                output_argument = backup_argument.with_name(backup_dir.name + "-verified")
                result = self._run_script(SCRIPTS_DIR / "backup.sh", ["--output", str(output_argument)], environment)
                output_dir = REPO_ROOT / output_argument
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = self._log_lines(log)
                stateful_up = "compose up -d --wait --wait-timeout 2 nuq-postgres redis rabbitmq"
                application_up = "compose up -d --wait --wait-timeout 2 playwright-service api gateway"
                self.assertIn(stateful_up, lines)
                self.assertIn(application_up, lines)
                self.assertLess(lines.index(stateful_up), lines.index(application_up))
                self.assertLess(lines.index(application_up), lines.index("verify"))
                self.assertLess(lines.index("verify"), lines.index("resource-post"))
                for archive in output_dir.glob("*.tar.gz"):
                    self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
                self.assertIn("backup created:", result.stdout)
                manifest = (output_dir / "manifest.txt").read_text(encoding="utf-8")
                checksums = (output_dir / "SHA256SUMS").read_text(encoding="utf-8")
                for line in checksums.splitlines():
                    digest, archive = line.split(maxsplit=1)
                    self.assertIn(f"Archive SHA-256: {digest}  {archive}", manifest)

    def test_backup_verification_failure_is_nonzero_and_retains_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            environment["MOCK_DOCKER_FAIL_STAGE"] = "verify"
            with self._backup_fixture() as (backup_dir, backup_argument):
                output_argument = backup_argument.with_name(backup_dir.name + "-verify-failure")
                result = self._run_script(SCRIPTS_DIR / "backup.sh", ["--output", str(output_argument)], environment)
                output_dir = REPO_ROOT / output_argument
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((output_dir / "postgres.tar.gz").is_file())
                self.assertIn("verify", self._log_lines(log))
                self.assertNotIn("backup created:", result.stdout)

    def test_restore_application_start_waits_before_local_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            with self._backup_fixture() as (_, backup_argument):
                result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = self._log_lines(log)
            application_up = "compose up -d --wait --wait-timeout 2 playwright-service api gateway"
            self.assertIn(application_up, lines)
            self.assertLess(lines.index(application_up), lines.index("verify"))

    def test_restore_rejects_unsafe_tar_members_before_volume_clear(self) -> None:
        for member_name, member_type in (("/absolute.txt", "regular"), ("../escape.txt", "regular"), ("link.txt", "symlink")):
            with self.subTest(member_name=member_name), tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
                environment, log = self._mock_runtime(Path(temporary_directory))
                with self._backup_fixture() as (backup_dir, backup_argument):
                    archive = backup_dir / "postgres.tar.gz"
                    with tarfile.open(archive, "w:gz") as stream:
                        info = tarfile.TarInfo(member_name)
                        payload = b"unsafe\n"
                        if member_type == "symlink":
                            info.type = tarfile.SYMTYPE
                            info.linkname = "/etc/passwd"
                        else:
                            info.size = len(payload)
                        stream.addfile(info, __import__("io").BytesIO(payload) if member_type == "regular" else None)
                    checksum_lines = []
                    for name in ("postgres.tar.gz", "redis.tar.gz", "rabbitmq.tar.gz"):
                        checksum_lines.append(f"{hashlib.sha256((backup_dir / name).read_bytes()).hexdigest()}  {name}")
                    (backup_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
                    result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("docker-clear", self._log_lines(log))

    def test_restore_rejects_symlinked_manifest_checksum_or_archive_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
            environment, log = self._mock_runtime(Path(temporary_directory))
            with self._backup_fixture() as (backup_dir, backup_argument):
                target = backup_dir / "postgres.tar.gz"
                replacement = backup_dir / "postgres-real.tar.gz"
                target.rename(replacement)
                target.symlink_to(replacement.name)
                result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._log_lines(log), [])

    def test_restore_failure_cleanup_stops_services_after_mutation(self) -> None:
        for failure_stage in ("clear", "extract", "start", "verify"):
            with self.subTest(failure_stage=failure_stage), tempfile.TemporaryDirectory() as temporary_directory, self._temporary_dotenv():
                environment, log = self._mock_runtime(Path(temporary_directory))
                if failure_stage in {"clear", "extract"}:
                    environment["MOCK_DOCKER_FAIL_STAGE"] = failure_stage
                elif failure_stage == "start":
                    environment["MOCK_COMPOSE_FAIL_STAGE"] = failure_stage
                else:
                    environment["MOCK_DOCKER_FAIL_STAGE"] = failure_stage
                with self._backup_fixture() as (_, backup_argument):
                    result = self._run_script(SCRIPTS_DIR / "restore.sh", [str(backup_argument), "--confirm"], environment)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                lines = self._log_lines(log)
                self.assertIn("docker-clear", lines)
                self.assertIn("compose stop gateway api playwright-service redis rabbitmq nuq-postgres", lines)
                self.assertIn("safety backup:", result.stderr)

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
                    current_environment = environment.copy()
                    current_environment["MEM_AVAILABLE_KIB"] = available
                    current_environment["SWAP_USED_KIB"] = "0"
                    current_environment["SWAP_TIMESTAMP"] = "1000"
                    current_environment["FIRECRAWL_SWAP_STATE_FILE"] = str(
                        Path(temporary_directory) / f"{mode}-{available}.state"
                    )
                    result = subprocess.run(
                        ["bash", str(guard), mode],
                        cwd=REPO_ROOT,
                        env=current_environment,
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

    def test_resource_guard_enforces_swap_growth_rate_and_atomic_baseline(self) -> None:
        guard = SCRIPTS_DIR / "resource-guard.sh"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_dir = root / "state"
            state_file = state_dir / "swap.state"
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": environment["PATH"],
                    "MEM_AVAILABLE_KIB": str(8 * 1024 * 1024),
                    "FIRECRAWL_SWAP_STATE_FILE": str(state_file),
                    "SWAP_GROWTH_THRESHOLD_KIB_PER_MINUTE": "131072",
                }
            )

            def run(used: int, timestamp: int) -> subprocess.CompletedProcess[str]:
                current = environment.copy()
                current.update({"SWAP_USED_KIB": str(used), "SWAP_TIMESTAMP": str(timestamp)})
                return subprocess.run(
                    ["bash", str(guard), "post"],
                    cwd=REPO_ROOT,
                    env=current,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            first = run(100, 1000)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(stat.S_IMODE(state_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(state_dir.stat().st_mode), 0o700)
            self.assertEqual(run(100 + 131071, 1060).returncode, 0)
            baseline_after_slow = state_file.read_text(encoding="utf-8")
            at_threshold = run(100 + 131071 + 131072, 1120)
            self.assertNotEqual(at_threshold.returncode, 0)
            self.assertEqual(state_file.read_text(encoding="utf-8"), baseline_after_slow)
            above_threshold = run(100 + 131071 + 131072 + 1, 1120)
            self.assertNotEqual(above_threshold.returncode, 0)
            self.assertEqual(state_file.read_text(encoding="utf-8"), baseline_after_slow)
            self.assertEqual(run(10, 1180).returncode, 0)
            self.assertIn("10", state_file.read_text(encoding="utf-8"))

            state_file.write_text("malformed state\n", encoding="utf-8")
            malformed = run(10, 1240)
            self.assertNotEqual(malformed.returncode, 0)

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

    def test_funnel_verifier_accepts_realistic_tailscale_status_contract(self) -> None:
        funnel = SCRIPTS_DIR / "verify-funnel.sh"
        hostname = "the-dream-land.taile6fad0.ts.net"
        baseline = {
            "TCP": {
                "443": {"HTTPS": True},
                "8443": {"HTTPS": True},
            },
            "Web": {
                f"{hostname}:443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}},
                },
                f"{hostname}:8443": {
                    "Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}},
                },
            },
            "AllowFunnel": {f"{hostname}:8443": True},
        }
        def post_fixture(baseline_document: dict = baseline) -> dict:
            post = deepcopy(baseline_document)
            post["TCP"]["10000"] = {"HTTPS": True}
            post["Web"][f"{hostname}:10000"] = {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}},
            }
            post["AllowFunnel"][f"{hostname}:10000"] = True
            return post

        post = post_fixture()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            baseline_path = root / "baseline.json"
            current_path = root / "current.json"
            secret_path = root / "api.env"
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

            def run_verifier(current: dict, baseline_document: dict = baseline) -> subprocess.CompletedProcess[str]:
                baseline_path.write_text(json.dumps(baseline_document), encoding="utf-8")
                current_path.write_text(json.dumps(current), encoding="utf-8")
                result = subprocess.run(
                    ["bash", str(funnel), str(baseline_path)],
                    cwd=REPO_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotIn(secret, result.stdout + result.stderr)
                return result

            def assert_rejected(current: dict, baseline_document: dict = baseline) -> None:
                self.assertNotEqual(run_verifier(current, baseline_document).returncode, 0)

            accepted = run_verifier(post)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("401", accepted.stdout)
            self.assertIn("200", accepted.stdout)

            baseline_with_unrelated = deepcopy(baseline)
            baseline_with_unrelated["TCP"]["1234"] = {"HTTPS": True}
            baseline_with_unrelated["Web"]["other-host.ts.net:1234"] = {
                "Handlers": {"/": {"Proxy": "http://other"}},
            }
            baseline_with_unrelated["AllowFunnel"]["other-host.ts.net:1234"] = True
            self.assertEqual(run_verifier(post_fixture(baseline_with_unrelated), baseline_with_unrelated).returncode, 0)

            absent_10000 = deepcopy(post)
            del absent_10000["TCP"]["10000"]
            assert_rejected(absent_10000)
            absent_10000 = deepcopy(post)
            del absent_10000["Web"][f"{hostname}:10000"]
            assert_rejected(absent_10000)
            absent_10000 = deepcopy(post)
            del absent_10000["AllowFunnel"][f"{hostname}:10000"]
            assert_rejected(absent_10000)

            false_https = deepcopy(post)
            false_https["TCP"]["10000"]["HTTPS"] = False
            assert_rejected(false_https)

            wrong_proxy = deepcopy(post)
            wrong_proxy["Web"][f"{hostname}:10000"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:3003"
            assert_rejected(wrong_proxy)
            missing_proxy = deepcopy(post)
            del missing_proxy["Web"][f"{hostname}:10000"]["Handlers"]["/"]["Proxy"]
            assert_rejected(missing_proxy)
            wrong_handler_path = deepcopy(post)
            wrong_handler_path["Web"][f"{hostname}:10000"]["Handlers"] = {
                "/health": {"Proxy": "http://127.0.0.1:3002"},
            }
            assert_rejected(wrong_handler_path)
            extra_handler_shape = deepcopy(post)
            extra_handler_shape["Web"][f"{hostname}:10000"]["Handlers"]["/health"] = {"Text": "unexpected"}
            assert_rejected(extra_handler_shape)

            false_funnel = deepcopy(post)
            false_funnel["AllowFunnel"][f"{hostname}:10000"] = False
            assert_rejected(false_funnel)
            missing_funnel = deepcopy(post)
            del missing_funnel["AllowFunnel"][f"{hostname}:10000"]
            assert_rejected(missing_funnel)

            for section, expected_value in (
                ("Web", {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}}}),
                ("AllowFunnel", True),
            ):
                bare_key = deepcopy(post)
                del bare_key[section][f"{hostname}:10000"]
                bare_key[section]["10000"] = expected_value
                assert_rejected(bare_key)

                wrong_host = deepcopy(post)
                del wrong_host[section][f"{hostname}:10000"]
                wrong_host[section]["other-host.ts.net:10000"] = expected_value
                assert_rejected(wrong_host)

            duplicate_10000_web = deepcopy(post)
            duplicate_10000_web["Web"]["other-host.ts.net:10000"] = {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}},
            }
            assert_rejected(duplicate_10000_web)
            duplicate_10000_funnel = deepcopy(post)
            duplicate_10000_funnel["AllowFunnel"]["other-host.ts.net:10000"] = True
            assert_rejected(duplicate_10000_funnel)

            for section, key, value in (
                ("TCP", "10001", {"HTTPS": True}),
                ("Web", f"{hostname}:10001", {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}}}),
                ("AllowFunnel", f"{hostname}:10001", True),
            ):
                additional_route = deepcopy(post)
                additional_route[section][key] = value
                assert_rejected(additional_route)

            for section, key, value in (
                ("TCP", "10000", {"HTTPS": True}),
                ("Web", "10000", {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}}}),
                ("Web", f"{hostname}:10000", {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3002"}}}),
                ("AllowFunnel", "10000", True),
                ("AllowFunnel", f"{hostname}:10000", True),
            ):
                baseline_with_10000 = deepcopy(baseline)
                baseline_with_10000[section][key] = value
                assert_rejected(post, baseline_with_10000)

            changed_handler = deepcopy(post)
            changed_handler["Web"][f"{hostname}:443"]["Handlers"]["/"]["Proxy"] = "http://changed"
            self.assertNotEqual(run_verifier(changed_handler).returncode, 0)

            changed_protocol = deepcopy(post)
            changed_protocol["TCP"]["8443"]["HTTPS"] = False
            self.assertNotEqual(run_verifier(changed_protocol).returncode, 0)

            required_keys = (
                ("TCP", "443"),
                ("TCP", "8443"),
                ("Web", f"{hostname}:443"),
                ("Web", f"{hostname}:8443"),
                ("AllowFunnel", f"{hostname}:8443"),
            )
            for section, key in required_keys:
                missing = deepcopy(post)
                del missing[section][key]
                self.assertNotEqual(run_verifier(missing).returncode, 0, f"missing {section} {key}")

            for malformed in (
                {**deepcopy(post), "TCP": {"443": {}, "8443": {"HTTPS": True}}},
                {**deepcopy(post), "TCP": {"443": [], "8443": {"HTTPS": True}}},
                {**deepcopy(post), "Web": []},
                {**deepcopy(post), "Web": {f"{hostname}:443": {}, f"{hostname}:8443": {"Handlers": {}}}},
                {**deepcopy(post), "AllowFunnel": []},
                {**deepcopy(post), "AllowFunnel": {f"{hostname}:8443": False}},
            ):
                self.assertNotEqual(run_verifier(malformed).returncode, 0)

            duplicate_web = deepcopy(post)
            duplicate_web["Web"][f"other-host.ts.net:443"] = {"Handlers": {"/": {"Proxy": "http://other"}}}
            self.assertNotEqual(run_verifier(duplicate_web).returncode, 0)

            mismatched_web_host = deepcopy(post)
            mismatched_web_host["Web"][f"{hostname}:8443"] = mismatched_web_host["Web"].pop(
                f"{hostname}:443"
            )
            mismatched_web_host["Web"]["other-host.ts.net:443"] = {"Handlers": {"/": {"Proxy": "http://other"}}}
            self.assertNotEqual(run_verifier(mismatched_web_host).returncode, 0)

            changed_between_documents = deepcopy(post)
            changed_between_documents["Web"] = {
                f"other-host.ts.net:443": changed_between_documents["Web"].pop(f"{hostname}:443"),
                f"other-host.ts.net:8443": changed_between_documents["Web"].pop(f"{hostname}:8443"),
            }
            changed_between_documents["AllowFunnel"] = {"other-host.ts.net:8443": True}
            self.assertNotEqual(run_verifier(changed_between_documents).returncode, 0)

            extra_funnel_443 = deepcopy(post)
            extra_funnel_443["AllowFunnel"][f"{hostname}:443"] = False
            self.assertNotEqual(run_verifier(extra_funnel_443).returncode, 0)

            duplicate_funnel_8443 = deepcopy(post)
            duplicate_funnel_8443["AllowFunnel"]["other-host.ts.net:8443"] = True
            self.assertNotEqual(run_verifier(duplicate_funnel_8443).returncode, 0)

            wrong_funnel_hostname = deepcopy(post)
            wrong_funnel_hostname["AllowFunnel"] = {"other-host.ts.net:8443": True}
            self.assertNotEqual(run_verifier(wrong_funnel_hostname).returncode, 0)

            empty_result = run_verifier({}, {})
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
                    import os
                    from contextlib import asynccontextmanager

                    @asynccontextmanager
                    async def stdio_client(server, *, errlog):
                        os.fstat(errlog.fileno())
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
            self.assertIn('firecrawl-mcp@3.24.0', text)

            timeout_environment = environment.copy()
            timeout_environment["FIRECRAWL_MCP_TIMEOUT_SECONDS"] = "0"
            timeout_result = subprocess.run(
                [str(HERMES_PYTHON), str(verifier)],
                cwd=REPO_ROOT,
                env=timeout_environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(timeout_result.returncode, 0)
            self.assertEqual(timeout_result.stdout, "")
            self.assertEqual(timeout_result.stderr, "FAIL: timeout\n")

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
            self.assertEqual(wrong_interpreter.stderr, "FAIL: runtime\n")
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
            self.assertEqual(missing_dependency.stderr, "FAIL: unexpected\n")
            self.assertNotIn(secret, missing_dependency.stdout + missing_dependency.stderr)

    def test_mcp_verifier_selects_hermes_interpreter_in_executable_contract(self) -> None:
        text = (SCRIPTS_DIR / "verify-mcp.py").read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "#!/usr/local/lib/hermes-agent/venv/bin/python")
        self.assertIn("/usr/local/lib/hermes-agent/venv/bin/python", text)
        self.assertNotRegex(text, r"(?m)^from mcp(?:\.| )", msg="mcp must be imported inside the guarded path")

    def test_runbook_start_and_rollback_are_fail_closed_and_bounded(self) -> None:
        text = (REPO_ROOT / "docs/operations/the-dream-land.md").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail\ncd /home/kang/docker/firecrawl\nscripts/compose.sh up --help", text)
        self.assertNotIn("alpine:3.20", text)
        self.assertIn("BACKUP_HELPER_IMAGE", text)
        self.assertIn("@sha256:", text)
        self.assertIn("for (( attempt=1; attempt<=60; attempt++ )); do", text)
        self.assertIn("FAIL: Open WebUI did not become healthy", text)
        self.assertIn("old_key=", text)
        self.assertIn("new_key=", text)
        self.assertIn("web.loader.firecrawl_api_key", text)
        self.assertIn("firecrawl_api_key=set", text)
        self.assertNotIn("until curl --fail --silent http://127.0.0.1:3000/health", text)


if __name__ == "__main__":
    unittest.main()
