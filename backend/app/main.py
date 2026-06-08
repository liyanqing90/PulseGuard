from __future__ import annotations

import asyncio
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .api_assertions import inspect_api_response
from . import config_transfer, notifier, run_comparison, storage
from .defaults import DEFAULT_SETTINGS
from .config import REPORTS_DIR, RESPONSES_DIR, SCREENSHOTS_DIR, STATIC_DIR, TRACES_DIR, ensure_runtime_dirs
from .runner import CheckRunner
from .scheduler import PulseScheduler
from .schemas import ApiInspectRequest, CheckBatchRequest, CheckCreate, CheckUpdate, ConfigImportRequest, NOTIFICATION_STATUSES, RunnerHeartbeatRequest, SettingsUpdate, UiInspectRequest, UiInspectRulesRequest
from .variables import mask_data, mask_text


HEARTBEAT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")

VALIDATION_FIELD_LABELS = {
    "name": "任务名称",
    "action": "批量操作",
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
    "tag": "标签",
    "tags": "标签",
    "expected_count": "命中数量",
    "alert_policy_json": "任务告警策略",
    "values": "设置",
    "notification_channels": "通知渠道",
    "alert_tag_policies": "标签告警策略",
    "alert_policy_tag": "标签告警策略标签",
    "environment_variables": "环境变量",
    "environment_variable_name": "环境变量名称",
    "environment_variable_value": "环境变量值",
    "environment_variable_secret": "环境变量密钥标记",
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
    "runner_id": "Runner ID",
    "address": "Runner 地址",
    "network_region": "Runner 网络区域",
    "browser_version": "Runner 浏览器版本",
    "metadata": "Runner 元数据",
    "maintenance_enabled": "维护公告启用状态",
    "maintenance_title": "维护公告标题",
    "maintenance_message": "维护公告内容",
    "maintenance_starts_at": "维护开始时间",
    "maintenance_ends_at": "维护结束时间",
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


@app.post("/api/heartbeats/{key}")
async def record_heartbeat(key: str, request: Request) -> dict[str, Any]:
    heartbeat_key = _normalize_heartbeat_key(key)
    settings = storage.get_settings()
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="心跳内容必须是 JSON Object")
    status = str(raw.get("status") or "ok").strip().lower()
    if status not in {"ok", "failed"}:
        raise HTTPException(status_code=400, detail="心跳状态必须是 ok 或 failed")
    message = mask_text(str(raw.get("message") or "").strip(), settings)[:500]
    payload = mask_data(raw.get("payload") if isinstance(raw.get("payload"), dict) else {}, settings)
    heartbeat = storage.record_heartbeat(heartbeat_key, status=status, message=message, payload=payload)
    return {"ok": True, "heartbeat": mask_data(heartbeat, settings)}


@app.get("/api/heartbeats/{key}")
def heartbeat_detail(key: str) -> dict[str, Any]:
    heartbeat_key = _normalize_heartbeat_key(key)
    heartbeat = storage.get_heartbeat(heartbeat_key)
    if not heartbeat:
        raise HTTPException(status_code=404, detail="心跳不存在")
    return mask_data(heartbeat, storage.get_settings())


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return storage.get_overview()


@app.get("/api/runtime")
def runtime_status(request: Request) -> dict[str, Any]:
    return request.app.state.runner.runtime_status()


@app.get("/api/runners")
def runners(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return mask_data(storage.list_probe_runners(limit=limit), storage.get_settings())


@app.post("/api/runners/heartbeat")
def runner_heartbeat(payload: RunnerHeartbeatRequest) -> dict[str, Any]:
    runner = storage.upsert_probe_runner(payload.model_dump())
    return {"ok": True, "runner": mask_data(runner, storage.get_settings())}


@app.get("/api/status-page")
def status_page() -> dict[str, Any]:
    return _status_page_payload()


@app.get("/api/read-only/snapshot")
def read_only_snapshot(
    token: str = Query(default=""),
    x_pulseguard_read_only_token: str = Header(default=""),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    _verify_read_only_token(_read_only_token_value(token, x_pulseguard_read_only_token, authorization))
    settings = storage.get_settings()
    return {
        "overview": _read_only_overview_payload(storage.get_overview(), settings),
        "checks": [_read_only_check_payload(check, settings) for check in storage.list_checks()],
        "recent_runs": [_read_only_run_payload(run, settings) for run in storage.list_runs(limit=100)],
    }


@app.get("/api/metrics.json")
def metrics_json() -> dict[str, Any]:
    return _metrics_payload()


@app.get("/api/metrics")
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(_prometheus_metrics(_metrics_payload()), media_type="text/plain; version=0.0.4")


@app.get("/api/checks")
def checks(type: str | None = Query(default=None)) -> list[dict[str, Any]]:
    if type and type not in {"ui", "api"}:
        raise HTTPException(status_code=400, detail="任务类型无效")
    return storage.list_checks(type)


@app.get("/api/audit-events")
def audit_events(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return mask_data(storage.list_audit_events(limit=limit), storage.get_settings())


@app.get("/api/run-archives")
def run_archives(limit: int = Query(default=90, ge=1, le=365)) -> list[dict[str, Any]]:
    return storage.list_run_archives(limit=limit)


@app.post("/api/checks")
def create_check(payload: CheckCreate, request: Request) -> dict[str, Any]:
    check = storage.create_check(payload.model_dump())
    storage.record_check_version(check, "created")
    storage.record_audit_event("created", "check", check["id"], check["name"], "创建任务", {"type": check["type"]})
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


@app.post("/api/checks/batch")
async def batch_checks(payload: CheckBatchRequest, request: Request) -> dict[str, Any]:
    checks_to_apply = storage.select_checks_for_batch(payload.type, payload.tag, enabled_only=payload.action == "run")
    ids = [int(check["id"]) for check in checks_to_apply]
    if payload.expected_count is not None and payload.expected_count != len(ids):
        raise HTTPException(status_code=409, detail=f"命中数量已变化：当前 {len(ids)} 条，请刷新后重试")

    if payload.action == "run":
        runs = await asyncio.gather(
            *[
                request.app.state.runner.run_check(check_id, trigger="manual-batch")
                for check_id in ids
            ]
        )
        return {"matched": len(ids), "changed": 0, "ids": ids, "runs": runs}

    if payload.action == "enable":
        changed = storage.batch_set_check_enabled(ids, True)
    elif payload.action == "disable":
        changed = storage.batch_set_check_enabled(ids, False)
    else:
        changed = storage.batch_update_check_interval(ids, int(payload.interval_seconds or 300))

    for check_id in ids:
        request.app.state.scheduler.sync_check(check_id)
    storage.record_audit_event(
        payload.action,
        "check_batch",
        entity_name=payload.type,
        summary="批量操作任务",
        payload={"type": payload.type, "tag": payload.tag, "matched": len(ids), "changed": changed, "ids": ids},
    )
    return {"matched": len(ids), "changed": changed, "ids": ids, "runs": []}


@app.post("/api/checks/debug")
async def debug_check(payload: CheckCreate, request: Request) -> dict[str, Any]:
    return await request.app.state.runner.run_draft(payload.model_dump(), trigger="draft-debug")


@app.post("/api/checks/inspect-api")
async def inspect_api_check(payload: ApiInspectRequest) -> dict[str, Any]:
    settings = storage.get_settings()
    try:
        return await inspect_api_response(payload.model_dump(), settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=mask_text(str(exc), settings)) from exc
    except httpx.HTTPError as exc:
        message = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=400, detail=mask_text(f"接口请求失败：{message}", settings)) from exc


@app.post("/api/checks/inspect-ui")
async def inspect_ui_check(payload: UiInspectRequest, request: Request) -> dict[str, Any]:
    settings = storage.get_settings()
    try:
        return await request.app.state.runner.inspect_ui(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=mask_text(str(exc), settings)) from exc
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=400, detail=mask_text(f"页面扫描失败：{message}", settings)) from exc


@app.post("/api/checks/inspect-ui-rules")
async def inspect_ui_rules(payload: UiInspectRulesRequest, request: Request) -> dict[str, Any]:
    settings = storage.get_settings()
    try:
        return await request.app.state.runner.inspect_ui_rules(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=mask_text(str(exc), settings)) from exc
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=400, detail=mask_text(f"规则检测失败：{message}", settings)) from exc


@app.get("/api/checks/{check_id}")
def check_detail(check_id: int) -> dict[str, Any]:
    check = storage.get_check(check_id)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    return check


@app.get("/api/checks/{check_id}/versions")
def check_versions(check_id: int, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    if not storage.get_check(check_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return mask_data(storage.list_check_versions(check_id, limit=limit), storage.get_settings())


@app.post("/api/check-versions/{version_id}/restore")
def restore_check_version(version_id: int, request: Request) -> dict[str, Any]:
    version = storage.get_check_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="任务版本不存在")
    snapshot = dict(version["snapshot"])
    payload = CheckCreate.model_validate(snapshot).model_dump()
    check_id = int(version["check_id"])
    current = storage.get_check(check_id)
    if current:
        storage.record_check_version(current, "restored-from")
        restored = storage.update_check(check_id, payload)
    else:
        restored = storage.create_check(payload)
        check_id = int(restored["id"])
    if not restored:
        raise HTTPException(status_code=404, detail="任务不存在")
    storage.record_audit_event("restored", "check", check_id, restored["name"], "恢复任务版本", {"version_id": version_id})
    request.app.state.scheduler.sync_check(check_id)
    return restored


@app.put("/api/checks/{check_id}")
def update_check(check_id: int, payload: CheckUpdate, request: Request) -> dict[str, Any]:
    previous = storage.get_check(check_id)
    check = storage.update_check(check_id, payload.model_dump())
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    if previous:
        storage.record_check_version(previous, "updated")
    storage.record_audit_event("updated", "check", check_id, check["name"], "更新任务", {"type": check["type"]})
    request.app.state.scheduler.sync_check(check_id)
    return check


@app.delete("/api/checks/{check_id}")
def delete_check(check_id: int, request: Request) -> dict[str, bool]:
    previous = storage.get_check(check_id)
    removed = storage.delete_check(check_id)
    if not removed:
        raise HTTPException(status_code=404, detail="任务不存在")
    if previous:
        storage.record_check_version(previous, "deleted")
        storage.record_audit_event("deleted", "check", check_id, previous["name"], "删除任务", {"type": previous["type"]})
    request.app.state.scheduler.sync_check(check_id)
    return {"ok": True}


@app.post("/api/checks/{check_id}/enable")
def enable_check(check_id: int, request: Request) -> dict[str, Any]:
    check = storage.set_check_enabled(check_id, True)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    storage.record_audit_event("enabled", "check", check_id, check["name"], "启用任务", {"type": check["type"]})
    request.app.state.scheduler.sync_check(check_id)
    return check


@app.post("/api/checks/{check_id}/disable")
def disable_check(check_id: int, request: Request) -> dict[str, Any]:
    check = storage.set_check_enabled(check_id, False)
    if not check:
        raise HTTPException(status_code=404, detail="任务不存在")
    storage.record_audit_event("disabled", "check", check_id, check["name"], "禁用任务", {"type": check["type"]})
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


@app.get("/api/runs/{run_id}/failure-summary")
def run_failure_summary(run_id: int) -> dict[str, Any]:
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return _run_failure_summary_payload(run)


@app.get("/api/runs/{run_id}/compare-success")
def run_success_comparison(run_id: int) -> dict[str, Any]:
    try:
        return run_comparison.compare_with_previous_success(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    storage.record_audit_event("updated", "settings", summary="更新系统设置", payload={"fields": sorted(payload.values)})
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


@app.get("/api/config/export")
def export_config(redact: bool = Query(default=True)) -> dict[str, Any]:
    return config_transfer.export_config(redact=redact)


@app.post("/api/config/import-preview")
def import_config_preview(payload: ConfigImportRequest) -> dict[str, Any]:
    return config_transfer.preview_import(payload.bundle)


@app.post("/api/config/import")
async def import_config(payload: ConfigImportRequest, request: Request) -> dict[str, Any]:
    try:
        result = config_transfer.apply_import(payload.bundle, replace_existing=payload.replace_existing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await request.app.state.runner.reload_settings()
    storage.record_audit_event("imported", "config", summary="导入配置", payload=result)
    return result


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


def _verify_read_only_token(token: str) -> None:
    expected = str(storage.get_settings().get("read_only_token") or "")
    if not expected:
        raise HTTPException(status_code=403, detail="只读访问令牌未配置")
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="只读访问令牌无效")


def _read_only_token_value(query_token: str, header_token: str, authorization: str) -> str:
    auth_value = authorization.strip()
    if auth_value.lower().startswith("bearer "):
        return auth_value[7:].strip()
    return (header_token or query_token).strip()


def _read_only_overview_payload(overview: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "ui_count": int(overview.get("ui_count") or 0),
        "api_count": int(overview.get("api_count") or 0),
        "failing_count": int(overview.get("failing_count") or 0),
        "today_runs": int(overview.get("today_runs") or 0),
        "latest_run": _read_only_run_payload(overview.get("latest_run"), settings) if overview.get("latest_run") else None,
        "latest_recovered": mask_data(overview.get("latest_recovered"), settings) if overview.get("latest_recovered") else None,
        "recent_failures": [
            _read_only_run_payload(run, settings)
            for run in overview.get("recent_failures") or []
            if isinstance(run, dict)
        ],
        "trends": overview.get("trends") if isinstance(overview.get("trends"), list) else [],
    }


def _read_only_check_payload(check: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    status = str(check.get("current_status") or ("disabled" if not check.get("enabled") else "never"))
    return {
        "id": check.get("id"),
        "name": mask_text(str(check.get("name") or ""), settings),
        "type": check.get("type"),
        "enabled": bool(check.get("enabled")),
        "tags": mask_text(str(check.get("tags") or ""), settings),
        "entry_url": mask_text(str(check.get("entry_url") or ""), settings),
        "method": check.get("method") or "",
        "interval_seconds": check.get("interval_seconds"),
        "timeout_ms": check.get("timeout_ms"),
        "status": status,
        "last_run_at": check.get("last_run_at"),
        "last_error": _public_failure_summary(status),
    }


def _read_only_run_payload(run: dict[str, Any] | None, settings: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(run, dict):
        return None
    status = str(run.get("status") or "")
    failure_kind = str(run.get("failure_kind") or "none")
    return {
        "id": run.get("id"),
        "check_id": run.get("check_id"),
        "check_name": mask_text(str(run.get("check_name") or ""), settings),
        "check_type": run.get("check_type"),
        "status": status,
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "duration_ms": run.get("duration_ms"),
        "consecutive_failures": int(run.get("consecutive_failures") or 0),
        "failure_kind": failure_kind,
        "runner_name": mask_text(str(run.get("runner_name") or ""), settings),
        "runner_region": mask_text(str(run.get("runner_region") or ""), settings),
        "error_message": _public_failure_summary(status, failure_kind),
    }


def _status_page_payload() -> dict[str, Any]:
    settings = storage.get_settings()
    overview = storage.get_overview()
    checks = [_status_check_payload(check, settings) for check in storage.list_checks()]
    incidents = [
        _status_incident_payload(run, settings)
        for run in storage.list_runs(limit=100)
        if run.get("status") in {"failed", "timeout"}
    ][:20]
    return {
        "generated_at": storage.now_iso(),
        "summary": {
            "checks_total": len(checks),
            "checks_enabled": sum(1 for check in checks if check["enabled"]),
            "checks_failing": int(overview.get("failing_count") or 0),
            "runs_today": int(overview.get("today_runs") or 0),
        },
        "maintenance": {
            "enabled": bool(settings.get("maintenance_enabled")),
            "title": mask_text(str(settings.get("maintenance_title") or ""), settings),
            "message": mask_text(str(settings.get("maintenance_message") or ""), settings),
            "starts_at": str(settings.get("maintenance_starts_at") or ""),
            "ends_at": str(settings.get("maintenance_ends_at") or ""),
        },
        "checks": checks,
        "recent_incidents": incidents,
    }


def _status_check_payload(check: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    status = str(check.get("current_status") or ("disabled" if not check.get("enabled") else "never"))
    return {
        "id": check.get("id"),
        "name": mask_text(str(check.get("name") or ""), settings),
        "type": check.get("type"),
        "enabled": bool(check.get("enabled")),
        "tags": mask_text(str(check.get("tags") or ""), settings),
        "status": status,
        "last_run_at": check.get("last_run_at"),
        "last_error": _public_failure_summary(status),
    }


def _status_incident_payload(run: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    status = str(run.get("status") or "")
    failure_kind = str(run.get("failure_kind") or "none")
    return {
        "id": run.get("id"),
        "check_id": run.get("check_id"),
        "check_name": mask_text(str(run.get("check_name") or ""), settings),
        "check_type": run.get("check_type"),
        "status": status,
        "started_at": run.get("started_at"),
        "duration_ms": run.get("duration_ms"),
        "failure_kind": failure_kind,
        "error_message": _public_failure_summary(status, failure_kind),
    }


def _public_failure_summary(status: str, failure_kind: str = "") -> str:
    if status == "timeout":
        return "最近运行超时"
    if failure_kind == "runner":
        return "Runner 执行异常"
    if status == "failed":
        return "最近运行失败"
    if status == "skipped":
        return "本次运行已跳过"
    return ""


def _run_failure_summary_payload(run: dict[str, Any]) -> dict[str, Any]:
    settings = storage.get_settings()
    status = str(run.get("status") or "")
    failure_kind = str(run.get("failure_kind") or "none")
    error_message = mask_text(str(run.get("error_message") or ""), settings)[:1000]
    if status not in {"failed", "timeout", "skipped"}:
        summary = "本次运行未记录失败，暂无需要处理的失败摘要。"
        next_steps = ["如需复盘，可查看运行日志、请求/响应快照和最近成功对比。"]
    elif failure_kind == "runner":
        summary = "本次异常更可能来自 Runner 执行环境或调度过程。"
        next_steps = [
            "检查 Runner 是否在线、队列是否已满、浏览器或依赖是否可用。",
            "查看运行日志中的清理、取消、浏览器启动或内部执行错误。",
            "确认本机 Runner 名称、地址和网络区域配置是否符合当前部署。"
        ]
    else:
        summary = "本次异常更可能来自被探测目标、响应内容或断言规则。"
        next_steps = [
            "先确认目标服务、页面或接口在对应网络区域是否可达。",
            "查看错误摘要和断言结果，判断是状态码、内容、选择器还是超时问题。",
            "如最近成功基线可用，优先对比 URL、标题、状态码和关键断言差异。"
        ]
    signals = [
        {"label": "运行状态", "value": status or "-"},
        {"label": "失败归因", "value": failure_kind},
        {"label": "Runner", "value": " · ".join(str(run.get(key) or "") for key in ("runner_name", "runner_region")).strip(" · ") or "-"},
        {"label": "耗时", "value": run.get("duration_ms")},
    ]
    return {
        "run_id": run.get("id"),
        "check_id": run.get("check_id"),
        "check_name": run.get("check_name"),
        "status": status,
        "failure_kind": failure_kind,
        "summary": summary,
        "error_message": error_message,
        "signals": signals,
        "next_steps": next_steps,
    }


def _metrics_payload() -> dict[str, Any]:
    overview = storage.get_overview()
    checks = storage.list_checks()
    runs_24h = next((item for item in overview.get("trends", []) if item.get("key") == "24h"), {})
    return {
        "checks_total": len(checks),
        "checks_enabled": sum(1 for check in checks if check.get("enabled")),
        "checks_disabled": sum(1 for check in checks if not check.get("enabled")),
        "checks_failing": int(overview.get("failing_count") or 0),
        "runs_today": int(overview.get("today_runs") or 0),
        "runs_24h": int(runs_24h.get("runs") or 0),
        "failures_24h": int(runs_24h.get("failure_count") or 0),
        "success_rate_24h": runs_24h.get("success_rate"),
    }


def _prometheus_metrics(metrics: dict[str, Any]) -> str:
    lines = [
        "# HELP pulseguard_checks_total Total configured checks.",
        "# TYPE pulseguard_checks_total gauge",
        f"pulseguard_checks_total {metrics['checks_total']}",
        "# HELP pulseguard_checks_enabled Enabled configured checks.",
        "# TYPE pulseguard_checks_enabled gauge",
        f"pulseguard_checks_enabled {metrics['checks_enabled']}",
        "# HELP pulseguard_checks_failing Enabled checks currently failing.",
        "# TYPE pulseguard_checks_failing gauge",
        f"pulseguard_checks_failing {metrics['checks_failing']}",
        "# HELP pulseguard_runs_today Runs started since local midnight.",
        "# TYPE pulseguard_runs_today counter",
        f"pulseguard_runs_today {metrics['runs_today']}",
        "# HELP pulseguard_failures_24h Failed or timed out runs in the last 24 hours.",
        "# TYPE pulseguard_failures_24h gauge",
        f"pulseguard_failures_24h {metrics['failures_24h']}",
    ]
    if metrics.get("success_rate_24h") is not None:
        lines.extend(
            [
                "# HELP pulseguard_success_rate_24h Success rate percentage in the last 24 hours.",
                "# TYPE pulseguard_success_rate_24h gauge",
                f"pulseguard_success_rate_24h {metrics['success_rate_24h']}",
            ]
        )
    return "\n".join(lines) + "\n"


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


def _normalize_heartbeat_key(key: str) -> str:
    heartbeat_key = key.strip()
    if not HEARTBEAT_KEY_PATTERN.fullmatch(heartbeat_key):
        raise HTTPException(status_code=400, detail="心跳 key 只能包含字母、数字、点、冒号、下划线或短横线，长度不超过 120")
    return heartbeat_key


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
