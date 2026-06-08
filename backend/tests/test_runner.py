from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

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


class RunnerQueueTests(unittest.TestCase):
    def test_queue_capacity_skips_excess_submissions(self) -> None:
        async def scenario() -> list[dict[str, object]]:
            first_started = asyncio.Event()
            release_first = asyncio.Event()

            async def execute(check: dict[str, object], trigger: str, run_id: int, record_status: bool = True, notify: bool = True) -> dict[str, object]:
                if check["id"] == 1:
                    first_started.set()
                    await release_first.wait()
                else:
                    await asyncio.sleep(0.01)
                return {"id": run_id, "check_id": check["id"], "status": "ok", "trigger": trigger}

            with runner_patches(max_concurrency=1, max_queue_size=1):
                runner = CheckRunner()
                runner._execute = execute  # type: ignore[method-assign]
                first = asyncio.create_task(runner.run_check(1))
                await first_started.wait()
                second = asyncio.create_task(runner.run_check(2))
                for _ in range(20):
                    if runner.runtime_status()["queue"]["queued"] == 1:
                        break
                    await asyncio.sleep(0)
                third = await runner.run_check(3)
                release_first.set()
                results = [await first, await second, third]
                await runner.shutdown()
                return results

        results = asyncio.run(scenario())

        self.assertEqual([result["status"] for result in results].count("skipped"), 1)
        skipped = next(result for result in results if result["status"] == "skipped")
        self.assertIn("执行队列已满", str(skipped["error_message"]))

    def test_ui_jobs_are_capped_independently_from_global_concurrency(self) -> None:
        active_ui = 0
        max_active_ui = 0

        async def scenario() -> list[dict[str, object]]:
            nonlocal active_ui, max_active_ui

            async def execute(check: dict[str, object], trigger: str, run_id: int, record_status: bool = True, notify: bool = True) -> dict[str, object]:
                nonlocal active_ui, max_active_ui
                active_ui += 1
                max_active_ui = max(max_active_ui, active_ui)
                try:
                    await asyncio.sleep(0.03)
                    return {"id": run_id, "check_id": check["id"], "status": "ok", "trigger": trigger}
                finally:
                    active_ui -= 1

            with runner_patches(max_concurrency=2, max_ui_concurrency=1, check_type="ui"):
                runner = CheckRunner()
                runner._execute = execute  # type: ignore[method-assign]
                results = await asyncio.gather(runner.run_check(1), runner.run_check(2))
                await runner.shutdown()
                return results

        results = asyncio.run(scenario())

        self.assertEqual([result["status"] for result in results], ["ok", "ok"])
        self.assertEqual(max_active_ui, 1)


def runner_patches(max_concurrency: int = 2, max_ui_concurrency: int = 1, max_queue_size: int = 50, check_type: str = "api"):
    run_ids = {"value": 0}

    def check_for(check_id: int) -> dict[str, object]:
        return {
            "id": check_id,
            "name": f"任务 {check_id}",
            "type": check_type,
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 10000,
            "entry_url": "https://example.com/health",
            "method": "GET" if check_type == "api" else "",
            "headers_json": "{}",
            "body": "",
            "assertions_json": '[{"type":"status_code","expected_status":200}]' if check_type == "api" else '[{"type":"title_contains","expected_text":"Example"}]',
            "setup_script": "",
            "script": "",
            "tags": "",
        }

    def create_run(check: dict[str, object], status: str = "running", error_message: str | None = None) -> dict[str, object]:
        run_ids["value"] += 1
        return {
            "id": run_ids["value"],
            "check_id": int(check.get("id") or 0),
            "status": status,
            "error_message": error_message,
        }

    settings = {
        "max_concurrency": max_concurrency,
        "max_ui_concurrency": max_ui_concurrency,
        "max_queue_size": max_queue_size,
        "max_task_runtime_seconds": 60,
        "browser_type": "chromium",
        "browser_headless": True,
    }
    return patch.multiple(
        "backend.app.runner.storage",
        get_settings=Mock(return_value=settings),
        get_check=Mock(side_effect=check_for),
        create_run=Mock(side_effect=create_run),
        start_run=Mock(),
    )


if __name__ == "__main__":
    unittest.main()
