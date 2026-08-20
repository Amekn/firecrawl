from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate-secrets.sh"


class SecretGenerationTests(unittest.TestCase):
    def run_generator(self, root: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["FIRECRAWL_ROOT"] = str(root)
        return subprocess.run(
            ["bash", str(GENERATOR)],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_generates_private_hex_secrets_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            first_result = self.run_generator(root)

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            api = root / "secrets/api.env"
            stack = root / "secrets/stack.env"
            self.assertIsNotNone(
                re.fullmatch(r"FIRECRAWL_API_KEY=[0-9a-f]{64}\n", api.read_text())
            )
            self.assertIsNotNone(
                re.fullmatch(r"POSTGRES_PASSWORD=[0-9a-f]{64}\n", stack.read_text())
            )
            self.assertEqual(stat.S_IMODE(api.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(stack.stat().st_mode), 0o600)
            self.assertEqual(first_result.stdout, "")

            first_hashes = (
                hashlib.sha256(api.read_bytes()).digest(),
                hashlib.sha256(stack.read_bytes()).digest(),
            )

            second_result = self.run_generator(root)

            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(second_result.stdout, "")
            second_hashes = (
                hashlib.sha256(api.read_bytes()).digest(),
                hashlib.sha256(stack.read_bytes()).digest(),
            )
            self.assertEqual(second_hashes, first_hashes)

    def test_existing_secret_permissions_are_restricted_without_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            secrets_directory = root / "secrets"
            secrets_directory.mkdir()
            api = secrets_directory / "api.env"
            stack = secrets_directory / "stack.env"
            api_contents = "FIRECRAWL_API_KEY=" + "a" * 64 + "\n"
            stack_contents = "POSTGRES_PASSWORD=" + "b" * 64 + "\n"
            api.write_text(api_contents)
            stack.write_text(stack_contents)
            api.chmod(0o644)
            stack.chmod(0o644)

            result = self.run_generator(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(api.read_text(), api_contents)
            self.assertEqual(stack.read_text(), stack_contents)
            self.assertEqual(stat.S_IMODE(api.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(stack.stat().st_mode), 0o600)

    def test_existing_dotenv_permissions_are_restricted_without_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dotenv = root / ".env"
            dotenv_contents = "BACKUP_HELPER_IMAGE=fixture/helper@sha256:" + "a" * 64 + "\\n"
            dotenv.write_text(dotenv_contents)
            dotenv.chmod(0o644)

            result = self.run_generator(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dotenv.read_text(), dotenv_contents)
            self.assertEqual(stat.S_IMODE(dotenv.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
