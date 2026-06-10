from __future__ import annotations

import asyncio
import inspect
import json
import re
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, AsyncIterator

from .api_assertions import has_enabled_api_assertions, run_structured_api_check
from .ui_assertions import has_enabled_ui_assertions, run_structured_ui_check
from . import notifier, storage
from .artifacts import ArtifactStore
from .context import RunContext, RunFailure, RunnerEnvironmentFailure
from .monitoring import run_metadata
from .resource_pool import ProbeResourcePool
from .variables import mask_data, mask_text


@dataclass
class RunJob:
    check: dict[str, Any]
    trigger: str
    run_id: int
    record_status: bool
    notify: bool
    future: asyncio.Future[dict[str, Any]]
    started: bool = False


class AsyncCapacityLimiter:
    def __init__(self, capacity: int) -> None:
        self._capacity = max(1, int(capacity))
        self._in_use = 0
        self._condition = asyncio.Condition()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self.acquire()
        try:
            yield
        finally:
            await self.release()

    async def acquire(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._in_use < self._capacity)
            self._in_use += 1

    async def release(self) -> None:
        async with self._condition:
            self._in_use = max(0, self._in_use - 1)
            self._condition.notify_all()

    async def resize(self, capacity: int) -> None:
        async with self._condition:
            self._capacity = max(1, int(capacity))
            self._condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        return {"limit": self._capacity, "in_use": self._in_use, "available": max(0, self._capacity - self._in_use)}


class CheckRunner:
    def __init__(self) -> None:
        self.artifacts = ArtifactStore()
        self._active_checks: set[int] = set()
        self._lock = asyncio.Lock()
        self._queue_limit = self._max_queue_size()
        self._queued_jobs = 0
        self._running_jobs = 0
        self._jobs: set[asyncio.Task[None]] = set()
        self._closing = False
        self._global_limiter = AsyncCapacityLimiter(self._max_concurrency())
        self._ui_limiter = AsyncCapacityLimiter(self._max_ui_concurrency())
        self.resources = ProbeResourcePool(self._api_pool_size(), self._browser_pool_size())

    async def start(self) -> None:
        self._closing = False
        settings = storage.get_settings()
        await self.resources.start(
            settings,
            api_pool_size=self._api_pool_size(settings),
            browser_pool_size=self._browser_pool_size(settings),
        )

    async def shutdown(self) -> None:
        async with self._lock:
            self._closing = True
            jobs = [job for job in self._jobs if not job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        await self.resources.shutdown()

    async def reload_settings(self) -> None:
        settings = storage.get_settings()
        self._queue_limit = self._max_queue_size(settings)
        await self._global_limiter.resize(self._max_concurrency(settings))
        await self._ui_limiter.resize(self._max_ui_concurrency(settings))
        await self.resources.reload(
            settings,
            api_pool_size=self._api_pool_size(settings),
            browser_pool_size=self._browser_pool_size(settings),
        )

    async def run_check(self, check_id: int, trigger: str = "scheduled") -> dict[str, Any]:
        check = storage.get_check(check_id)
        if not check:
            raise ValueError("任务不存在")
        return await self._submit(check, trigger)

    async def run_draft(self, check: dict[str, Any], trigger: str = "draft") -> dict[str, Any]:
        draft = dict(check)
        draft["id"] = 0
        return await self._submit(draft, trigger, record_status=False, notify=False)

    async def inspect_ui(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .ui_assertions import inspect_ui_page

        settings = storage.get_settings()
        ctx = RunContext(
            {
                "id": 0,
                "name": "页面扫描",
                "type": "ui",
                "entry_url": payload.get("entry_url") or "",
                "timeout_ms": payload.get("timeout_ms") or settings.get("default_ui_timeout_ms", 15000),
                "viewport_mode": payload.get("viewport_mode") or "web",
                "setup_script": payload.get("setup_script") or "",
                "method": "",
                "headers_json": "{}",
                "body": "",
                "viewport_width": payload.get("viewport_width"),
                "viewport_height": payload.get("viewport_height"),
            },
            0,
            settings,
            self.artifacts,
            resources=self.resources,
        )
        setup_func = None
        try:
            setup_script = str(payload.get("setup_script") or "")
            if setup_script.strip():
                setup_func = self._load_check_function(
                    setup_script,
                    ctx,
                    function_name="setup",
                    expected_signature="async def setup(ctx, page)",
                    script_label="前置脚本",
                )
            async with self._ui_limiter.slot():
                return await inspect_ui_page(payload, settings, ctx=ctx, setup_func=setup_func)
        finally:
            await ctx.close(False)

    async def inspect_ui_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .ui_assertions import inspect_ui_rule_selectors

        settings = storage.get_settings()
        ctx = RunContext(
            {
                "id": 0,
                "name": "规则检测",
                "type": "ui",
                "entry_url": payload.get("entry_url") or "",
                "timeout_ms": payload.get("timeout_ms") or settings.get("default_ui_timeout_ms", 15000),
                "viewport_mode": payload.get("viewport_mode") or "web",
                "setup_script": payload.get("setup_script") or "",
                "method": "",
                "headers_json": "{}",
                "body": "",
                "viewport_width": payload.get("viewport_width"),
                "viewport_height": payload.get("viewport_height"),
            },
            0,
            settings,
            self.artifacts,
            resources=self.resources,
        )
        setup_func = None
        try:
            setup_script = str(payload.get("setup_script") or "")
            if setup_script.strip():
                setup_func = self._load_check_function(
                    setup_script,
                    ctx,
                    function_name="setup",
                    expected_signature="async def setup(ctx, page)",
                    script_label="前置脚本",
                )
            async with self._ui_limiter.slot():
                return await inspect_ui_rule_selectors(payload, settings, ctx=ctx, setup_func=setup_func)
        finally:
            await ctx.close(False)

    def runtime_status(self) -> dict[str, Any]:
        global_slots = self._global_limiter.snapshot()
        ui_slots = self._ui_limiter.snapshot()
        return {
            "queue": {
                "queued": self._queued_jobs,
                "limit": self._queue_limit,
                "available": max(0, self._queue_limit - self._queued_jobs),
            },
            "workers": {
                "running": self._running_jobs,
                "limit": global_slots["limit"],
                "available": global_slots["available"],
            },
            "browser": {
                "running": ui_slots["in_use"],
                "limit": ui_slots["limit"],
                "available": ui_slots["available"],
            },
            "pools": self.resources.snapshot(),
            "active_checks": len(self._active_checks),
            "closing": self._closing,
        }

    async def _submit(
        self,
        check: dict[str, Any],
        trigger: str,
        record_status: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        check_id = int(check.get("id") or 0)
        async with self._lock:
            self._jobs = {job for job in self._jobs if not job.done()}
            if self._closing:
                return self._create_skipped_run(check, "执行器正在关闭，本次已跳过", trigger, record_status=record_status)
            if check_id > 0 and check_id in self._active_checks:
                return self._create_skipped_run(check, "同一任务上一次执行尚未结束或仍在排队，本次已跳过", trigger, record_status=record_status)
            if self._queued_jobs >= self._queue_limit:
                return self._create_skipped_run(check, "执行队列已满，本次已跳过", trigger, record_status=record_status)

            settings = storage.get_settings()
            metadata = run_metadata(trigger)
            run = storage.create_run(self._with_runner_metadata(check, settings, failure_kind="none", trigger=trigger), "pending")
            job = RunJob(
                check=check,
                trigger=trigger,
                run_id=int(run["id"]),
                record_status=record_status and bool(metadata["affects_health"]),
                notify=notify and bool(metadata["affects_health"]),
                future=loop.create_future(),
            )
            self._queued_jobs += 1
            if check_id > 0:
                self._active_checks.add(check_id)
            task = loop.create_task(self._run_job(job))
            task.add_done_callback(self._jobs.discard)
            self._jobs.add(task)

        return await asyncio.shield(job.future)

    async def _run_job(self, job: RunJob) -> None:
        result: dict[str, Any] | None = None
        try:
            if self._uses_browser(job.check):
                async with self._ui_limiter.slot():
                    async with self._global_limiter.slot():
                        result = await self._start_and_execute(job)
            else:
                async with self._global_limiter.slot():
                    result = await self._start_and_execute(job)
        except asyncio.CancelledError:
            result = self._finish_cancelled_job(job)
        except Exception as exc:
            result = self._finish_internal_error(job, exc)
        finally:
            await self._complete_job(job, result)

    async def _start_and_execute(self, job: RunJob) -> dict[str, Any]:
        async with self._lock:
            job.started = True
            self._queued_jobs = max(0, self._queued_jobs - 1)
            self._running_jobs += 1
        storage.start_run(job.run_id)
        return await self._execute(job.check, job.trigger, job.run_id, job.record_status, job.notify)

    async def _complete_job(self, job: RunJob, result: dict[str, Any] | None) -> None:
        check_id = int(job.check.get("id") or 0)
        async with self._lock:
            if job.started:
                self._running_jobs = max(0, self._running_jobs - 1)
            else:
                self._queued_jobs = max(0, self._queued_jobs - 1)
            if check_id > 0:
                self._active_checks.discard(check_id)
        if result is None:
            result = storage.get_run(job.run_id) or {}
        if not job.future.done():
            job.future.set_result(result)

    async def _execute(
        self,
        check: dict[str, Any],
        trigger: str,
        run_id: int,
        record_status: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        settings = storage.get_settings()
        ctx: RunContext | None = None
        started = datetime.now().astimezone()
        status = "ok"
        error_message: str | None = None
        error_stack: str | None = None
        failure_kind = "none"
        log_lines: list[str] = []
        max_attempts = self._max_attempts(check, settings)

        for attempt in range(1, max_attempts + 1):
            ctx = None
            retrying = False
            try:
                ctx = RunContext(check, run_id, settings, self.artifacts, resources=self.resources)
                ctx.log(f"触发方式：{trigger}")
                ctx.log(f"任务入口：{check.get('entry_url')}")
                if max_attempts > 1:
                    ctx.log(f"执行尝试：{attempt}/{max_attempts}")
                await self._run_check_attempt(ctx, check, settings)
                status = "ok"
                error_message = None
                error_stack = None
                failure_kind = "none"
            except asyncio.CancelledError:
                status = "skipped"
                error_message = "执行被取消，可能是服务关闭或运行设置刷新"
                error_stack = None
                failure_kind = "runner"
            except asyncio.TimeoutError as exc:
                status = "timeout"
                error_message = str(exc).strip() or f"执行超过超时限制：{check.get('timeout_ms')}ms"
                error_stack = traceback.format_exc()
                failure_kind = "target"
            except RunnerEnvironmentFailure as exc:
                status = "failed"
                error_message = str(exc)
                error_stack = traceback.format_exc()
                failure_kind = "runner"
            except RunFailure as exc:
                status = "failed"
                error_message = str(exc)
                error_stack = traceback.format_exc()
                failure_kind = "target"
            except AssertionError as exc:
                status = "failed"
                error_message = str(exc) or "断言失败"
                error_stack = traceback.format_exc()
                failure_kind = "target"
            except Exception as exc:
                status = "failed"
                error_message = str(exc) or exc.__class__.__name__
                error_stack = traceback.format_exc()
                failure_kind = "runner"
            finally:
                failed = status in {"failed", "timeout"}
                retrying = failed and failure_kind == "target" and attempt < max_attempts
                if ctx is not None:
                    if retrying and error_message:
                        ctx.log(f"本次尝试失败，立即重试：{error_message}")
                    try:
                        await ctx.close(failed and not retrying)
                    except Exception as exc:
                        if status == "ok":
                            status = "failed"
                            error_message = f"运行清理失败：{exc}"
                            error_stack = traceback.format_exc()
                            failure_kind = "runner"
                            retrying = False
                        else:
                            ctx.log(f"运行清理失败：{exc}")
                    log_lines.extend(ctx.logs)

            if retrying:
                continue
            break

        finished = datetime.now().astimezone()
        duration_ms = int((finished - started).total_seconds() * 1000)
        safe_error_message = mask_text(error_message, settings) if error_message is not None else None
        safe_error_stack = mask_text(error_stack, settings) if error_stack is not None else None
        safe_logs = mask_text("\n".join(log_lines), settings)
        safe_request_snapshot = mask_data(ctx.request_snapshot, settings) if ctx and ctx.request_snapshot else None
        safe_response_snapshot = mask_data(ctx.response_snapshot, settings) if ctx and ctx.response_snapshot else None
        finished_run = storage.finish_run(
            run_id,
            {
                "status": status,
                "finished_at": finished.isoformat(timespec="seconds"),
                "duration_ms": duration_ms,
                "error_message": safe_error_message,
                "error_stack": safe_error_stack,
                "logs": safe_logs,
                "screenshot_path": ctx.screenshot_path if ctx else None,
                "trace_path": ctx.trace_path if ctx else None,
                "response_path": ctx.response_path if ctx else None,
                "request_snapshot": json.dumps(safe_request_snapshot, ensure_ascii=False)
                if safe_request_snapshot
                else None,
                "response_snapshot": json.dumps(safe_response_snapshot, ensure_ascii=False)
                if safe_response_snapshot
                else None,
                **self._runner_metadata(settings, ctx=ctx, failure_kind=failure_kind),
            },
        )
        if finished_run is None:
            raise RuntimeError("运行记录更新失败")

        if not record_status:
            storage.update_run_notification(run_id, "not_required", channel=None, error=None, sent_at=None)
            return storage.get_run(run_id) or finished_run

        transition = storage.update_check_status(int(check["id"]), finished_run)
        transition["trigger"] = trigger
        if notify:
            await notifier.maybe_notify(check, finished_run, transition)
        return storage.get_run(run_id) or finished_run

    async def _run_check_attempt(self, ctx: RunContext, check: dict[str, Any], settings: dict[str, Any]) -> None:
        max_runtime_seconds = int(settings.get("max_task_runtime_seconds", 60))
        timeout_seconds = min(
            int(check.get("timeout_ms") or 15000) / 1000,
            max_runtime_seconds,
        )
        uses_structured_api = self._uses_structured_api_check(check)
        uses_structured_ui = self._uses_structured_ui_check(check)
        if uses_structured_api:
            await run_structured_api_check(ctx)
        elif uses_structured_ui:
            setup_func = None
            setup_script = str(check.get("setup_script") or "")
            if setup_script.strip():
                setup_func = self._load_check_function(
                    setup_script,
                    ctx,
                    function_name="setup",
                    expected_signature="async def setup(ctx, page)",
                    script_label="前置脚本",
                )
            await run_structured_ui_check(ctx, setup_func=setup_func)
        else:
            check_func = self._load_check_function(check.get("script") or "", ctx)
            await asyncio.wait_for(check_func(ctx), timeout=timeout_seconds)

    @staticmethod
    def _max_attempts(check: dict[str, Any], settings: dict[str, Any]) -> int:
        check_type = str(check.get("type") or "")
        if check_type == "ui":
            retries = settings.get("ui_retry_attempts", 1)
        elif check_type == "api":
            retries = settings.get("api_retry_attempts", 1)
        else:
            retries = 0
        return 1 + max(0, min(3, int(retries or 0)))

    def _create_skipped_run(self, check: dict[str, Any], message: str, trigger: str, record_status: bool = True) -> dict[str, Any]:
        settings = storage.get_settings()
        metadata = run_metadata(trigger)
        run = storage.create_run(self._with_runner_metadata(check, settings, failure_kind="runner", trigger=trigger), "skipped", message)
        if not record_status or not metadata["affects_health"]:
            storage.update_run_notification(int(run["id"]), "not_required", channel=None, error=None, sent_at=None)
            return storage.get_run(int(run["id"])) or run
        if run.get("affects_health"):
            storage.update_check_status(int(check["id"]), run)
        return run

    def _finish_cancelled_job(self, job: RunJob) -> dict[str, Any]:
        return self._finish_without_context(job, "skipped", "执行被取消，可能是服务关闭或运行设置刷新")

    def _finish_internal_error(self, job: RunJob, exc: Exception) -> dict[str, Any]:
        message = str(exc) or exc.__class__.__name__
        return self._finish_without_context(job, "failed", f"执行器内部错误：{message}", traceback.format_exc())

    def _finish_without_context(
        self,
        job: RunJob,
        status: str,
        message: str,
        error_stack: str | None = None,
    ) -> dict[str, Any]:
        settings = storage.get_settings()
        safe_message = mask_text(message, settings)
        safe_error_stack = mask_text(error_stack, settings) if error_stack is not None else None
        finished = datetime.now().astimezone()
        run = storage.finish_run(
            job.run_id,
            {
                "status": status,
                "finished_at": finished.isoformat(timespec="seconds"),
                "duration_ms": 0,
                "error_message": safe_message,
                "error_stack": safe_error_stack,
                "logs": safe_message,
                "screenshot_path": None,
                "trace_path": None,
                "response_path": None,
                "request_snapshot": None,
                "response_snapshot": None,
                **self._runner_metadata(settings, failure_kind="runner"),
            },
        )
        storage.update_run_notification(job.run_id, "not_required", channel=None, error=None, sent_at=None)
        final_run = storage.get_run(job.run_id) or run or {"id": job.run_id, "status": status, "error_message": safe_message}
        if job.record_status and final_run.get("affects_health") and int(job.check.get("id") or 0) > 0:
            storage.update_check_status(int(job.check["id"]), final_run)
        return final_run

    @staticmethod
    def _runner_metadata(settings: dict[str, Any], ctx: RunContext | None = None, failure_kind: str = "none") -> dict[str, str]:
        name = str(settings.get("local_runner_name") or "local").strip() or "local"
        address = str(settings.get("local_runner_address") or "127.0.0.1").strip()
        region = str(settings.get("local_runner_region") or "local").strip() or "local"
        browser_version = str(getattr(ctx, "browser_version", None) or "").strip()
        normalized_failure_kind = failure_kind if failure_kind in {"none", "target", "runner"} else "runner"
        return {
            "runner_name": name,
            "runner_address": address,
            "runner_region": region,
            "runner_browser_version": browser_version,
            "failure_kind": normalized_failure_kind,
        }

    def _with_runner_metadata(
        self,
        check: dict[str, Any],
        settings: dict[str, Any],
        failure_kind: str = "none",
        trigger: str = "manual",
    ) -> dict[str, Any]:
        return {
            **check,
            "_runner": self._runner_metadata(settings, failure_kind=failure_kind),
            "_run": run_metadata(trigger),
        }

    @staticmethod
    def _uses_browser(check: dict[str, Any]) -> bool:
        return check.get("type") == "ui"

    @staticmethod
    def _uses_structured_api_check(check: dict[str, Any]) -> bool:
        return check.get("type") == "api" and has_enabled_api_assertions(check.get("assertions_json"))

    @staticmethod
    def _uses_structured_ui_check(check: dict[str, Any]) -> bool:
        return check.get("type") == "ui" and has_enabled_ui_assertions(check.get("assertions_json"))

    def _load_check_function(
        self,
        script: str,
        ctx: RunContext,
        function_name: str = "check",
        expected_signature: str = "async def check(ctx)",
        script_label: str = "脚本",
    ) -> Any:
        builtins = {
            "AssertionError": AssertionError,
            "Exception": Exception,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "bool": bool,
            "dict": dict,
            "float": float,
            "int": int,
            "isinstance": isinstance,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "range": range,
            "set": set,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "print": lambda *args, **_: ctx.log(" ".join(str(arg) for arg in args)),
        }
        safe_globals = {
            "__builtins__": MappingProxyType(builtins),
            "asyncio": asyncio,
            "json": json,
            "re": re,
        }
        namespace: dict[str, Any] = {}
        exec(compile(script, "<pulseguard-check>", "exec"), safe_globals, namespace)
        check_func = namespace.get(function_name)
        if check_func is None or not inspect.iscoroutinefunction(check_func):
            raise RunFailure(f"{script_label}必须定义 {expected_signature}")
        self._validate_function_signature(check_func, ctx, function_name, expected_signature, script_label)
        return check_func

    @staticmethod
    def _validate_function_signature(func: Any, ctx: RunContext, function_name: str, expected_signature: str, script_label: str) -> None:
        args = (ctx, None) if function_name == "setup" else (ctx,)
        try:
            inspect.signature(func).bind(*args)
        except TypeError as exc:
            raise RunFailure(f"{script_label}必须定义 {expected_signature}") from exc

    @staticmethod
    def _max_concurrency(settings: dict[str, Any] | None = None) -> int:
        try:
            resolved_settings = settings or storage.get_settings()
            return max(1, int(resolved_settings.get("max_concurrency", 2)))
        except Exception:
            return 2

    @staticmethod
    def _max_ui_concurrency(settings: dict[str, Any] | None = None) -> int:
        try:
            resolved_settings = settings or storage.get_settings()
            return max(1, int(resolved_settings.get("max_ui_concurrency", 1)))
        except Exception:
            return 1

    @staticmethod
    def _max_queue_size(settings: dict[str, Any] | None = None) -> int:
        try:
            resolved_settings = settings or storage.get_settings()
            return max(1, int(resolved_settings.get("max_queue_size", 50)))
        except Exception:
            return 50

    @staticmethod
    def _api_pool_size(settings: dict[str, Any] | None = None) -> int:
        try:
            resolved_settings = settings or storage.get_settings()
            return max(1, int(resolved_settings.get("api_pool_size", 5)))
        except Exception:
            return 5

    @staticmethod
    def _browser_pool_size(settings: dict[str, Any] | None = None) -> int:
        try:
            resolved_settings = settings or storage.get_settings()
            return max(1, int(resolved_settings.get("browser_pool_size", 5)))
        except Exception:
            return 5
