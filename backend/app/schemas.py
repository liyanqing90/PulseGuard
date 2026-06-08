from __future__ import annotations

import json
import re
from typing import Any
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .api_assertions import has_enabled_api_assertions, normalize_api_assertions
from .ui_assertions import has_enabled_ui_assertions, normalize_ui_assertions
from .variables import VARIABLE_NAME_PATTERN


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
    alert_policy_json: str | None = "{}"

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

    @field_validator("alert_policy_json")
    @classmethod
    def alert_policy_must_be_json_object(cls, value: str | None) -> str:
        if not value or not value.strip():
            return "{}"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("告警策略必须是合法 JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("告警策略必须是 JSON Object")
        return json.dumps(_alert_policy(parsed), ensure_ascii=False)

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


class CheckBatchRequest(BaseModel):
    action: Literal["enable", "disable", "run", "update_interval"]
    type: CheckType
    tag: str | None = Field(default="", max_length=80)
    expected_count: int | None = Field(default=None, ge=0, le=10000)
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)

    @field_validator("tag")
    @classmethod
    def normalize_tag(cls, value: str | None) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def validate_action_payload(self) -> "CheckBatchRequest":
        if self.action == "update_interval" and self.interval_seconds is None:
            raise ValueError("批量调整频率必须提供执行频率")
        return self


class SettingsUpdate(BaseModel):
    values: dict[str, object]


class ConfigImportRequest(BaseModel):
    bundle: dict[str, Any]
    replace_existing: bool = False


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
    setup_script: str | None = ""

    @field_validator("setup_script")
    @classmethod
    def setup_script_must_define_entry(cls, value: str | None) -> str:
        return CheckBase.setup_script_must_define_entry(value)


class UiInspectRulesRequest(UiInspectRequest):
    assertions_json: str | None = "[]"

    @field_validator("assertions_json")
    @classmethod
    def assertions_must_be_json_array(cls, value: str | None) -> str:
        return CheckBase.assertions_must_be_json_array(value)


SETTING_RANGES: dict[str, tuple[int, int]] = {
    "default_interval_seconds": (5, 86400),
    "default_ui_timeout_ms": (500, 300000),
    "default_api_timeout_ms": (500, 300000),
    "max_concurrency": (1, 20),
    "max_ui_concurrency": (1, 5),
    "max_queue_size": (1, 1000),
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
    "max_ui_concurrency": "最大 UI 并发数",
    "max_queue_size": "执行队列容量",
    "max_task_runtime_seconds": "单任务最大运行时长",
    "alert_cooldown_minutes": "告警冷却时间",
    "alert_detail_base_url": "告警详情链接前缀",
    "run_retention_days": "执行历史保留",
    "screenshot_retention_days": "截图保留",
    "trace_retention_days": "Trace 保留",
    "response_retention_days": "Response Body 保留",
    "alerts_enabled": "启用告警",
    "notification_channels": "通知渠道",
    "alert_tag_policies": "标签告警策略",
    "alert_policy_json": "任务告警策略",
    "alert_policy_tag": "标签告警策略标签",
    "alert_policy_enabled": "标签告警策略启用状态",
    "environment_variables": "环境变量",
    "environment_variable_name": "环境变量名称",
    "environment_variable_value": "环境变量值",
    "environment_variable_secret": "环境变量密钥标记",
    "recovery_notification": "恢复通知",
    "browser_headless": "Headless",
    "webhook_type": "通知渠道类型",
    "browser_type": "浏览器类型",
    "webhook_url": "Webhook URL",
    "browser_proxy": "浏览器代理",
    "browser_viewport": "浏览器 Viewport",
    "read_only_token": "只读访问令牌",
    "local_runner_name": "本机 Runner 名称",
    "local_runner_address": "本机 Runner 地址",
    "local_runner_region": "本机 Runner 网络区域",
    "maintenance_enabled": "维护公告启用状态",
    "maintenance_title": "维护公告标题",
    "maintenance_message": "维护公告内容",
    "maintenance_starts_at": "维护开始时间",
    "maintenance_ends_at": "维护结束时间",
    "dingtalk_secret": "钉钉加签密钥",
    "channel_enabled": "通知渠道启用状态",
}

BOOLEAN_SETTINGS = {
    "alerts_enabled",
    "recovery_notification",
    "browser_headless",
    "maintenance_enabled",
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
        elif key == "alert_tag_policies":
            normalized[key] = _alert_tag_policies(value)
        elif key == "environment_variables":
            normalized[key] = _environment_variables(value)
        elif key == "alert_detail_base_url":
            normalized[key] = _absolute_http_url(key, value)
        elif key == "browser_type":
            normalized[key] = _enum(key, value, BROWSER_TYPES)
        elif key == "browser_proxy":
            normalized[key] = _string(key, value, max_length=2048)
        elif key == "read_only_token":
            normalized[key] = _string(key, value, max_length=256)
        elif key in {"local_runner_name", "local_runner_address", "local_runner_region"}:
            normalized[key] = _string(key, value, max_length=120)
        elif key in {"maintenance_title", "maintenance_starts_at", "maintenance_ends_at"}:
            normalized[key] = _string(key, value, max_length=200)
        elif key == "maintenance_message":
            normalized[key] = _string(key, value, max_length=2000)
        elif key == "browser_viewport":
            viewport = _string(key, value, max_length=32).lower().replace(" ", "")
            if not VIEWPORT_PATTERN.fullmatch(viewport):
                raise ValueError("浏览器 Viewport 必须使用 1440x900 这类格式")
            normalized[key] = viewport
    return normalized


class RunnerHeartbeatRequest(BaseModel):
    runner_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=2048)
    network_region: str = Field(default="local", max_length=120)
    browser_version: str = Field(default="", max_length=120)
    status: Literal["ok", "warning", "offline"] = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    if text and not text.startswith("SEC") and not _is_variable_placeholder(text):
        raise ValueError("钉钉加签密钥必须以 SEC 开头")
    return text


def _is_variable_placeholder(value: str) -> bool:
    return value.startswith("${") and value.endswith("}") and VARIABLE_NAME_PATTERN.fullmatch(value[2:-1]) is not None


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


def _alert_tag_policies(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("标签告警策略必须是列表")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_tags: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 个标签告警策略格式不正确")

        policy_id = _string("alert_tag_policies", raw.get("id") or f"tag-policy-{index}", max_length=80)
        if policy_id in seen_ids:
            raise ValueError("标签告警策略 ID 不能重复")
        seen_ids.add(policy_id)

        tag = _string("alert_policy_tag", raw.get("tag") or "", max_length=80)
        if not tag:
            raise ValueError("标签告警策略标签不能为空")
        if "," in tag:
            raise ValueError("标签告警策略标签不能包含逗号")
        normalized_tag = tag.lower()
        if normalized_tag in seen_tags:
            raise ValueError("标签告警策略标签不能重复")
        seen_tags.add(normalized_tag)

        policy = _alert_policy(raw)
        policy.update(
            {
                "id": policy_id,
                "name": _string("alert_tag_policies", raw.get("name") or "", max_length=80),
                "tag": tag,
                "enabled": _coerce_bool("alert_policy_enabled", raw.get("enabled", True)),
            }
        )
        normalized.append(policy)
    return normalized


def _alert_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("告警策略必须是 JSON Object")

    policy: dict[str, Any] = {}
    if "alert_cooldown_minutes" in value and value.get("alert_cooldown_minutes") not in {None, ""}:
        policy["alert_cooldown_minutes"] = _bounded_int("alert_cooldown_minutes", value.get("alert_cooldown_minutes"), 1, 1440)
    if "recovery_notification" in value and value.get("recovery_notification") is not None:
        policy["recovery_notification"] = _coerce_bool("recovery_notification", value.get("recovery_notification"))
    if "notification_channel_ids" in value and value.get("notification_channel_ids") is not None:
        channel_ids = _string_list("notification_channels", value.get("notification_channel_ids"), max_length=80)
        policy["notification_channel_ids"] = channel_ids
    return policy


def _string_list(key: str, value: Any, max_length: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{_setting_label(key)}必须是列表")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _string(key, item, max_length=max_length)
        if not text:
            continue
        if text in seen:
            raise ValueError(f"{_setting_label(key)}不能重复")
        seen.add(text)
        result.append(text)
    return result


def _environment_variables(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("环境变量必须是列表")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 个环境变量格式不正确")

        variable_id = _string("environment_variables", raw.get("id") or f"variable-{index}", max_length=80)
        if variable_id in seen_ids:
            raise ValueError("环境变量 ID 不能重复")
        seen_ids.add(variable_id)

        name = _string("environment_variable_name", raw.get("name") or "", max_length=80)
        if not name:
            raise ValueError("环境变量名称不能为空")
        if not VARIABLE_NAME_PATTERN.fullmatch(name):
            raise ValueError("环境变量名称必须使用 NAME 或 SERVICE_TOKEN 这类格式")
        if name in seen_names:
            raise ValueError("环境变量名称不能重复")
        seen_names.add(name)

        normalized.append(
            {
                "id": variable_id,
                "name": name,
                "value": _string("environment_variable_value", raw.get("value") or "", max_length=4096),
                "secret": _coerce_bool("environment_variable_secret", raw.get("secret", False)),
            }
        )
    return normalized


def _setting_label(key: str) -> str:
    return SETTING_LABELS.get(key, key)
