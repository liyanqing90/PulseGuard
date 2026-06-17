from __future__ import annotations

import unittest

from backend.app import network_checks


class NetworkCheckUtilityTests(unittest.TestCase):
    def test_normalize_host_port_accepts_url_host_port_and_default(self) -> None:
        self.assertEqual(network_checks.normalize_host_port("https://example.com/path", 443), ("example.com", 443))
        self.assertEqual(network_checks.normalize_host_port("example.com:8443", 443), ("example.com", 8443))
        self.assertEqual(network_checks.normalize_host_port("example.com", 80), ("example.com", 80))

    def test_normalize_host_port_rejects_invalid_target(self) -> None:
        with self.assertRaises(ValueError):
            network_checks.normalize_host_port("", 443)
        with self.assertRaises(ValueError):
            network_checks.normalize_host_port("example.com:99999", 443)


if __name__ == "__main__":
    unittest.main()
