from __future__ import annotations

import unittest

from backend.app.browser_types import normalized_browser_settings


class BrowserTypeSettingsTests(unittest.TestCase):
    def test_explicit_enabled_browser_types_do_not_reenable_legacy_browser_type(self) -> None:
        settings = normalized_browser_settings(
            {
                "browser_type": "chromium",
                "enabled_browser_types": ["firefox"],
                "prewarmed_browser_types": ["chromium", "firefox"],
            }
        )

        self.assertEqual(settings["browser_type"], "firefox")
        self.assertEqual(settings["enabled_browser_types"], ["firefox"])
        self.assertEqual(settings["prewarmed_browser_types"], ["firefox"])

    def test_legacy_browser_pool_size_maps_to_each_type_when_pool_sizes_are_absent(self) -> None:
        settings = normalized_browser_settings({"browser_pool_size": 3})

        self.assertEqual(settings["browser_pool_sizes"], {"chromium": 3, "firefox": 3, "webkit": 3})


if __name__ == "__main__":
    unittest.main()
