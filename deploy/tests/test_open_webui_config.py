from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
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
    def test_desired_config_selects_firecrawl_with_safe_timeout(self) -> None:
        helper = load_helper()

        updates = helper.desired_config("http://firecrawl-gateway:8080", "secret")

        self.assertEqual(updates["web.search.engine"], "firecrawl")
        self.assertEqual(updates["web.loader.engine"], "firecrawl")
        self.assertEqual(
            updates["web.loader.firecrawl_api_url"],
            "http://firecrawl-gateway:8080",
        )
        self.assertEqual(updates["web.loader.firecrawl_api_key"], "secret")
        self.assertEqual(updates["web.loader.firecrawl_timeout"], "120")

    def test_apply_updates_json_encodes_values_and_preserves_unrelated_rows(self) -> None:
        helper = load_helper()
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO config(key, value, updated_at) VALUES (?, ?, ?)",
            [
                ("web.search.engine", json.dumps("searxng"), "before"),
                ("unrelated.setting", json.dumps({"keep": True}), "before"),
            ],
        )
        updates = helper.desired_config("http://firecrawl-gateway:8080", "secret")

        helper.apply_updates(connection, updates, "2026-08-21T00:00:00Z")
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
                "SELECT updated_at FROM config WHERE key = ?", ("web.search.engine",)
            ).fetchone()[0],
            "2026-08-21T00:00:00Z",
        )


if __name__ == "__main__":
    unittest.main()
