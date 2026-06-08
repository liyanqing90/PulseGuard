from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .api_assertions import inspect_api_response
from . import notifier, storage
from .defaults import DEFAULT_SETTINGS
from .config import REPORTS_DIR, RESPONSES_DIR, SCREENSHOTS_DIR, STATIC_DIR, TRACES_DIR, ensure_runtime_dirs
from .runner import CheckRunner
from .scheduler import PulseScheduler
from .schemas import ApiInspectRequest, CheckCreate, CheckUpdate, NOTIFICATION_STATUSES, SettingsUpdate, UiInspectRequest


VALIDATION_FIELD_LABELS = {
    "name": "任务名称",
    "type": "任务类型",
    "enabled": "启用状态",
    "interval_seconds": "执行频率",
    "timeout_ms": "超时时间",
    "entry_url": "目标 URL",
    "viewport_mode": "页面模式",
    "method": "Method",
    "headers_json": "Headers",
    "body": "Body",
    "assertions_json": "校验项",
    "setup_script": "前置脚本",
    "script": "Python 脚本",
    "tags": "标签",
    "values": "设置",
    "notification_channels": "通知渠道",
    "alert_cooldown_minutes": "告警冷却时间",
    "alert_detail_base_url": "告警详情链接前缀",
    "recovery_notification": "恢复通知",
    "max_queue_size": "执行队列容量",
    "max_ui_concurrency": "最大 UI 并发数",
    "viewport_width": "Viewport 宽度",
    "viewport_height": "Viewport 高度",
    "browser_viewport": "浏览器 Viewport",
    "browser_type": "浏览器类型",
    "browser_proxy": "浏览器代理",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    runner = CheckRunner()
    scheduler = PulseScheduler(runner)
    app.state.runner = runner
    app.state.scheduler = scheduler
    await runner.start()
    scheduler.start()
    yield
    scheduler.shutdown()
    await runner.shutdown()


ensure_runtime_dirs()

app = FastAPI(title="PulseGuard", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")
app.mount("/artifacts/traces", StaticFiles(directory=TRACES_DIR), name="traces")
app.mount("/artifacts/responses", StaticFiles(directory=RESPONSES_DIR), name="responses")
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="frontend-assets")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return storage.get_overview()


@app.get("/api/runtime")
def runtime_status(request: Request) -> dict[str, Any]:
    return request.app.state.runner.runtime_status()


@app.get("/api/checks")
def checks(type: str | None = Query(default=None)) -> list[dict[str, Any]]:
    if type and type not in {"ui", "api"}:
        raise HTTPException(status_code=400, detail="任务类型无效")
    return storage.list_checks(type)


@app.post("/api/checks")
def create_check(payload: CheckCreate, request: Request) -> dict[str, Any]:
    check = storage.create_check(payload.model_dump())
    request.app.state.scheduler.sync_check(int(check["id"]))
    return check


@app.post("/api/checks/run-all")
async def run_all_checks(request: Request, type: str | None = Query(default=None)) -> dict[str, Any]:
    if type and type not in {"ui", "api"}:
        raise HTTPException(status_code=400, detail="任务类型无效")
    checks_to_run = [check for check in storage.list_checks(type, enabled_only=True)]
    results = await asyncio.gather(
        *[
            request.app.state.runner.run_check(int(check["id"]), trigger="manual-batch")
            for check in checks_to_run
        ]
    )
    return {"runs": results}


@app.post("/api/checks/debug")
async def debug_check(payload: CheckCreate, request: Request) -> dict[str, Any]:
    return await request.app.state.runner.run_draft(payload.model_dump(), trigger="draft-debug")


@app.post("/api/checks/inspect-api")
async def inspect_api_check(payload: ApiInspectRequest) -> dict[str, Any]:
    try:
        return await inspect_api_response(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        message = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=400, detail=f"接口请求失败：{message}") from exc


@app.post("/api/checks/inspect-ui")
async def inspect_ui_check(payload: UiInspectRequest, request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.runner.inspect_ui(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=400, detail=f"页面扫描失败：{message}") from exc


@app.get("/api/checks/{check_id}")
def check_detail(check_id: int) -> dict[str, Any]:
    check = storage.get_check(check_id)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    return check


@app.put("/api/checks/{check_id}")
def update_check(check_id: int, payload: CheckUpdate, request: Request) -> dict[str, Any]:
    check = storage.update_check(check_id, payload.model_dump())
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    request.app.state.scheduler.sync_check(check_id)
    return check


@app.delete("/api/checks/{check_id}")
def delete_check(check_id: int, request: Request) -> dict[str, bool]:
    removed = storage.delete_check(check_id)
    if not removed:
        raise HTTPException(status_code=404, detail="任务不存在")
    request.app.state.scheduler.sync_check(check_id)
    return {"ok": True}


@app.post("/api/checks/{check_id}/enable")
def enable_check(check_id: int, request: Request) -> dict[str, Any]:
    check = storage.set_check_enabled(check_id, True)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    request.app.state.scheduler.sync_check(check_id)
    return check


@app.post("/api/checks/{check_id}/disable")
def disable_check(check_id: int, request: Request) -> dict[str, Any]:
    check = storage.set_check_enabled(check_id, False)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    request.app.state.scheduler.sync_check(check_id)
    return check


@app.post("/api/checks/{check_id}/run")
async def run_check(check_id: int, request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.runner.run_check(check_id, trigger="manual")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs")
def runs(
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    notification_status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    check_id: int | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    if type and type not in {"ui", "api"}:
        raise HTTPException(status_code=400, detail="任务类型无效")
    if status and status not in {"ok", "failed", "timeout", "skipped", "running", "pending"}:
        raise HTTPException(status_code=400, detail="运行状态无效")
    if notification_status and notification_status not in NOTIFICATION_STATUSES:
        raise HTTPException(status_code=400, detail="告警状态无效")
    return storage.list_runs(
        {
            "check_type": type,
            "status": status,
            "notification_status": notification_status,
            "q": q,
            "check_id": check_id,
            "start": start,
            "end": end,
        },
        limit=limit,
    )


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict[str, Any]:
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/rerun")
async def rerun(run_id: int, request: Request) -> dict[str, Any]:
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if int(run["check_id"]) <= 0:
        raise HTTPException(status_code=400, detail="临时运行记录不能重新执行")
    try:
        return await request.app.state.runner.run_check(int(run["check_id"]), trigger=f"rerun:{run_id}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return storage.get_public_settings()


@app.put("/api/settings")
async def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
    try:
        storage.update_settings(payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await request.app.state.runner.reload_settings()
    request.app.state.scheduler.refresh_all()
    return storage.get_public_settings()


@app.post("/api/settings/test-alert")
async def test_alert(payload: SettingsUpdate) -> dict[str, Any]:
    settings = _settings_with_overrides(payload)
    try:
        await notifier.send_test_alert(settings)
    except notifier.AlertDeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": "测试告警已发送"}


@app.post("/api/settings/alert-preview")
def alert_preview(payload: SettingsUpdate) -> dict[str, Any]:
    return notifier.build_test_alert_preview(_settings_with_overrides(payload))


def _settings_with_overrides(payload: SettingsUpdate) -> dict[str, Any]:
    settings = storage.get_settings()
    unknown = sorted(set(payload.values) - set(DEFAULT_SETTINGS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持的设置项：{', '.join(unknown)}")
    try:
        for key, value in storage.normalize_settings_update_values(payload.values).items():
            if key in DEFAULT_SETTINGS:
                settings[key] = value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return settings


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _format_validation_errors(exc.errors())})


@app.exception_handler(ValidationError)
async def validation_exception_handler(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _format_validation_errors(exc.errors())})


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_operational_error_handler(_: Request, exc: sqlite3.OperationalError) -> JSONResponse:
    message = str(exc).lower()
    if "locked" in message:
        detail = "数据库暂时被占用，请稍后重试"
    elif "unable to open" in message:
        detail = "数据库文件无法打开，请检查数据目录权限"
    else:
        detail = "数据库操作失败"
    return JSONResponse(status_code=503, content={"detail": detail})


@app.get("/")
def frontend_index():
    return _serve_frontend()


@app.get("/{full_path:path}")
def frontend_spa(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("artifacts/"):
        raise HTTPException(status_code=404, detail="资源不存在")
    return _serve_frontend()


def _serve_frontend():
    index = Path(STATIC_DIR) / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "message": "PulseGuard backend is running. Frontend build was not found.",
            "frontend_dist": str(STATIC_DIR),
            "reports_dir": str(REPORTS_DIR),
        }
    )


def _format_validation_errors(errors: list[dict[str, Any]]) -> str:
    messages: list[str] = []
    for error in errors:
        label = _validation_field_label(error.get("loc"))
        text = _validation_error_text(error)
        if label and text.startswith(label):
            messages.append(text)
        elif label and text.startswith(("不能为空", "过长", "过短", "必须", "不能", "格式", "低于", "超过", "选项")):
            messages.append(f"{label}{text}")
        elif label:
            messages.append(f"{label}：{text}")
        else:
            messages.append(text)
    return "；".join(dict.fromkeys(messages)) or "请求参数格式不正确"


def _validation_field_label(loc: Any) -> str:
    if not isinstance(loc, (list, tuple)):
        return ""
    keys = [str(item) for item in loc if str(item) not in {"body", "query", "path"} and not str(item).isdigit()]
    if not keys:
        return ""
    return VALIDATION_FIELD_LABELS.get(keys[-1], "")


def _validation_error_text(error: dict[str, Any]) -> str:
    error_type = str(error.get("type") or "")
    message = str(error.get("msg") or "").removeprefix("Value error, ").strip()

    if error_type == "missing":
        return "不能为空"
    if error_type in {"string_too_short", "too_short"}:
        return "不能为空"
    if error_type in {"string_too_long", "too_long"}:
        return "过长"
    if error_type in {"int_parsing", "int_type", "float_parsing", "float_type"}:
        return "必须是数字"
    if error_type in {"bool_type", "bool_parsing"}:
        return "必须是布尔值"
    if error_type in {"literal_error", "enum"}:
        return "选项无效"
    if error_type in {"greater_than_equal", "greater_than"}:
        return "低于允许范围"
    if error_type in {"less_than_equal", "less_than"}:
        return "超过允许范围"
    return message or "格式不正确"
