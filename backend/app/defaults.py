from __future__ import annotations

from .config import ALERT_DETAIL_BASE_URL


DEFAULT_SETTINGS: dict[str, object] = {
    "default_interval_seconds": 300,
    "default_ui_timeout_ms": 15000,
    "default_api_timeout_ms": 10000,
    "max_concurrency": 2,
    "max_task_runtime_seconds": 60,
    "alerts_enabled": False,
    "alert_detail_base_url": ALERT_DETAIL_BASE_URL,
    "notification_channels": [],
    "alert_cooldown_minutes": 30,
    "recovery_notification": True,
    "browser_headless": True,
    "browser_type": "chromium",
    "browser_proxy": "",
    "browser_viewport": "1440x900",
    "run_retention_days": 30,
    "screenshot_retention_days": 30,
    "trace_retention_days": 7,
    "response_retention_days": 30,
}


UI_SCRIPT_TEMPLATE = """async def check(ctx):
    page = await ctx.new_page()

    await page.goto(ctx.entry_url, wait_until="networkidle")

    await ctx.expect_text(page, "Example Domain")
    await ctx.expect_hidden(page, "text=系统异常")
"""


API_SCRIPT_TEMPLATE = """async def check(ctx):
    resp = await ctx.request()

    ctx.assert_status(resp, 200)

    data = resp.json()

    ctx.assert_json_schema(data, {
        "type": "object",
        "required": ["userId", "id", "title", "completed"],
        "properties": {
            "userId": {"type": "integer"},
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "completed": {"type": "boolean"}
        }
    })

    ctx.save_response(resp)
"""


API_ASSERTIONS_TEMPLATE = """[
  {"id": "status-200", "type": "status_code", "enabled": true, "expected_status": 200},
  {"id": "duration-1000", "type": "response_time", "enabled": true, "max_ms": 1000},
  {"id": "field-id", "type": "json_path_exists", "enabled": true, "path": "$.id"},
  {"id": "field-title", "type": "json_path_exists", "enabled": true, "path": "$.title"}
]"""


DEMO_CHECKS = [
    {
        "name": "Example Domain 页面",
        "type": "ui",
        "enabled": True,
        "interval_seconds": 300,
        "timeout_ms": 15000,
        "entry_url": "https://example.com",
        "method": "",
        "headers_json": "{}",
        "body": "",
        "assertions_json": "[]",
        "script": UI_SCRIPT_TEMPLATE,
        "tags": "demo,public",
    },
    {
        "name": "JSONPlaceholder Todo 接口",
        "type": "api",
        "enabled": True,
        "interval_seconds": 300,
        "timeout_ms": 10000,
        "entry_url": "https://jsonplaceholder.typicode.com/todos/1",
        "method": "GET",
        "headers_json": "{}",
        "body": "",
        "assertions_json": API_ASSERTIONS_TEMPLATE,
        "script": "",
        "tags": "demo,public",
    },
]
