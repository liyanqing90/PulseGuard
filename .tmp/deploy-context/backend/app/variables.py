from __future__ import annotations

import os
import re
from typing import Any


VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VARIABLE_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SENSITIVE_NAME_PARTS = ("SECRET", "TOKEN", "PASSWORD", "PASS", "KEY", "AUTH", "COOKIE")
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "access-token",
    "refresh-token",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "read_only_token",
    "dingtalk_secret",
    "webhook_url",
    "browser_proxy",
    "headers_json",
}
MASK = "***"


class VariableResolutionError(ValueError):
    pass


def environment_variables(settings: dict[str, Any]) -> list[dict[str, Any]]:
    values = settings.get("environment_variables") or []
    return [item for item in values if isinstance(item, dict)]


def variable_lookup(settings: dict[str, Any]) -> dict[str, str]:
    lookup = dict(os.environ)
    for item in environment_variables(settings):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        lookup[name] = str(item.get("value") or "")
    return lookup


def resolve_text(value: Any, settings: dict[str, Any]) -> str:
    text = "" if value is None else str(value)
    if "${" not in text:
        return text

    lookup = variable_lookup(settings)
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in lookup:
            missing.add(name)
            return match.group(0)
        return lookup[name]

    resolved = VARIABLE_PLACEHOLDER_PATTERN.sub(replace, text)
    if missing:
        names = ", ".join(sorted(missing))
        raise VariableResolutionError(f"\u672a\u914d\u7f6e\u53d8\u91cf: {names}")
    return resolved


def resolve_data(value: Any, settings: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return resolve_text(value, settings)
    if isinstance(value, list):
        return [resolve_data(item, settings) for item in value]
    if isinstance(value, dict):
        return {key: resolve_data(item, settings) for key, item in value.items()}
    return value


def mask_text(value: Any, settings: dict[str, Any]) -> str:
    text = "" if value is None else str(value)
    for secret in _secret_values(settings):
        text = text.replace(secret, MASK)
    return text


def mask_data(value: Any, settings: dict[str, Any]) -> Any:
    return _mask_data(value, settings)


def is_sensitive_variable_name(name: str) -> bool:
    return _is_sensitive_variable(name, False)


def _secret_values(settings: dict[str, Any]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    lookup = variable_lookup(settings)

    for item in environment_variables(settings):
        name = str(item.get("name") or "")
        raw_value = str(item.get("value") or "")
        if not raw_value or not _is_sensitive_variable(name, bool(item.get("secret", False))):
            continue
        resolved = _resolve_secret_value(raw_value, lookup)
        for candidate in (raw_value, resolved):
            if len(candidate) < 4 or candidate in seen:
                continue
            seen.add(candidate)
            values.append(candidate)

    for channel in settings.get("notification_channels") or []:
        if not isinstance(channel, dict):
            continue
        for key in ("webhook_url", "dingtalk_secret"):
            value = str(channel.get(key) or "")
            if len(value) < 4 or value in seen:
                continue
            resolved = _resolve_secret_value(value, lookup)
            for candidate in (value, resolved):
                if len(candidate) < 4 or candidate in seen:
                    continue
                seen.add(candidate)
                values.append(candidate)

    read_only_token = str(settings.get("read_only_token") or "")
    if len(read_only_token) >= 4 and read_only_token not in seen:
        seen.add(read_only_token)
        values.append(read_only_token)

    for name, value in os.environ.items():
        if not value or not _is_sensitive_variable(name, False):
            continue
        if len(value) < 4 or value in seen:
            continue
        seen.add(value)
        values.append(value)

    values.sort(key=len, reverse=True)
    return values


def _mask_data(value: Any, settings: dict[str, Any], field_name: str = "") -> Any:
    if field_name and _is_sensitive_field_name(field_name):
        return MASK if value not in (None, "") else ""
    if isinstance(value, str):
        return mask_text(value, settings)
    if isinstance(value, list):
        return [_mask_data(item, settings) for item in value]
    if isinstance(value, dict):
        return {key: _mask_data(item, settings, str(key)) for key, item in value.items()}
    return value


def _is_sensitive_field_name(name: str) -> bool:
    normalized = name.strip().lower()
    canonical = normalized.replace("_", "-")
    if normalized in SENSITIVE_FIELD_NAMES or canonical in SENSITIVE_FIELD_NAMES:
        return True
    return normalized.endswith(("_token", "_secret", "_password")) or "api_key" in normalized


def _resolve_secret_value(value: str, lookup: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return lookup.get(match.group(1), match.group(0))

    return VARIABLE_PLACEHOLDER_PATTERN.sub(replace, value)


def _is_sensitive_variable(name: str, explicit_secret: bool) -> bool:
    if explicit_secret:
        return True
    normalized = name.upper()
    return any(part in normalized for part in SENSITIVE_NAME_PARTS)
