from __future__ import annotations

import asyncio
import inspect
import json
import re
import traceback
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .api_assertions import has_enabled_api_assertions, run_structured_api_check
from .ui_assertions import has_enabled_ui_assertions, run_structured_ui_check
from . import notifier, storage
from .artifacts import ArtifactStore
from .context import RunContext, RunFailure


class CheckRunner:
    def __init__(self) -> None:
        self.artifacts = ArtifactStore()
        self._running_checks: set[int] = set()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self._max_concurrency())

    def reload_settings(self) -> None:
        self._semaphore = asyncio.Semaphore(self._max_concurrency())

    async def run_check(self, check_id: int, trigger: str = "manual") -> dict[str, Any]:
        check = storage.get_check(check_id)
        if not check:
            raise ValueError("任务不存在")

        async with self._lock:
            if check_id in self._running_checks:
                return storage.create_run(check, "skipped", "同一任务上一次执行尚未结束，本次已跳过")
            self._running_checks.add(check_id)

        try:
            async with self._semaphore:
                return await self._execute(check, trigger)
        finally:
            async with self._lock:
                self._running_checks.discard(check_id)

    async def run_draft(self, check: dict[str, Any], trigger: str = "draft") -> dict[str, Any]:
        draft = dict(check)
        draft["id"] = 0
        async with self._semaphore:
            return await self._execute(draft, trigger, record_status=False, notify=False)

    async def _execute(
        self,
        check: dict[str, Any],
        trigger: str,
        record_status: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        run = storage.create_run(check, "running")
        run_id = int(run["id"])
        settings = storage.get_settings()
        ctx = RunContext(check, run_id, settings, self.artifacts)
        started = datetime.now().astimezone()
        status = "ok"
        error_message: str | None = None
        error_stack: str | None = None

        ctx.log(f"触发方式：{trigger}")
        ctx.log(f"任务入口：{check.get('entry_url')}")

        try:
            max_runtime_seconds = int(settings.get("max_task_runtime_seconds", 60))
            timeout_seconds = min(
                int(check.get("timeout_ms") or 15000) / 1000,
                max_runtime_seconds,
            )
            uses_structured_api = self._uses_structured_api_check(check)
            uses_structured_ui = self._uses_structured_ui_check(check)
            structured_timeout_seconds = min(timeout_seconds + 2, max_runtime_seconds)
            if uses_structured_api:
                await asyncio.wait_for(run_structured_api_check(ctx), timeout=structured_timeout_seconds)
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
                await asyncio.wait_for(run_structured_ui_check(ctx, setup_func=setup_func), timeout=structured_timeout_seconds)
            else:
                check_func = self._load_check_function(check.get("script") or "", ctx)
                await asyncio.wait_for(check_func(ctx), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            status = "timeout"
            error_message = str(exc).strip() or f"执行超过超时限制：{check.get('timeout_ms')}ms"
            error_stack = traceback.format_exc()
        except RunFailure as exc:
            status = "failed"
            error_message = str(exc)
            error_stack = traceback.format_exc()
        except AssertionError as exc:
            status = "failed"
            error_message = str(exc) or "断言失败"
            error_stack = traceback.format_exc()
        except Exception as exc:
            status = "failed"
            error_message = str(exc) or exc.__class__.__name__
            error_stack = traceback.format_exc()
        finally:
            failed = status in {"failed", "timeout"}
            try:
                await ctx.close(failed)
            except Exception as exc:
                if status == "ok":
                    status = "failed"
                    error_message = f"运行清理失败：{exc}"
                    error_stack = traceback.format_exc()
                else:
                    ctx.log(f"运行清理失败：{exc}")

        finished = datetime.now().astimezone()
        duration_ms = int((finished - started).total_seconds() * 1000)
        finished_run = storage.finish_run(
            run_id,
            {
                "status": status,
                "finished_at": finished.isoformat(timespec="seconds"),
                "duration_ms": duration_ms,
                "error_message": error_message,
                "error_stack": error_stack,
                "logs": "\n".join(ctx.logs),
                "screenshot_path": ctx.screenshot_path,
                "trace_path": ctx.trace_path,
                "response_path": ctx.response_path,
                "request_snapshot": json.dumps(ctx.request_snapshot, ensure_ascii=False)
                if ctx.request_snapshot
                else None,
                "response_snapshot": json.dumps(ctx.response_snapshot, ensure_ascii=False)
                if ctx.response_snapshot
                else None,
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
    def _max_concurrency() -> int:
        try:
            return max(1, int(storage.get_settings().get("max_concurrency", 2)))
        except Exception:
            return 2
