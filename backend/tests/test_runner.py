from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from backend.app.runner import CheckRunner, RunFailure, RunnerEnvironmentFailure


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
        result_data = {
            "status": "ok",
            "finished_at": "2026-01-01T00:00:01+08:00",
            "duration_ms": 10,
            "error_message": None,
            "error_stack": None,
            "logs": "draft ok",
            "screenshot_path": None,
            "trace_path": None,
            "response_path": None,
            "request_snapshot": None,
            "response_snapshot": None,
            "failure_kind": "none",
        }

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch(
            "backend.app.runner.storage.get_probe_runner",
            return_value={"runner_id": "local", "name": "本机节点", "network_region": "local", "address": "", "browser_version": ""},
        ), patch.object(
            CheckRunner,
            "_execute_core",
            new_callable=AsyncMock,
            return_value=result_data,
        ) as execute_core, patch("backend.app.runner.storage.create_run") as create_run, patch(
            "backend.app.runner.storage.finish_run"
        ) as finish_run, patch("backend.app.runner.storage.get_run") as get_run, patch(
            "backend.app.runner.storage.update_run_notification"
        ) as update_run_notification, patch(
            "backend.app.runner.storage.update_check_status"
        ) as update_check_status, patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify:
            runner = CheckRunner()
            result = asyncio.run(runner.run_draft(check))

        self.assertEqual(result["id"], 0)
        self.assertEqual(result["check_id"], 0)
        self.assertEqual(result["check_name"], "草稿调试")
        self.assertEqual(result["check_type"], "api")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["notification_status"], "not_required")
        self.assertEqual(result["observation_kind"], "draft")
        self.assertFalse(result["affects_health"])
        self.assertEqual(result["runner_id"], "local")
        execute_core.assert_awaited_once()
        create_run.assert_not_called()
        finish_run.assert_not_called()
        get_run.assert_not_called()
        update_run_notification.assert_not_called()
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
        ) as create_run, patch(
            "backend.app.runner.storage.finish_run", return_value=finished_run
        ), patch(
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
            result = asyncio.run(runner.run_check(7, trigger="manual"))

        self.assertEqual(result, finished_run)
        manual_payload = create_run.call_args.args[0]
        self.assertEqual(manual_payload["_run"]["trigger"], "manual")
        self.assertEqual(manual_payload["_run"]["observation_kind"], "observation")
        self.assertTrue(manual_payload["_run"]["affects_health"])
        run_structured_api_check.assert_awaited_once()
        maybe_notify.assert_awaited_once()

    def test_duration_excludes_preparation_and_notification_latency(self) -> None:
        check = {
            "id": 27,
            "name": "Precise duration API",
            "type": "api",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 10000,
            "entry_url": "https://example.com/health",
            "method": "GET",
            "headers_json": "{}",
            "body": "",
            "assertions_json": "[]",
            "script": "async def check(ctx): pass",
            "tags": "",
        }
        created_run = {"id": 270, "status": "running"}
        captured_duration: list[int] = []

        async def actual_task(_ctx: object) -> None:
            await asyncio.sleep(0.01)

        def load_check_function(*_args: object, **_kwargs: object) -> object:
            time.sleep(0.2)
            return actual_task

        def finish_run(run_id: int, data: dict[str, object]) -> dict[str, object]:
            captured_duration.append(int(data["duration_ms"]))
            return {"id": run_id, "check_id": 27, **data}

        async def slow_notify(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(0.2)

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value={"max_task_runtime_seconds": 60, "browser_type": "chromium", "browser_headless": True},
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch(
            "backend.app.runner.storage.finish_run", side_effect=finish_run
        ), patch(
            "backend.app.runner.storage.get_run", return_value=None
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "ok", "previous_status": None}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock, side_effect=slow_notify
        ), patch.object(
            CheckRunner, "_load_check_function", side_effect=load_check_function
        ):
            result = asyncio.run(CheckRunner().run_check(27, trigger="manual"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(captured_duration), 1)
        self.assertLess(captured_duration[0], 150)

    def test_target_failure_records_runner_metadata_and_failure_kind(self) -> None:
        check = {
            "id": 17,
            "name": "Runner metadata API",
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
        settings = {
            "max_task_runtime_seconds": 60,
            "browser_type": "chromium",
            "browser_headless": True,
            "local_runner_name": "office-runner",
            "local_runner_address": "10.0.0.8",
            "local_runner_region": "office-lan",
        }
        created_run = {"id": 170, "status": "running"}
        finished_run = {"id": 170, "check_id": 17, "status": "failed"}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value=settings,
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch(
            "backend.app.runner.storage.finish_run", return_value=finished_run
        ) as finish_run, patch(
            "backend.app.runner.storage.get_run", return_value=finished_run
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "failed", "previous_status": None}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ), patch(
            "backend.app.runner.run_structured_api_check", new_callable=AsyncMock, side_effect=RunFailure("target failed")
        ):
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(17))

        self.assertEqual(result, finished_run)
        finish_payload = finish_run.call_args.args[1]
        self.assertEqual(finish_payload["status"], "failed")
        self.assertEqual(finish_payload["failure_kind"], "target")
        self.assertEqual(finish_payload["runner_name"], "office-runner")
        self.assertEqual(finish_payload["runner_address"], "10.0.0.8")
        self.assertEqual(finish_payload["runner_region"], "office-lan")
        self.assertEqual(finish_payload["runner_browser_version"], "")

    def test_target_failure_retry_can_recover_with_single_run_record(self) -> None:
        check = {
            "id": 19,
            "name": "Retry API",
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
        settings = {
            "max_task_runtime_seconds": 60,
            "browser_type": "chromium",
            "browser_headless": True,
            "api_retry_attempts": 1,
            "local_runner_name": "office-runner",
            "local_runner_address": "10.0.0.8",
            "local_runner_region": "office-lan",
        }
        created_run = {"id": 190, "status": "running"}
        finished_runs: list[dict[str, object]] = []

        def finish_run(run_id: int, data: dict[str, object]) -> dict[str, object]:
            finished = {"id": run_id, "check_id": 19, **data}
            finished_runs.append(finished)
            return finished

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value=settings,
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ) as create_run, patch(
            "backend.app.runner.storage.finish_run", side_effect=finish_run
        ), patch(
            "backend.app.runner.storage.get_run", return_value=None
        ), patch(
            "backend.app.runner.storage.update_check_status", return_value={"current_status": "healthy", "previous_status": "unknown"}
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ), patch(
            "backend.app.runner.run_structured_api_check", new_callable=AsyncMock, side_effect=[RunFailure("flaky"), None]
        ) as run_structured_api_check:
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(19))

        self.assertEqual(result["status"], "ok")
        create_run.assert_called_once()
        self.assertEqual(run_structured_api_check.await_count, 2)
        self.assertEqual(len(finished_runs), 1)
        self.assertEqual(finished_runs[0]["status"], "ok")
        self.assertIn("本次尝试失败，立即重试：flaky", str(finished_runs[0]["logs"]))

    def test_runner_environment_failure_does_not_persist_task_run(self) -> None:
        check = {
            "id": 18,
            "name": "Runner browser failure",
            "type": "ui",
            "enabled": True,
            "interval_seconds": 300,
            "timeout_ms": 10000,
            "entry_url": "https://example.com",
            "method": "",
            "headers_json": "{}",
            "body": "",
            "assertions_json": '[{"type":"title_contains","expected_text":"Example"}]',
            "script": "",
            "tags": "",
        }
        settings = {
            "max_task_runtime_seconds": 60,
            "browser_type": "chromium",
            "browser_headless": True,
            "local_runner_name": "office-runner",
            "local_runner_address": "10.0.0.8",
            "local_runner_region": "office-lan",
        }
        created_run = {"id": 180, "status": "running"}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch(
            "backend.app.runner.storage.get_settings",
            return_value=settings,
        ), patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.create_run", return_value=created_run
        ), patch(
            "backend.app.runner.storage.finish_run"
        ) as finish_run, patch(
            "backend.app.runner.storage.discard_incomplete_run", return_value=True
        ) as discard_incomplete_run, patch(
            "backend.app.runner.storage.update_check_status"
        ) as update_check_status, patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify, patch(
            "backend.app.runner.run_structured_ui_check", new_callable=AsyncMock, side_effect=RunnerEnvironmentFailure("browser failed")
        ):
            runner = CheckRunner()
            result = asyncio.run(runner.run_check(18))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_kind"], "runner")
        self.assertFalse(result["affects_health"])
        self.assertEqual(result["observation_kind"], "runner")
        finish_run.assert_not_called()
        discard_incomplete_run.assert_called_once_with(180)
        update_check_status.assert_not_called()
        maybe_notify.assert_not_called()

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

    def test_ui_inspect_loads_setup_script_for_scan(self) -> None:
        setup_func = AsyncMock()
        settings = {
            "max_concurrency": 2,
            "max_ui_concurrency": 1,
            "max_queue_size": 50,
            "max_task_runtime_seconds": 60,
            "default_ui_timeout_ms": 15000,
            "browser_type": "chromium",
            "browser_headless": True,
        }
        payload = {
            "type": "ui",
            "entry_url": "https://example.com/dashboard",
            "timeout_ms": 15000,
            "viewport_mode": "web",
            "setup_script": "async def setup(ctx, page):\n    ctx.log('scan setup')\n",
        }
        inspect_result = {"title": "Dashboard", "url": "https://example.com/dashboard", "candidates": [], "screenshot": ""}

        with patch.object(CheckRunner, "_max_concurrency", return_value=2), patch.object(
            CheckRunner, "_max_ui_concurrency", return_value=1
        ), patch.object(
            CheckRunner, "_max_queue_size", return_value=50
        ), patch(
            "backend.app.runner.storage.get_settings", return_value=settings
        ), patch(
            "backend.app.ui_assertions.inspect_ui_page", new_callable=AsyncMock, return_value=inspect_result
        ) as inspect_ui_page, patch.object(
            CheckRunner, "_load_check_function", return_value=setup_func
        ) as load_check_function:
            runner = CheckRunner()
            result = asyncio.run(runner.inspect_ui(payload))

        self.assertEqual(result, inspect_result)
        load_check_function.assert_called_once()
        self.assertEqual(load_check_function.call_args.kwargs["function_name"], "setup")
        inspect_ui_page.assert_awaited_once()
        self.assertIs(inspect_ui_page.call_args.kwargs["setup_func"], setup_func)
        self.assertEqual(inspect_ui_page.call_args.kwargs["ctx"].entry_url, payload["entry_url"])


class RunnerQueueTests(unittest.TestCase):
    def test_queue_capacity_skips_excess_submissions(self) -> None:
        async def scenario() -> list[dict[str, object]]:
            first_started = asyncio.Event()
            release_first = asyncio.Event()

            async def execute(
                check: dict[str, object],
                trigger: str,
                run_id: int,
                record_status: bool = True,
                notify: bool = True,
                runner_metadata: dict[str, object] | None = None,
            ) -> dict[str, object]:
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

            async def execute(
                check: dict[str, object],
                trigger: str,
                run_id: int,
                record_status: bool = True,
                notify: bool = True,
                runner_metadata: dict[str, object] | None = None,
            ) -> dict[str, object]:
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


class DistributedRunnerTests(unittest.TestCase):
    def test_remote_runner_timeout_covers_retry_budget(self) -> None:
        runner = CheckRunner()
        timeout = runner._remote_runner_timeout_seconds(
            {"type": "ui", "timeout_ms": 10000},
            {"max_task_runtime_seconds": 60, "ui_retry_attempts": 1},
        )

        self.assertEqual(timeout, 135.0)

    def test_remote_runner_timeout_error_is_actionable(self) -> None:
        class TimeoutClient:
            async def __aenter__(self) -> "TimeoutClient":
                return self

            async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> httpx.Response:
                raise httpx.ReadTimeout("")

        async def scenario() -> None:
            with patch(
                "backend.app.runner.storage.get_settings",
                return_value={"max_task_runtime_seconds": 60, "ui_retry_attempts": 1},
            ), patch("backend.app.runner.httpx.AsyncClient", return_value=TimeoutClient()):
                await CheckRunner()._call_remote_runner(
                    {"runner_id": "edge-1", "address": "http://10.0.0.8:8788", "_token": "pgrn_token"},
                    {"id": 31, "name": "Remote timeout", "type": "ui", "timeout_ms": 10000},
                    "manual",
                    310,
                )

        with self.assertRaisesRegex(RuntimeError, "执行节点调用超时，等待 135 秒后未返回"):
            asyncio.run(scenario())

    def test_disabled_local_runner_is_skipped_without_executing_probe(self) -> None:
        check = {
            "id": 31,
            "name": "Disabled local runner",
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
            "runner_selection_mode": "selected_parallel",
            "runner_ids": ["local"],
        }
        local_runner = {
            "runner_id": "local",
            "name": "local",
            "address": "127.0.0.1",
            "network_region": "local",
            "browser_version": "",
            "status": "offline",
            "enabled": False,
            "available": False,
            "role": "local",
        }

        def finish_run(run_id: int, data: dict[str, object]) -> dict[str, object]:
            return {"id": run_id, "check_id": 31, "affects_health": True, **data}

        with patch("backend.app.runner.storage.get_check", return_value=check), patch(
            "backend.app.runner.storage.list_probe_runners_by_ids", return_value=[local_runner]
        ), patch("backend.app.runner.storage.get_settings", return_value={}), patch(
            "backend.app.runner.storage.create_run", return_value={"id": 310, "check_id": 31, "status": "pending"}
        ), patch("backend.app.runner.storage.finish_run", side_effect=finish_run), patch(
            "backend.app.runner.storage.get_run", return_value=None
        ), patch("backend.app.runner.storage.discard_incomplete_run", return_value=True) as discard_incomplete_run, patch(
            "backend.app.runner.storage.update_run_notification"
        ) as update_run_notification, patch(
            "backend.app.runner.storage.update_check_status"
        ) as update_check_status, patch(
            "backend.app.runner.storage.get_probe_runner", return_value=local_runner
        ), patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify, patch.object(
            CheckRunner, "_execute", new_callable=AsyncMock, side_effect=AssertionError("disabled local runner should not execute")
        ) as execute:
            result = asyncio.run(CheckRunner().run_check(31, trigger="manual"))

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["failure_kind"], "runner")
        self.assertFalse(result["affects_health"])
        execute.assert_not_awaited()
        discard_incomplete_run.assert_called_once_with(310)
        update_run_notification.assert_not_called()
        update_check_status.assert_not_called()
        maybe_notify.assert_not_called()

    def test_runner_only_distributed_group_does_not_update_target_health(self) -> None:
        check = {"id": 32, "name": "Runner only", "type": "api"}
        runner_failure = {
            "id": 320,
            "check_id": 32,
            "status": "skipped",
            "failure_kind": "runner",
            "affects_health": True,
        }

        with patch("backend.app.runner.storage.update_check_status") as update_check_status, patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify:
            result = asyncio.run(CheckRunner()._finish_distributed_group(check, [runner_failure], "manual"))

        self.assertEqual(result, runner_failure)
        update_check_status.assert_not_called()
        maybe_notify.assert_not_called()

    def test_distributed_group_target_failure_wins_over_success_and_updates_once(self) -> None:
        check = {"id": 33, "name": "Aggregate target failure", "type": "api"}
        success = {
            "id": 331,
            "check_id": 33,
            "status": "ok",
            "failure_kind": "none",
            "affects_health": True,
        }
        target_failure = {
            "id": 332,
            "check_id": 33,
            "status": "failed",
            "failure_kind": "target",
            "affects_health": True,
        }

        with patch(
            "backend.app.runner.storage.update_check_status",
            return_value={"current_status": "failing", "previous_status": "healthy"},
        ) as update_check_status, patch(
            "backend.app.runner.notifier.maybe_notify", new_callable=AsyncMock
        ) as maybe_notify:
            result = asyncio.run(CheckRunner()._finish_distributed_group(check, [success, target_failure], "manual"))

        self.assertEqual(result, target_failure)
        update_check_status.assert_called_once_with(33, target_failure)
        maybe_notify.assert_awaited_once()


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
