#!/usr/bin/env python3
"""Persist Open WebUI's Firecrawl retrieval configuration safely."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Mapping


DEFAULT_DB_PATH = "/app/backend/data/webui.db"
DEFAULT_BASE_URL = "http://firecrawl-gateway:8080"
CONFIG_KEYS = (
    "web.search.engine",
    "web.loader.engine",
    "web.loader.firecrawl_api_url",
    "web.loader.firecrawl_api_key",
    "web.loader.firecrawl_timeout",
)
_ALLOWED_KEYS = frozenset(CONFIG_KEYS)


def desired_config(base_url: str, api_key: str) -> dict[str, object]:
    """Return only the five persisted settings required for Firecrawl."""
    return {
        "web.search.engine": "firecrawl",
        "web.loader.engine": "firecrawl",
        "web.loader.firecrawl_api_url": base_url,
        "web.loader.firecrawl_api_key": api_key,
        "web.loader.firecrawl_timeout": "120",
    }


def apply_updates(
    connection: sqlite3.Connection,
    updates: Mapping[str, object],
    now: str,
) -> None:
    """Upsert the allowed settings as JSON values without touching other rows."""
    unknown_keys = set(updates) - _ALLOWED_KEYS
    if unknown_keys:
        raise ValueError(f"unsupported config keys: {sorted(unknown_keys)!r}")

    statement = """
        INSERT INTO config(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """
    connection.executemany(
        statement,
        (
            (key, json.dumps(value), now)
            for key, value in updates.items()
        ),
    )
    connection.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise SystemExit("FIRECRAWL_API_KEY is not set")

    base_url = os.environ.get("FIRECRAWL_API_BASE_URL", DEFAULT_BASE_URL)
    db_path = os.environ.get("OPEN_WEBUI_DB_PATH", DEFAULT_DB_PATH)
    connection = sqlite3.connect(db_path)
    try:
        apply_updates(connection, desired_config(base_url, api_key), _utc_now())
    finally:
        connection.close()

    for key in CONFIG_KEYS:
        print(f"updated {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
