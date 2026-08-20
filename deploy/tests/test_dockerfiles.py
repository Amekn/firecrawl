from __future__ import annotations

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_BASES = {
    "apps/api/Dockerfile": {
        "node:22-slim": "node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436",
        "golang:1.24": "golang:1.24@sha256:d2d2bc1c84f7e60d7d2438a3836ae7d0c847f4888464e7ec9ba3a1339a1ee804",
    },
    "apps/playwright-service-ts/Dockerfile": {
        "node:22-slim": "node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436",
    },
    "apps/nuq-postgres/Dockerfile": {
        "postgres:17": "postgres:17@sha256:e38411452a464af89e5adadb8d223bf53b898d47d6ef918b2d58c08707350449",
    },
}


class DockerfilePinTests(unittest.TestCase):
    def test_every_deployment_source_from_is_the_reviewed_immutable_digest(self) -> None:
        for relative_path, expected in EXPECTED_BASES.items():
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            from_lines = re.findall(r"(?m)^FROM\s+([^\s]+)", text)
            self.assertTrue(from_lines, relative_path)
            for image in from_lines:
                if image in {"base"}:
                    continue
                self.assertIn("@sha256:", image, f"floating FROM in {relative_path}: {image}")
            for tag, digest_pin in expected.items():
                self.assertIn(f"FROM {digest_pin}", text, relative_path)

    def test_api_keeps_external_download_provenance_limitation_explicit(self) -> None:
        text = (REPO_ROOT / "docs/operations/the-dream-land.md").read_text(encoding="utf-8")
        self.assertIn("Versioned external build downloads remain a separate provenance limitation", text)


if __name__ == "__main__":
    unittest.main()