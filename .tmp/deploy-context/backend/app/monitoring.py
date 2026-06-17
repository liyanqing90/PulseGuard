from __future__ import annotations

from typing import Any


HEALTH_STATES = {
    "healthy",
    "suspected_failing",
    "failing",
    "suspected_recovery",
    "unknown",
    "stale",
    "disabled",
}


def run_metadata(trigger: str) -> dict[str, Any]:
    normalized = str(trigger or "manual").strip() or "manual"
    if normalized.startswith("draft"):
        observation_kind = "draft"
    else:
        observation_kind = "observation"
    return {
        "trigger": normalized,
        "observation_kind": observation_kind,
        "affects_health": observation_kind == "observation",
    }


def next_health_state(
    previous: dict[str, Any] | None,
    run: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    previous = previous or {}
    previous_state = str(previous.get("monitor_status") or "unknown")
    previous_failures = int(previous.get("consecutive_failures") or 0)
    previous_successes = int(previous.get("consecutive_successes") or 0)
    status = str(run.get("status") or "")
    failure_kind = str(run.get("failure_kind") or "none")
    trigger = str(run.get("trigger") or "")
    check_type = str(run.get("check_type") or previous.get("check_type") or "")

    failures = previous_failures
    successes = previous_successes
    state = previous_state

    if status == "skipped" or failure_kind == "runner":
        state = "unknown"
        failures = 0
        successes = 0
    elif status in {"failed", "timeout"}:
        failures += 1
        successes = 0
        threshold = _failure_confirmation_count(settings, check_type)
        state = "failing" if failures >= threshold else "suspected_failing"
    elif status == "ok":
        successes += 1
        failures = 0
        if previous_state in {"failing", "suspected_recovery"}:
            threshold = 1 if trigger == "confirm-recovery" else max(1, int(settings.get("recovery_confirmation_count", 2)))
            state = "healthy" if successes >= threshold else "suspected_recovery"
        else:
            state = "healthy"

    return {
        "previous_status": previous_state,
        "current_status": state,
        "previous_consecutive_failures": previous_failures,
        "consecutive_failures": failures,
        "consecutive_successes": successes,
        "last_notified_at": previous.get("last_notified_at"),
    }


def _failure_confirmation_count(settings: dict[str, Any], check_type: str) -> int:
    if check_type == "ui":
        return max(1, int(settings.get("ui_failure_confirmation_count", 3)))
    if check_type == "api":
        return max(1, int(settings.get("api_failure_confirmation_count", 2)))
    return 2
