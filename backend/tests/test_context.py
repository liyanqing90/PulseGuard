from __future__ import annotations

import unittest

from backend.app.context import RunContext


class RunContextViewportTests(unittest.TestCase):
    def test_h5_task_uses_mobile_browser_context_options(self) -> None:
        ctx = RunContext(
            {
                "name": "H5 页面",
                "type": "ui",
                "entry_url": "https://example.com",
                "viewport_mode": "h5",
                "method": "",
                "headers_json": "{}",
                "body": "",
                "timeout_ms": 15000,
            },
            1,
            {"browser_viewport": "1440x900"},
            artifacts=None,  # type: ignore[arg-type]
        )

        options = ctx._browser_context_options()

        self.assertEqual(options["viewport"], {"width": 390, "height": 844})
        self.assertTrue(options["is_mobile"])
        self.assertTrue(options["has_touch"])

    def test_web_task_uses_configured_browser_viewport(self) -> None:
        ctx = RunContext(
            {
                "name": "Web 页面",
                "type": "ui",
                "entry_url": "https://example.com",
                "viewport_mode": "web",
                "method": "",
                "headers_json": "{}",
                "body": "",
                "timeout_ms": 15000,
            },
            1,
            {"browser_viewport": "1366x768"},
            artifacts=None,  # type: ignore[arg-type]
        )

        options = ctx._browser_context_options()

        self.assertEqual(options, {"viewport": {"width": 1366, "height": 768}})


if __name__ == "__main__":
    unittest.main()
