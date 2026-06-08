from __future__ import annotations

import asyncio
import unittest

from backend.app import ui_assertions
from backend.app.context import RunFailure


class FakeLocator:
    def __init__(self, *, visible: bool = True, count: int = 1) -> None:
        self.first = self
        self.visible = visible
        self._count = count

    async def wait_for(self, state: str, timeout: int) -> None:
        if state == "visible" and not self.visible:
            raise RuntimeError("not visible")
        if state == "hidden" and self.visible:
            raise RuntimeError("still visible")

    async def count(self) -> int:
        return self._count

    async def evaluate(self, script: str) -> dict[str, object]:
        return {"text": "卡片内容", "hasMedia": False, "visibleChildCount": 0, "width": 120, "height": 80}


class FakePage:
    url = "https://example.com/dashboard"

    def __init__(self) -> None:
        self.gotos: list[str] = []
        self.setup_marker = ""

    async def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.gotos.append(url)
        self.url = "https://example.com/dashboard" if url == "https://example.com" else url

    def locator(self, selector: str) -> FakeLocator:
        if selector == ".invalid":
            raise ValueError("selector parse failed")
        if selector == ".missing":
            return FakeLocator(visible=False, count=0)
        if selector == ".many":
            return FakeLocator(visible=True, count=3)
        if selector == ".items":
            return FakeLocator(visible=True, count=3)
        return FakeLocator()

    def get_by_text(self, text: str) -> FakeLocator:
        return FakeLocator(visible=text == "首页")

    async def evaluate(self, script: str) -> dict[str, object]:
        return {"textLength": 12, "preview": "页面内容", "mediaCount": 1, "interactiveCount": 2, "width": 1440, "height": 900}

    async def title(self) -> str:
        return "PulseGuard 首页"


class FakeContext:
    def __init__(self, assertions_json: str) -> None:
        self.check = {"assertions_json": assertions_json}
        self.settings = {
            "environment_variables": [
                {"id": "title", "name": "EXPECTED_TITLE", "value": "PulseGuard", "secret": False}
            ]
        }
        self.entry_url = "https://example.com"
        self.viewport_mode = "web"
        self.timeout_ms = 1000
        self.console_messages: list[dict[str, str]] = []
        self.response_snapshot = None
        self.logs: list[str] = []
        self.page = FakePage()

    async def new_page(self) -> FakePage:
        return self.page

    def log(self, message: object) -> None:
        self.logs.append(str(message))


class UiAssertionTests(unittest.TestCase):
    def test_normalize_ui_assertions_requires_selector_for_element_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "选择器不能为空"):
            ui_assertions.normalize_ui_assertions('[{"type":"element_visible"}]')

    def test_normalize_ui_assertions_preserves_selector_metadata(self) -> None:
        normalized = ui_assertions.normalize_ui_assertions(
            """
            [{
              "type":"element_visible",
              "selector":"#submit",
              "selector_type":"role",
              "selector_stability":"low",
              "selector_score":72.5
            }]
            """
        )

        self.assertEqual(normalized[0]["selector_type"], "role")
        self.assertEqual(normalized[0]["selector_stability"], "low")
        self.assertEqual(normalized[0]["selector_score"], 72.5)

    def test_inspect_ui_selector_rules_reports_selector_health(self) -> None:
        page = FakePage()

        results = asyncio.run(
            ui_assertions.inspect_ui_selector_rules(
                """
                [
                  {"id":"ok","type":"element_visible","selector":"#app"},
                  {"id":"missing","type":"element_visible","selector":".missing"},
                  {"id":"multiple","type":"element_not_empty","selector":".many"},
                  {"id":"count","type":"element_count","selector":".many","operator":"gte","expected_count":2},
                  {"id":"invalid","type":"element_visible","selector":".invalid"},
                  {"id":"disabled","type":"element_visible","selector":"#app","enabled":false},
                  {"id":"text","type":"title_contains","expected_text":"PulseGuard"}
                ]
                """,
                page,
            )
        )

        statuses = {item["id"]: item["status"] for item in results}
        self.assertEqual(statuses["ok"], "ok")
        self.assertEqual(statuses["missing"], "missing")
        self.assertEqual(statuses["multiple"], "multiple")
        self.assertEqual(statuses["count"], "ok")
        self.assertEqual(statuses["invalid"], "invalid_selector")
        self.assertEqual(statuses["disabled"], "disabled")
        self.assertNotIn("text", statuses)

    def test_structured_ui_check_records_results_and_passes(self) -> None:
        ctx = FakeContext(
            """
            [
              {"type":"element_visible","selector":"#app"},
              {"type":"element_not_empty","selector":".card"},
              {"type":"page_not_blank"},
              {"type":"text_present","expected_text":"首页"},
              {"type":"title_contains","expected_text":"PulseGuard"},
              {"type":"url_contains","expected_text":"/dashboard"},
              {"type":"element_count","selector":".items","operator":"gte","expected_count":2},
              {"type":"console_error_absent"}
            ]
            """
        )

        asyncio.run(ui_assertions.run_structured_ui_check(ctx))  # type: ignore[arg-type]

        self.assertIsNotNone(ctx.response_snapshot)
        self.assertEqual(len(ctx.response_snapshot["assertions"]), 8)
        self.assertTrue(all(item["status"] == "ok" for item in ctx.response_snapshot["assertions"]))

    def test_structured_ui_check_fails_with_actionable_result(self) -> None:
        ctx = FakeContext('[{"type":"text_absent","expected_text":"首页"}]')

        with self.assertRaisesRegex(RunFailure, "UI 结构化校验失败"):
            asyncio.run(ui_assertions.run_structured_ui_check(ctx))  # type: ignore[arg-type]

        self.assertEqual(ctx.response_snapshot["assertions"][0]["status"], "failed")

    def test_setup_script_runs_on_same_page_before_assertions(self) -> None:
        ctx = FakeContext('[{"type":"title_contains","expected_text":"${EXPECTED_TITLE}"}]')
        seen: dict[str, object] = {}

        async def setup(setup_ctx: FakeContext, page: FakePage) -> None:
            seen["ctx"] = setup_ctx
            seen["page"] = page
            await page.goto("https://example.com/login", wait_until="domcontentloaded", timeout=setup_ctx.timeout_ms)
            page.setup_marker = "prepared"
            page.url = "https://example.com/session-ready"

        asyncio.run(ui_assertions.run_structured_ui_check(ctx, setup_func=setup))  # type: ignore[arg-type]

        self.assertIs(seen["ctx"], ctx)
        self.assertIs(seen["page"], ctx.page)
        self.assertEqual(ctx.page.setup_marker, "prepared")
        self.assertEqual(ctx.page.gotos, ["https://example.com/login", "https://example.com"])
        self.assertEqual(ctx.response_snapshot["page"]["url"], "https://example.com/dashboard")


if __name__ == "__main__":
    unittest.main()
