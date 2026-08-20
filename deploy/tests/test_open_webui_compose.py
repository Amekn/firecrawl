from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


OPEN_WEBUI_ROOT = Path("/home/kang/docker/open-webui")


class OpenWebUIComposeNetworkTests(unittest.TestCase):
    def test_only_searxng_joins_the_internal_firecrawl_search_network(self) -> None:
        compose = OPEN_WEBUI_ROOT / "compose.yaml"
        self.assertTrue(compose.is_file(), compose)
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
            cwd=OPEN_WEBUI_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        model = json.loads(result.stdout)
        networks = model["networks"]
        services = model["services"]
        if "firecrawl-search" not in networks:
            self.skipTest("external Firecrawl search network cutover not yet applied")
        self.assertEqual(networks["firecrawl-search"]["name"], "firecrawl-search-network")
        self.assertTrue(networks["firecrawl-search"]["external"])
        self.assertIn("firecrawl-search", services["searxng"]["networks"])
        self.assertIn("open-webui", services["searxng"]["networks"])
        self.assertNotIn("firecrawl-search", services["open-webui"]["networks"])


if __name__ == "__main__":
    unittest.main()