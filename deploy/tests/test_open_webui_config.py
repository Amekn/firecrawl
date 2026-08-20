from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "scripts" / "configure-open-webui.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("configure_open_webui", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenWebUIConfigTests(unittest.TestCase):
    def test_desired_config_returns_exact_required_key_set(self) -> None:
        helper = load_helper()

        updates = helper.desired_config("http://firecrawl-gateway:8080", "secret")

        self.assertEqual(
            set(updates),
            {
                "web.search.engine",
                "web.loader.engine",
                "web.loader.firecrawl_api_url",
                "web.loader.firecrawl_api_key",
                "web.loader.firecrawl_timeout",
            },
        )
        self.assertEqual(updates["web.search.engine"], "firecrawl")
        self.assertEqual(updates["web.loader.engine"], "firecrawl")
        self.assertEqual(
            updates["web.loader.firecrawl_api_url"],
            "http://firecrawl-gateway:8080",
        )
        self.assertEqual(updates["web.loader.firecrawl_api_key"], "secret")
        self.assertEqual(updates["web.loader.firecrawl_timeout"], "120")

    def test_apply_updates_rejects_unknown_keys(self) -> None:
        helper = load_helper()
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at BIGINT)"
        )

        with self.assertRaisesRegex(ValueError, "unsupported config keys"):
            helper.apply_updates(connection, {"unknown.setting": "bad"}, 1)

        self.assertEqual(connection.execute("SELECT COUNT(*) FROM config").fetchone()[0], 0)

    def test_apply_updates_uses_integer_unix_timestamp_and_preserves_unrelated_row(self) -> None:
        helper = load_helper()
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at BIGINT)"
        )
        connection.executemany(
            "INSERT INTO config(key, value, updated_at) VALUES (?, ?, ?)",
            [
                ("web.search.engine", json.dumps("searxng"), 1785943851),
                ("web.loader.engine", json.dumps(""), 1785943851),
                ("web.loader.firecrawl_api_url", json.dumps("https://api.firecrawl.dev"), 1785943851),
                ("web.loader.firecrawl_api_key", json.dumps(""), 1785943851),
                ("web.loader.firecrawl_timeout", json.dumps(""), 1785943851),
                ("unrelated.setting", json.dumps({"keep": True}), 1785943851),
            ],
        )
        updates = helper.desired_config("http://firecrawl-gateway:8080", "secret")
        unrelated_before = connection.execute(
            "SELECT value, updated_at FROM config WHERE key = ?", ("unrelated.setting",)
        ).fetchone()
        now = helper._utc_now()

        self.assertIsInstance(now, int)
        self.assertGreaterEqual(now, 0)
        helper.apply_updates(connection, updates, now)
        rows = dict(connection.execute("SELECT key, value FROM config"))

        self.assertEqual(json.loads(rows["web.search.engine"]), "firecrawl")
        self.assertEqual(json.loads(rows["web.loader.engine"]), "firecrawl")
        self.assertEqual(
            json.loads(rows["web.loader.firecrawl_api_url"]),
            "http://firecrawl-gateway:8080",
        )
        self.assertEqual(json.loads(rows["web.loader.firecrawl_api_key"]), "secret")
        self.assertEqual(json.loads(rows["web.loader.firecrawl_timeout"]), "120")
        self.assertEqual(json.loads(rows["unrelated.setting"]), {"keep": True})
        self.assertEqual(
            connection.execute(
                "SELECT updated_at, typeof(updated_at) FROM config WHERE key IN (?, ?, ?, ?, ?) "
                "ORDER BY key",
                (
                    "web.search.engine",
                    "web.loader.engine",
                    "web.loader.firecrawl_api_url",
                    "web.loader.firecrawl_api_key",
                    "web.loader.firecrawl_timeout",
                ),
            ).fetchall(),
            [(now, "integer")] * 5,
        )
        self.assertEqual(
            connection.execute(
                "SELECT value, updated_at FROM config WHERE key = ?", ("unrelated.setting",)
            ).fetchone(),
            unrelated_before,
        )

    def test_cli_requires_firecrawl_api_key_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env = os.environ.copy()
            env["OPEN_WEBUI_DB_PATH"] = str(Path(temporary_directory) / "webui.db")
            env.pop("FIRECRAWL_API_KEY", None)

            result = subprocess.run(
                [sys.executable, str(HELPER_PATH)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FIRECRAWL_API_KEY is not set", result.stderr)

    def test_cli_prints_only_safe_key_names_and_never_secret(self) -> None:
        helper = load_helper()
        sentinel = "task-7-cli-sentinel-secret"

        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "webui.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at BIGINT)"
            )
            connection.commit()
            connection.close()

            env = os.environ.copy()
            env["FIRECRAWL_API_KEY"] = sentinel
            env["FIRECRAWL_API_BASE_URL"] = "http://firecrawl-gateway:8080"
            env["OPEN_WEBUI_DB_PATH"] = str(db_path)
            command = [sys.executable, str(HELPER_PATH)]
            result = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            with sqlite3.connect(db_path) as read_connection:
                persisted = dict(
                    read_connection.execute("SELECT key, value FROM config").fetchall()
                )

        self.assertNotIn(sentinel, command)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "".join(f"updated {key}\n" for key in helper.CONFIG_KEYS))
        self.assertEqual(result.stderr, "")
        self.assertNotIn(sentinel, result.stdout)
        self.assertNotIn(sentinel, result.stderr)
        self.assertEqual(set(persisted), set(helper.CONFIG_KEYS))


if __name__ == "__main__":
    unittest.main()
