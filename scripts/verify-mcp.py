#!/usr/bin/env python3
"""Verify the official Firecrawl MCP adapter through the Funnel URL."""

from __future__ import annotations

import asyncio
from pathlib import Path
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
API_ENV_FILE = Path(
    os.environ.get("FIRECRAWL_API_ENV_FILE", str(REPO_ROOT / "secrets" / "api.env"))
)
URL = os.environ.get(
    "FIRECRAWL_MCP_URL", "https://the-dream-land.taile6fad0.ts.net:10000"
)


def read_api_key(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError("unable to read API environment file") from error
    for line in lines:
        if line.startswith("FIRECRAWL_API_KEY="):
            key = line.split("=", 1)[1]
            if key:
                return key
            break
    raise RuntimeError("missing FIRECRAWL_API_KEY")


async def verify(key: str) -> int:
    server = StdioServerParameters(
        command="npx",
        args=["-y", "firecrawl-mcp"],
        env={**os.environ, "FIRECRAWL_API_URL": URL, "FIRECRAWL_API_KEY": key},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if "firecrawl_search" not in tool_names:
                raise RuntimeError("firecrawl_search tool is unavailable")
            result = await session.call_tool(
                "firecrawl_search", {"query": "Firecrawl self hosting", "limit": 2}
            )
            if getattr(result, "isError", False):
                raise RuntimeError("firecrawl_search returned an error")
            print(f"tools: {len(tools.tools)}")
            print("PASS")
    return 0


def main() -> int:
    try:
        key = read_api_key(API_ENV_FILE)
        return asyncio.run(verify(key))
    except Exception:
        print("FAIL", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
