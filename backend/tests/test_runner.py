from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.runner import CheckRunner


class DraftRunnerTests(unittest.TestCase):
    def test_draft_run_does_not_update_task_status_or_send_notification(self) -> None:
        check = {
            "name": "草稿调试",
            "type": "api",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 10000,
            "entry_url": "https://example.com/health",
            "method": "GET",
            "headers_json": "{}",
            "body": "",
            "script": "async def check(ctx):\n    print('draft ok')\n",
            "tags": "",
        }
        created_run = {"id": 123, "status": "running"}
        finished_run = {"id": 123, "check_id": 0, "status": "ok"}
        final_run = {**finished_run, "notification_status": "not_required"}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch("backend.app.runner.storage.create_run", return_value=created_run), patch(
            "backend.app.runner.storage.finish_run", return_value=finished_run
        ), patch("backend.app.runner.storage.get_run", return_value=final_run), patch(
            "backend.app.runner.storage.update_run_notification"
        ) as update_run_notification, patch(
            "backend.app.runner.storage.update_check_status"
        ) as update_check_status, patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify:
            runner = CheckRunner()
            result = asyncio.run(runner.run_draft(check))

        self.assertEqual(result, final_run)
        update_run_notification.assert_called_once_with(123, "not_required", channel=None, error=None, sent_at=None)
        update_check_status.assert_not_called()
        maybe_notify.assert_not_called()

    def test_structured_api_check_runs_without_loading_user_script(self) -> None:
        check = {
            "id": 7,
            "name": "无脚本接口",
            "type": "api",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 10000,
            "entry_url": "https://example.com/health",
            "method": "GET",
            "headers_json": "{}",
            "body": "",
            "assertions_json": '[{"type":"status_code","expected_status":200}]',
            "script": "",
            "tags": "",
        }
        created_run = {"id": 124, "status": "running"}
        finished_run = {"id": 124, "check_id": 7, "status": "ok"}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch("backend.app.runner.storage.finish_run", return_value=finished_run), patch(
            "backend.app.runner.storage.get_run", return_value=finished_run
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "ok", "previous_status": None}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify, patch(
            "backend.app.runner.run_structured_api_check", new_callable=AsyncMock
        ) as run_structured_api_check, patch.object(
            CheckRunner, "_load_check_function", side_effect=AssertionError("script should not load")
        ):
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(7))

        self.assertEqual(result, finished_run)
        run_structured_api_check.assert_awaited_once()
        maybe_notify.assert_awaited_once()

    def test_structured_ui_check_runs_without_loading_user_script(self) -> None:
        check = {
            "id": 8,
            "name": "无脚本 UI",
            "type": "ui",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 15000,
            "entry_url": "https://example.com",
            "method": "",
            "headers_json": "{}",
            "body": "",
            "assertions_json": '[{"type":"title_contains","expected_text":"Example"}]',
            "script": "",
            "tags": "",
        }
        created_run = {"id": 125, "status": "running"}
        finished_run = {"id": 125, "check_id": 8, "status": "ok"}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch("backend.app.runner.storage.finish_run", return_value=finished_run), patch(
            "backend.app.runner.storage.get_run", return_value=finished_run
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "ok", "previous_status": None}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify, patch(
            "backend.app.runner.run_structured_ui_check", new_callable=AsyncMock
        ) as run_structured_ui_check, patch.object(
            CheckRunner, "_load_check_function", side_effect=AssertionError("script should not load")
        ):
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(8))

        self.assertEqual(result, finished_run)
        run_structured_ui_check.assert_awaited_once()
        maybe_notify.assert_awaited_once()

    def test_structured_ui_check_loads_setup_script_without_running_advanced_script(self) -> None:
        check = {
            "id": 9,
            "name": "带前置脚本 UI",
            "type": "ui",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 15000,
            "entry_url": "https://example.com/dashboard",
            "method": "",
            "headers_json": "{}",
            "body": "",
            "assertions_json": '[{"type":"title_contains","expected_text":"Dashboard"}]',
            "setup_script": "async def setup(ctx, page):\n    ctx.log('setup ok')\n",
            "script": "async def check(ctx):\n    raise AssertionError('advanced script should not run')\n",
            "tags": "",
        }
        created_run = {"id": 126, "status": "running"}
        finished_run = {"id": 126, "check_id": 9, "status": "ok"}
        setup_func = AsyncMock()

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch("backend.app.runner.storage.finish_run", return_value=finished_run), patch(
            "backend.app.runner.storage.get_run", return_value=finished_run
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "ok", "previous_status": None}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ), patch(
            "backend.app.runner.run_structured_ui_check", new_callable=AsyncMock
        ) as run_structured_ui_check, patch.object(
            CheckRunner, "_load_check_function", return_value=setup_func
        ) as load_check_function:
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(9))

        self.assertEqual(result, finished_run)
        load_check_function.assert_called_once()
        self.assertEqual(load_check_function.call_args.kwargs["function_name"], "setup")
        self.assertIs(run_structured_ui_check.call_args.kwargs["setup_func"], setup_func)


if __name__ == "__main__":
    unittest.main()
