from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_IMAGES = {
    "redis": "redis:alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0",
    "rabbitmq": "rabbitmq:3-management@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69",
    "gateway": "nginxinc/nginx-unprivileged:1.30.5-alpine@sha256:4714e0b1b2577eaa1a6131d07c958b67f0eb68e6d0521e90c6e5287db8cf0bc5",
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

    def test_gateway_tmpfs_entries_are_uid_gid_and_mode_pinned(self) -> None:
        self.assertEqual(
            self.model["services"]["gateway"]["tmpfs"],
            [
                "/tmp:uid=101,gid=101,mode=1777",
                "/var/cache/nginx:uid=101,gid=101,mode=0755",
                "/etc/nginx/conf.d:uid=101,gid=101,mode=0755",
            ],
        )

    def test_api_networks_and_required_external_network(self) -> None:
        services = self.model["services"]
        self.assertEqual(set(services["api"]["networks"]), {"backend", "search"})
        self.assertNotIn("open-webui", services["api"]["networks"])
        self.assertEqual(
            services["gateway"]["networks"],
            {"backend": {}, "open-webui": {"aliases": ["firecrawl-gateway"]}},
        )
        self.assertTrue(self.model["networks"]["open-webui"]["external"])

    def test_search_network_is_internal_and_named_for_api_provider_peer(self) -> None:
        search = self.model["networks"]["search"]
        self.assertEqual(search["name"], "firecrawl-search-network")
        self.assertTrue(search["internal"])

    def test_all_service_resource_restart_health_and_logging_policies_are_pinned(self) -> None:
        services = self.model["services"]
        expected = {
            "playwright-service": (1.0, 2 * 1024**3, 2 * 1024**3),
            "api": (1.5, 3 * 1024**3, 3 * 1024**3),
            "redis": (0.25, 256 * 1024**2, 256 * 1024**2),
            "rabbitmq": (0.5, 512 * 1024**2, 512 * 1024**2),
            "nuq-postgres": (0.5, 768 * 1024**2, 768 * 1024**2),
            "gateway": (0.1, 128 * 1024**2, 128 * 1024**2),
        }
        for service_name, (cpus, memory, memswap) in expected.items():
            with self.subTest(service=service_name):
                service = services[service_name]
                self.assertEqual(service["cpus"], cpus)
                self.assertEqual(int(service["mem_limit"]), memory)
                self.assertEqual(int(service["memswap_limit"]), memswap)
                self.assertEqual(service["restart"], "unless-stopped")
                self.assertEqual(service["logging"]["driver"], "json-file")
                self.assertIn("max-size", service["logging"]["options"])
                self.assertIn("max-file", service["logging"]["options"])
        for service_name in ("api", "redis", "nuq-postgres", "gateway"):
            self.assertIn("healthcheck", services[service_name], service_name)

    def test_profiled_foundationdb_services_have_no_host_ports(self) -> None:
        for service_name in ("foundationdb", "foundationdb-init"):
            self.assertEqual(self.profiled_model["services"][service_name].get("ports", []), [])

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
