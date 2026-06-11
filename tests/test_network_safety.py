from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from stella.lit.network_safety import validate_public_http_url  # noqa: E402


class NetworkSafetyTest(unittest.TestCase):
    def test_allows_public_http_urls(self) -> None:
        allowed, reason = validate_public_http_url("https://example.test/catalog.csv")

        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_blocks_local_private_link_local_and_non_http_urls(self) -> None:
        blocked = [
            "http://localhost/catalog.csv",
            "http://127.0.0.1/catalog.csv",
            "http://10.0.0.5/catalog.csv",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/catalog.csv",
            "ftp://example.test/catalog.csv",
            "https:///missing-host.csv",
        ]

        for url in blocked:
            with self.subTest(url=url):
                allowed, reason = validate_public_http_url(url)
                self.assertFalse(allowed)
                self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
