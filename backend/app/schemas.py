from __future__ import annotations

import json
import re
from typing import Any
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .api_assertions import has_enabled_api_assertions, normalize_api_assertions
from .ui_assertions import has_enabled_ui_assertions, normalize_ui_assertions


CheckType = Literal["ui", "api"]
RunStatus = Literal["pending", "running", "ok", "failed", "timeout", "skipped"]
NotificationStatus = Literal["disabled", "not_required", "suppressed", "sent", "failed"]
NOTIFICATION_STATUSES = {"disabled", "not_required", "suppressed", "sent", "failed"}


class CheckBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: CheckType
    enabled: bool = True
    interval_seconds: int = Field(default=300, ge=5, le=86400)
    timeout_ms: int = Field(default=15000, ge=500, le=300000)
    entry_url: str = Field(min_length=1, max_length=2048)
    viewport_mode: Literal["web", "h5"] = "web"
    method: str | None = None
    headers_json: str | None = "{}"
    body: str | None = ""
    assertions_json: str | None = "[]"
    setup_script: str | None = ""
    script: str | None = ""
    tags: str | None = ""

    @field_validator("script")
    @classmethod
    def script_must_define_entry(cls, value: str | None) -> str:
        text = value or ""
        if text and "async def check" not in text:
            raise ValueError("脚本必须定义 async def check(ctx)")
        return text

    @field_validator("setup_script")
    @classmethod
    def setup_script_must_define_entry(cls, value: str | None) -> str:
        text = value or ""
        if text and "async def setup" not in text:
            raise ValueError("前置脚本必须定义 async def setup(ctx, page)")
        return text

    @field_validator("headers_json")
    @classmethod
    def headers_must_be_json_object(cls, value: str | None) -> str:
        if not value or not value.strip():
            return "{}"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Headers 必须是合法 JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Headers 必须是 JSON Object")
        return json.dumps(parsed, ensure_ascii=False)

    @field_validator("assertions_json")
    @classmethod
    def assertions_must_be_json_array(cls, value: str | None) -> str:
        if not value or not value.strip():
            return "[]"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("校验项必须是合法 JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError("校验项必须是 JSON Array")
        return json.dumps(parsed, ensure_ascii=False)

    @model_validator(mode="after")
    def normalize_method(self) -> "CheckBase":
        if self.type == "api":
            self.method = (self.method or "GET").upper()
            self.viewport_mode = "web"
            self.setup_script = ""
            self.assertions_json = json.dumps(normalize_api_assertions(self.assertions_json), ensure_ascii=False)
            if not has_enabled_api_assertions(self.assertions_json) and not (self.script or "").strip():
                raise ValueError("接口任务请至少添加一个校验项，或填写高级脚本")
        else:
            self.method = ""
            self.setup_script = self.setup_script or ""
            self.headers_json = "{}"
            self.body = ""
            self.assertions_json = json.dumps(normalize_ui_assertions(self.assertions_json), ensure_ascii=False)
            if not has_enabled_ui_assertions(self.assertions_json) and "async def check" not in (self.script or ""):
                raise ValueError("UI 任务请至少添加一个校验项，或填写高级脚本 async def check(ctx)")
        return self


class CheckCreate(CheckBase):
    pass


class CheckUpdate(CheckBase):
    pass


class SettingsUpdate(BaseModel):
    values: dict[str, object]


class ApiInspectRequest(BaseModel):
    type: Literal["api"] = "api"
    entry_url: str = Field(min_length=1, max_length=2048)
    method: str | None = "GET"
    headers_json: str | None = "{}"
    body: str | None = ""
    timeout_ms: int = Field(default=10000, ge=500, le=300000)

    @field_validator("headers_json")
    @classmethod
    def headers_must_be_json_object(cls, value: str | None) -> str:
        return CheckBase.headers_must_be_json_object(value)

    @model_validator(mode="after")
    def normalize_method(self) -> "ApiInspectRequest":
        self.method = (self.method or "GET").upper()
        return self


class UiInspectRequest(BaseModel):
    type: Literal["ui"] = "ui"
    entry_url: str = Field(min_length=1, max_length=2048)
    timeout_ms: int = Field(default=15000, ge=500, le=300000)
    viewport_mode: Literal["web", "h5"] = "web"
    viewport_width: int | None = Field(default=None, ge=240, le=3840)
    viewport_height: int | None = Field(default=None, ge=320, le=4096)


SETTING_RANGES: dict[str, tuple[int, int]] = {
    "default_interval_seconds": (5, 86400),
    "default_ui_timeout_ms": (500, 300000),
    "default_api_timeout_ms": (500, 300000),
    "max_concurrency": (1, 20),
    "max_task_runtime_seconds": (1, 600),
    "alert_cooldown_minutes": (1, 1440),
    "run_retention_days": (1, 365),
    "screenshot_retention_days": (1, 365),
    "trace_retention_days": (1, 365),
    "response_retention_days": (1, 365),
}

SETTING_LABELS = {
    "default_interval_seconds": "默认执行频率",
    "default_ui_timeout_ms": "默认 UI 超时",
    "default_api_timeout_ms": "默认 API 超时",
    "max_concurrency": "最大并发任务数",
    "max_task_runtime_seconds": "单任务最大运行时长",
    "alert_cooldown_minutes": "告警冷却时间",
    "alert_detail_base_url": "告警详情链接前缀",
    "run_retention_days": "执行历史保留",
    "screenshot_retention_days": "截图保留",
    "trace_retention_days": "Trace 保留",
    "response_retention_days": "Response Body 保留",
    "alerts_enabled": "启用告警",
    "notification_channels": "通知渠道",
    "recovery_notification": "恢复通知",
    "browser_headless": "Headless",
    "webhook_type": "通知渠道类型",
    "browser_type": "浏览器类型",
    "webhook_url": "Webhook URL",
    "browser_proxy": "浏览器代理",
    "browser_viewport": "浏览器 Viewport",
    "dingtalk_secret": "钉钉加签密钥",
    "channel_enabled": "通知渠道启用状态",
}

BOOLEAN_SETTINGS = {
    "alerts_enabled",
    "recovery_notification",
    "browser_headless",
}

WEBHOOK_TYPES = {"feishu", "wecom", "dingtalk"}
BROWSER_TYPES = {"chromium", "firefox", "webkit"}
VIEWPORT_PATTERN = re.compile(r"^[1-9]\d{2,4}x[1-9]\d{2,4}$")


def normalize_settings_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if key in SETTING_RANGES:
            normalized[key] = _bounded_int(key, value, *SETTING_RANGES[key])
        elif key in BOOLEAN_SETTINGS:
            normalized[key] = _coerce_bool(key, value)
        elif key == "notification_channels":
            normalized[key] = _notification_channels(value)
        elif key == "alert_detail_base_url":
            normalized[key] = _absolute_http_url(key, value)
        elif key == "browser_type":
            normalized[key] = _enum(key, value, BROWSER_TYPES)
        elif key == "browser_proxy":
            normalized[key] = _string(key, value, max_length=2048)
        elif key == "browser_viewport":
            viewport = _string(key, value, max_length=32).lower().replace(" ", "")
            if not VIEWPORT_PATTERN.fullmatch(viewport):
                raise ValueError("浏览器 Viewport 必须使用 1440x900 这类格式")
            normalized[key] = viewport
    return normalized


def _bounded_int(key: str, value: Any, minimum: int, maximum: int) -> int:
    label = _setting_label(key)
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是数字")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return number


def _coerce_bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{_setting_label(key)}必须是布尔值")


def _enum(key: str, value: Any, allowed: set[str]) -> str:
    text = _string(key, value, max_length=32)
    if text not in allowed:
        raise ValueError(f"{_setting_label(key)}不支持：{text}")
    return text


def _string(key: str, value: Any, max_length: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{_setting_label(key)}必须是字符串")
    text = value.strip()
    if len(text) > max_length:
        raise ValueError(f"{_setting_label(key)} 过长")
    return text


def _absolute_http_url(key: str, value: Any) -> str:
    text = _string(key, value, max_length=2048).rstrip("/")
    if not text:
        raise ValueError(f"{_setting_label(key)}不能为空")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"{_setting_label(key)}必须是完整的 http:// 或 https:// 地址")
    if parts.query or parts.fragment:
        raise ValueError(f"{_setting_label(key)}不能包含查询参数或锚点")
    return text


def _dingtalk_secret(value: Any) -> str:
    text = _string("dingtalk_secret", value, max_length=256)
    if text and not text.startswith("SEC"):
        raise ValueError("钉钉加签密钥必须以 SEC 开头")
    return text


def _notification_channels(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("通知渠道必须是列表")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 个通知渠道格式不正确")
        channel_id = _string("notification_channels", raw.get("id") or f"channel-{index}", max_length=80)
        if channel_id in seen_ids:
            raise ValueError("通知渠道 ID 不能重复")
        seen_ids.add(channel_id)
        channel_type = _enum("webhook_type", raw.get("type") or "feishu", WEBHOOK_TYPES)
        channel = {
            "id": channel_id,
            "name": _string("notification_channels", raw.get("name") or "", max_length=80),
            "type": channel_type,
            "enabled": _coerce_bool("channel_enabled", raw.get("enabled", True)),
            "webhook_url": _string("webhook_url", raw.get("webhook_url") or "", max_length=2048),
            "dingtalk_secret": _dingtalk_secret(raw.get("dingtalk_secret") or ""),
        }
        normalized.append(channel)
    return normalized

def _setting_label(key: str) -> str:
    return SETTING_LABELS.get(key, key)
