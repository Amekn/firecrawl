from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_IMAGES = {
    "redis": "redis:alpine@sha256:978f0e01593e65eed801f2402944efcd936d43b5027e4908a7897baf88ed6241",
    "rabbitmq": "rabbitmq:3-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69",
    "gateway": "nginxinc/nginx-unprivileged:1.29.1-alpine@sha256:27985295bdb22a1ef8f712863210bd5877c0f3006494a593e86b3fe0fa55467e",
}
EXPECTED_BACKUP_HELPER_IMAGE = (
    "alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1"
)


class ComposeInvariantTests(unittest.TestCase):
    @staticmethod
    def _load_model(environment_overrides: dict[str, str] | None = None) -> dict:
        environment = os.environ.copy()
        environment["FIRECRAWL_API_ENV_FILE"] = "./deploy/examples/api.env.example"
        if environment_overrides:
            environment.update(environment_overrides)
        cmd = [
            "docker",
            "compose",
            "--env-file",
            ".env.example",
            "--env-file",
            "deploy/examples/stack.env.example",
            "-f",
            "docker-compose.yaml",
            "-f",
            "compose.the-dream-land.yaml",
            "config",
            "--format",
            "json",
        ]
        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
        return json.loads(result.stdout)

    @classmethod
    def setUpClass(cls) -> None:
        cls.model = cls._load_model()
        # Compose omits inactive profile services from the rendered model.
        # Enable this profile only while inspecting its declared invariant.
        cls.profiled_model = cls._load_model({"COMPOSE_PROFILES": "foundationdb"})

    def test_api_has_no_host_port_and_gateway_is_loopback_only(self) -> None:
        services = self.model["services"]
        self.assertEqual(services["api"].get("ports", []), [])
        self.assertEqual(
            services["gateway"]["ports"],
            [
                {
                    "mode": "ingress",
                    "target": 8080,
                    "published": "3002",
                    "protocol": "tcp",
                    "host_ip": "127.0.0.1",
                }
            ],
        )

    def test_no_non_gateway_service_has_host_published_ports(self) -> None:
        for service_name, service in self.model["services"].items():
            if service_name != "gateway":
                self.assertEqual(service.get("ports", []), [], service_name)

    def test_api_networks_and_required_external_network(self) -> None:
        services = self.model["services"]
        self.assertEqual(set(services["api"]["networks"]), {"backend", "open-webui"})
        self.assertTrue(self.model["networks"]["open-webui"]["external"])

    def test_foundationdb_services_are_profiled(self) -> None:
        services = self.profiled_model["services"]
        self.assertEqual(services["foundationdb"]["profiles"], ["foundationdb"])
        self.assertEqual(services["foundationdb-init"]["profiles"], ["foundationdb"])
        self.assertNotIn("foundationdb", self.model["services"])
        self.assertNotIn("foundationdb-init", self.model["services"])

    def test_api_runtime_environment_and_persistent_volumes(self) -> None:
        api_environment = self.model["services"]["api"]["environment"]
        self.assertEqual(api_environment["SEARXNG_ENDPOINT"], "http://searxng:8080")
        self.assertEqual(api_environment["NUM_WORKERS_PER_QUEUE"], "1")
        self.assertEqual(api_environment["NUQ_WORKER_COUNT"], "1")
        self.assertIn("postgres-data", self.model["volumes"])
        self.assertIn("redis-data", self.model["volumes"])
        self.assertIn("rabbitmq-data", self.model["volumes"])
        self.assertEqual(
            self.model["volumes"]["postgres-data"]["name"], "firecrawl-postgres-data"
        )
        self.assertEqual(
            self.model["volumes"]["redis-data"]["name"], "firecrawl-redis-data"
        )
        self.assertEqual(
            self.model["volumes"]["rabbitmq-data"]["name"], "firecrawl-rabbitmq-data"
        )

    def test_direct_images_and_backup_helper_are_digest_pinned(self) -> None:
        services = self.model["services"]
        for service_name, expected_image in EXPECTED_IMAGES.items():
            self.assertEqual(services[service_name]["image"], expected_image)

        env_example = (REPO_ROOT / ".env.example").read_text()
        self.assertIn(f"BACKUP_HELPER_IMAGE={EXPECTED_BACKUP_HELPER_IMAGE}\n", env_example)


if __name__ == "__main__":
    unittest.main()
