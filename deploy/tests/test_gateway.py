from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "deploy" / "nginx" / "default.conf.template"


class GatewayTemplateTests(unittest.TestCase):
    def _read_template(self) -> str:
        self.assertTrue(TEMPLATE.is_file(), f"missing gateway template: {TEMPLATE}")
        return TEMPLATE.read_text(encoding="utf-8")

    def test_gateway_template_contains_required_auth_proxy_controls(self) -> None:
        text = self._read_template()

        self.assertRegex(
            text,
            r'(?m)^\s*"~\^Bearer \$\{FIRECRAWL_API_KEY\}\$"\s+1;\s*$',
            "auth map must use an anchored, case-sensitive Bearer regex",
        )
        self.assertNotIn('"Bearer ${FIRECRAWL_API_KEY}" 1;', text)
        self.assertNotIn('"~*^Bearer ${FIRECRAWL_API_KEY}$" 1;', text)
        self.assertIn("return 401", text)
        self.assertIn('proxy_set_header Authorization "";', text)
        self.assertIn("proxy_pass http://api:3002;", text)
        self.assertIn("limit_req_zone", text)
        self.assertIn("rate=60r/m", text)
        self.assertIn("location = /healthz", text)
        self.assertIn("proxy_read_timeout 360s", text)

    def test_gateway_template_has_no_literal_secret_or_localhost_upstream(self) -> None:
        text = self._read_template()

        self.assertNotRegex(text, r"proxy_pass\s+https?://localhost(?::\d+)?\s*;")
        self.assertNotRegex(text, r"(?<![A-Za-z0-9])[A-Fa-f0-9]{64}(?![A-Za-z0-9])")


if __name__ == "__main__":
    unittest.main()
