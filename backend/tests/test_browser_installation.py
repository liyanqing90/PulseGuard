from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from backend.app import browser_installation


class BrowserInstallationTests(unittest.TestCase):
    def test_installed_browser_types_uses_direct_probe_outside_event_loop(self) -> None:
        with patch.object(browser_installation, "_installed_browser_types_direct", return_value=["chromium"]) as direct, patch.object(
            browser_installation, "_installed_browser_types_subprocess", return_value=[]
        ) as subprocess_probe:
            self.assertEqual(browser_installation.installed_browser_types(), ["chromium"])

        direct.assert_called_once_with()
        subprocess_probe.assert_not_called()

    def test_installed_browser_types_uses_subprocess_probe_inside_event_loop(self) -> None:
        async def run() -> list[str]:
            with patch.object(browser_installation, "_installed_browser_types_direct", return_value=[]) as direct, patch.object(
                browser_installation, "_installed_browser_types_subprocess", return_value=["chromium"]
            ) as subprocess_probe:
                result = browser_installation.installed_browser_types()
            direct.assert_not_called()
            subprocess_probe.assert_called_once_with()
            return result

        self.assertEqual(asyncio.run(run()), ["chromium"])


if __name__ == "__main__":
    unittest.main()
