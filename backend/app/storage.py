from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from .artifacts import cleanup_old_artifacts
from .config import DB_PATH, ensure_runtime_dirs
from .defaults import DEFAULT_SETTINGS, DEMO_CHECKS
from .schemas import normalize_settings_values
from .variables import is_sensitive_variable_name


_LOCK = threading.RLock()
_TAG_SPLIT_PATTERN = re.compile(r"[,\s]+")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def init_db() -> None:
    ensure_runtime_dirs()
    with _connect() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA busy_timeout=30000;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                interval_seconds INTEGER NOT NULL DEFAULT 300,
                timeout_ms INTEGER NOT NULL DEFAULT 15000,
                entry_url TEXT,
                viewport_mode TEXT NOT NULL DEFAULT 'web',
                method TEXT,
                headers_json TEXT,
                body TEXT,
                assertions_json TEXT,
                setup_script TEXT NOT NULL DEFAULT '',
                script TEXT NOT NULL,
                tags TEXT,
                alert_policy_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                check_name TEXT NOT NULL,
                check_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                error_message TEXT,
                error_stack TEXT,
                logs TEXT,
                screenshot_path TEXT,
                trace_path TEXT,
                response_path TEXT,
                request_snapshot TEXT,
                response_snapshot TEXT,
                runner_name TEXT,
                runner_address TEXT,
                runner_region TEXT,
                runner_browser_version TEXT,
                failure_kind TEXT,
                notification_status TEXT,
                notification_channel TEXT,
                notification_error TEXT,
                notification_sent_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS check_status (
                check_id INTEGER PRIMARY KEY,
                current_status TEXT NOT NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                last_failed_at TEXT,
                last_run_at TEXT,
                last_run_id INTEGER,
                last_error TEXT,
                last_notified_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS heartbeats (
                key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'ok',
                message TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                received_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                entity_name TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS check_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_date TEXT NOT NULL,
                check_type TEXT NOT NULL,
                status TEXT NOT NULL,
                run_count INTEGER NOT NULL DEFAULT 0,
                duration_sum_ms INTEGER NOT NULL DEFAULT 0,
                duration_sample_count INTEGER NOT NULL DEFAULT 0,
                last_run_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(archive_date, check_type, status)
            );

            CREATE TABLE IF NOT EXISTS probe_runners (
                runner_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                network_region TEXT NOT NULL DEFAULT 'local',
                browser_version TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_checks_type ON checks(type);
            CREATE INDEX IF NOT EXISTS idx_runs_check_id ON runs(check_id);
            CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_type_status ON runs(check_type, status);
            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_check_versions_check_id ON check_versions(check_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_run_archives_date ON run_archives(archive_date DESC);
            CREATE INDEX IF NOT EXISTS idx_probe_runners_region ON probe_runners(network_region, status);
            """
        )
        _ensure_check_columns(conn)
        _ensure_run_columns(conn)
        _ensure_default_settings(conn)
        _mark_interrupted_runs(conn)
        _seed_demo_checks(conn)


def list_checks(check_type: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT c.*, s.current_status, s.consecutive_failures, s.last_success_at,
               s.last_failed_at, s.last_run_at, s.last_run_id, s.last_error,
               r.duration_ms AS last_duration_ms
        FROM checks c
        LEFT JOIN check_status s ON s.check_id = c.id
        LEFT JOIN runs r ON r.id = s.last_run_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    if check_type:
        clauses.append("c.type = ?")
        params.append(check_type)
    if enabled_only:
        clauses.append("c.enabled = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY c.updated_at DESC, c.id DESC"
    with _LOCK, _connect() as conn:
        return [_normalize_check(row) for row in conn.execute(sql, params).fetchall()]


def check_tag_set(tags: str | None) -> set[str]:
    return {item.strip().lower() for item in _TAG_SPLIT_PATTERN.split(tags or "") if item.strip()}


def select_checks_for_batch(check_type: str | None = None, tag: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    checks = list_checks(check_type, enabled_only=enabled_only)
    normalized_tag = (tag or "").strip().lower()
    if not normalized_tag:
        return checks
    return [check for check in checks if normalized_tag in check_tag_set(check.get("tags"))]


def get_check(check_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT c.*, s.current_status, s.consecutive_failures, s.last_success_at,
                   s.last_failed_at, s.last_run_at, s.last_run_id, s.last_error,
                   r.duration_ms AS last_duration_ms
            FROM checks c
            LEFT JOIN check_status s ON s.check_id = c.id
            LEFT JOIN runs r ON r.id = s.last_run_id
            WHERE c.id = ?
            """,
            (check_id,),
        ).fetchone()
    return _normalize_check(row) if row else None


def create_check(data: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO checks (
                name, type, enabled, interval_seconds, timeout_ms, entry_url, viewport_mode, method,
                headers_json, body, assertions_json, setup_script, script, tags, alert_policy_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"].strip(),
                data["type"],
                1 if data.get("enabled", True) else 0,
                int(data.get("interval_seconds") or 300),
                int(data.get("timeout_ms") or 15000),
                data.get("entry_url", "").strip(),
                data.get("viewport_mode") or "web",
                (data.get("method") or "").upper(),
                data.get("headers_json") or "{}",
                data.get("body") or "",
                data.get("assertions_json") or "[]",
                data.get("setup_script") or "",
                data.get("script") or "",
                data.get("tags") or "",
                data.get("alert_policy_json") or "{}",
                timestamp,
                timestamp,
            ),
        )
        check_id = int(cursor.lastrowid)
    return get_check(check_id)  # type: ignore[return-value]


def update_check(check_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE checks
            SET name = ?, type = ?, enabled = ?, interval_seconds = ?, timeout_ms = ?,
                entry_url = ?, viewport_mode = ?, method = ?, headers_json = ?, body = ?, assertions_json = ?, setup_script = ?,
                script = ?, tags = ?, alert_policy_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["name"].strip(),
                data["type"],
                1 if data.get("enabled", True) else 0,
                int(data.get("interval_seconds") or 300),
                int(data.get("timeout_ms") or 15000),
                data.get("entry_url", "").strip(),
                data.get("viewport_mode") or "web",
                (data.get("method") or "").upper(),
                data.get("headers_json") or "{}",
                data.get("body") or "",
                data.get("assertions_json") or "[]",
                data.get("setup_script") or "",
                data.get("script") or "",
                data.get("tags") or "",
                data.get("alert_policy_json") or "{}",
                timestamp,
                check_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
    return get_check(check_id)


def delete_check(check_id: int) -> bool:
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM check_status WHERE check_id = ?", (check_id,))
        cursor = conn.execute("DELETE FROM checks WHERE id = ?", (check_id,))
        return cursor.rowcount > 0


def set_check_enabled(check_id: int, enabled: bool) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE checks SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now_iso(), check_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_check(check_id)


def batch_set_check_enabled(check_ids: list[int], enabled: bool) -> int:
    ids = _clean_check_ids(check_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            f"UPDATE checks SET enabled = ?, updated_at = ? WHERE id IN ({placeholders})",
            [1 if enabled else 0, now_iso(), *ids],
        )
        return int(cursor.rowcount)


def batch_update_check_interval(check_ids: list[int], interval_seconds: int) -> int:
    ids = _clean_check_ids(check_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            f"UPDATE checks SET interval_seconds = ?, updated_at = ? WHERE id IN ({placeholders})",
            [int(interval_seconds), now_iso(), *ids],
        )
        return int(cursor.rowcount)


def _clean_check_ids(check_ids: list[int]) -> list[int]:
    cleaned: list[int] = []
    seen: set[int] = set()
    for raw in check_ids:
        check_id = int(raw)
        if check_id <= 0 or check_id in seen:
            continue
        seen.add(check_id)
        cleaned.append(check_id)
    return cleaned


def record_heartbeat(key: str, status: str = "ok", message: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    heartbeat_key = key.strip()
    timestamp = now_iso()
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO heartbeats(key, status, message, payload_json, received_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                status = excluded.status,
                message = excluded.message,
                payload_json = excluded.payload_json,
                received_at = excluded.received_at,
                updated_at = excluded.updated_at
            """,
            (heartbeat_key, status, message, payload_json, timestamp, timestamp),
        )
    return get_heartbeat(heartbeat_key)  # type: ignore[return-value]


def get_heartbeat(key: str) -> dict[str, Any] | None:
    heartbeat_key = key.strip()
    if not heartbeat_key:
        return None
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM heartbeats WHERE key = ?", (heartbeat_key,)).fetchone()
    return _normalize_heartbeat(row) if row else None


def record_audit_event(
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    entity_name: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_events(action, entity_type, entity_id, entity_name, summary, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action,
                entity_type,
                str(entity_id) if entity_id is not None else None,
                entity_name,
                summary,
                json.dumps(payload or {}, ensure_ascii=False),
                timestamp,
            ),
        )
        event_id = int(cursor.lastrowid)
    return get_audit_event(event_id)  # type: ignore[return-value]


def get_audit_event(event_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()
    return _normalize_audit_event(row) if row else None


def list_audit_events(limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    return [_normalize_audit_event(row) for row in rows]


def record_check_version(check: dict[str, Any], action: str) -> dict[str, Any]:
    timestamp = now_iso()
    check_id = int(check["id"])
    snapshot = _check_snapshot(check)
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO check_versions(check_id, action, snapshot_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (check_id, action, json.dumps(snapshot, ensure_ascii=False), timestamp),
        )
        version_id = int(cursor.lastrowid)
    return get_check_version(version_id)  # type: ignore[return-value]


def get_check_version(version_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM check_versions WHERE id = ?", (version_id,)).fetchone()
    return _normalize_check_version(row) if row else None


def list_check_versions(check_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM check_versions
            WHERE check_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (check_id, max(1, min(200, int(limit)))),
        ).fetchall()
    return [_normalize_check_version(row) for row in rows]


def list_run_archives(limit: int = 90) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM run_archives
            ORDER BY archive_date DESC, check_type ASC, status ASC
            LIMIT ?
            """,
            (max(1, min(365, int(limit))),),
        ).fetchall()
    return [_normalize_run_archive(row) for row in rows]


def create_run(check: dict[str, Any], status: str = "running", error_message: str | None = None) -> dict[str, Any]:
    timestamp = now_iso()
    finished_at = timestamp if status == "skipped" else None
    duration_ms = 0 if status == "skipped" else None
    notification_status = "not_required" if status == "skipped" else None
    runner = check.get("_runner") if isinstance(check.get("_runner"), dict) else {}
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                check_id, check_name, check_type, status, started_at, finished_at,
                duration_ms, error_message, error_stack, logs, screenshot_path,
                trace_path, response_path, request_snapshot, response_snapshot,
                runner_name, runner_address, runner_region, runner_browser_version, failure_kind,
                notification_status, notification_channel, notification_error,
                notification_sent_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(check["id"]),
                check["name"],
                check["type"],
                status,
                timestamp,
                finished_at,
                duration_ms,
                error_message,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                runner.get("runner_name"),
                runner.get("runner_address"),
                runner.get("runner_region"),
                runner.get("runner_browser_version"),
                runner.get("failure_kind"),
                notification_status,
                None,
                None,
                None,
                timestamp,
            ),
        )
        run_id = int(cursor.lastrowid)
    return get_run(run_id)  # type: ignore[return-value]


def start_run(run_id: int) -> dict[str, Any] | None:
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE runs
            SET status = 'running',
                started_at = ?,
                finished_at = NULL,
                duration_ms = NULL,
                error_message = NULL
            WHERE id = ? AND status = 'pending'
            """,
            (timestamp, run_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_run(run_id)


def finish_run(run_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, duration_ms = ?, error_message = ?,
                error_stack = ?, logs = ?, screenshot_path = ?, trace_path = ?,
                response_path = ?, request_snapshot = ?, response_snapshot = ?,
                runner_name = ?, runner_address = ?, runner_region = ?,
                runner_browser_version = ?, failure_kind = ?
            WHERE id = ?
            """,
            (
                data["status"],
                data["finished_at"],
                data["duration_ms"],
                data.get("error_message"),
                data.get("error_stack"),
                data.get("logs"),
                data.get("screenshot_path"),
                data.get("trace_path"),
                data.get("response_path"),
                data.get("request_snapshot"),
                data.get("response_snapshot"),
                data.get("runner_name"),
                data.get("runner_address"),
                data.get("runner_region"),
                data.get("runner_browser_version"),
                data.get("failure_kind"),
                run_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
    return get_run(run_id)


def upsert_probe_runner(data: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    runner_id = str(data.get("runner_id") or "").strip()
    if not runner_id:
        raise ValueError("Runner ID 不能为空")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO probe_runners (
                runner_id, name, address, network_region, browser_version,
                status, metadata_json, last_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(runner_id) DO UPDATE SET
                name = excluded.name,
                address = excluded.address,
                network_region = excluded.network_region,
                browser_version = excluded.browser_version,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                last_seen_at = excluded.last_seen_at,
                updated_at = excluded.updated_at
            """,
            (
                runner_id,
                str(data.get("name") or runner_id).strip(),
                str(data.get("address") or "").strip(),
                str(data.get("network_region") or "local").strip(),
                str(data.get("browser_version") or "").strip(),
                str(data.get("status") or "ok").strip(),
                json.dumps(metadata, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
    return get_probe_runner(runner_id)  # type: ignore[return-value]


def get_probe_runner(runner_id: str) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM probe_runners WHERE runner_id = ?", (runner_id,)).fetchone()
    return _normalize_probe_runner(row) if row else None


def list_probe_runners(limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM probe_runners
            ORDER BY last_seen_at DESC, runner_id ASC
            LIMIT ?
            """,
            (max(1, min(500, int(limit))),),
        ).fetchall()
    return [_normalize_probe_runner(row) for row in rows]


def update_run_notification(
    run_id: int,
    status: str,
    channel: str | None = None,
    error: str | None = None,
    sent_at: str | None = None,
) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE runs
            SET notification_status = ?,
                notification_channel = ?,
                notification_error = ?,
                notification_sent_at = ?
            WHERE id = ?
            """,
            (status, channel, error, sent_at, run_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_run(run_id)


def update_check_status(check_id: int, run: dict[str, Any]) -> dict[str, Any]:
    if run["status"] == "skipped":
        return get_status_transition(check_id, "skipped")

    current_status = "ok" if run["status"] == "ok" else "failed"
    timestamp = run.get("finished_at") or now_iso()

    with _LOCK, _connect() as conn:
        previous = conn.execute(
            "SELECT * FROM check_status WHERE check_id = ?",
            (check_id,),
        ).fetchone()
        previous_dict = dict(previous) if previous else None
        previous_failures = int(previous_dict["consecutive_failures"]) if previous_dict else 0
        consecutive_failures = previous_failures + 1 if current_status == "failed" else 0
        last_success_at = timestamp if current_status == "ok" else (previous_dict or {}).get("last_success_at")
        last_failed_at = timestamp if current_status == "failed" else (previous_dict or {}).get("last_failed_at")

        conn.execute(
            """
            INSERT INTO check_status (
                check_id, current_status, consecutive_failures, last_success_at,
                last_failed_at, last_run_at, last_run_id, last_error, last_notified_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(check_id) DO UPDATE SET
                current_status = excluded.current_status,
                consecutive_failures = excluded.consecutive_failures,
                last_success_at = excluded.last_success_at,
                last_failed_at = excluded.last_failed_at,
                last_run_at = excluded.last_run_at,
                last_run_id = excluded.last_run_id,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                check_id,
                current_status,
                consecutive_failures,
                last_success_at,
                last_failed_at,
                timestamp,
                run["id"],
                run.get("error_message"),
                (previous_dict or {}).get("last_notified_at"),
                timestamp,
            ),
        )

    return {
        "previous_status": (previous_dict or {}).get("current_status"),
        "current_status": current_status,
        "previous_consecutive_failures": previous_failures,
        "consecutive_failures": consecutive_failures,
        "last_notified_at": (previous_dict or {}).get("last_notified_at"),
    }


def get_status_transition(check_id: int, current_status: str) -> dict[str, Any]:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM check_status WHERE check_id = ?", (check_id,)).fetchone()
    previous = dict(row) if row else {}
    return {
        "previous_status": previous.get("current_status"),
        "current_status": current_status,
        "previous_consecutive_failures": previous.get("consecutive_failures", 0),
        "consecutive_failures": previous.get("consecutive_failures", 0),
        "last_notified_at": previous.get("last_notified_at"),
    }


def update_last_notified(check_id: int, notified_at: str | None = None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE check_status SET last_notified_at = ?, updated_at = ? WHERE check_id = ?",
            (notified_at or now_iso(), now_iso(), check_id),
        )


def get_run(run_id: int) -> dict[str, Any] | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _normalize_run(row) if row else None


def get_previous_successful_run(run: dict[str, Any]) -> dict[str, Any] | None:
    check_id = int(run.get("check_id") or 0)
    run_id = int(run.get("id") or 0)
    if check_id <= 0 or run_id <= 0:
        return None
    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM runs
            WHERE check_id = ?
              AND status = 'ok'
              AND id < ?
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (check_id, run_id),
        ).fetchone()
    return _normalize_run(row) if row else None


def list_runs(filters: dict[str, Any] | None = None, limit: int = 100) -> list[dict[str, Any]]:
    filters = filters or {}
    clauses: list[str] = []
    params: list[Any] = []

    if filters.get("check_type"):
        clauses.append("check_type = ?")
        params.append(filters["check_type"])
    if filters.get("status"):
        if filters["status"] == "failed":
            clauses.append("status IN ('failed', 'timeout')")
        else:
            clauses.append("status = ?")
            params.append(filters["status"])
    if filters.get("notification_status"):
        clauses.append("notification_status = ?")
        params.append(filters["notification_status"])
    if filters.get("q"):
        clauses.append("check_name LIKE ?")
        params.append(f"%{filters['q']}%")
    if filters.get("check_id"):
        clauses.append("check_id = ?")
        params.append(int(filters["check_id"]))
    if filters.get("start"):
        clauses.append("started_at >= ?")
        params.append(filters["start"])
    if filters.get("end"):
        clauses.append("started_at <= ?")
        params.append(filters["end"])

    sql = "SELECT * FROM runs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
    params.append(limit)

    with _LOCK, _connect() as conn:
        return [_normalize_run(row) for row in conn.execute(sql, params).fetchall()]


def get_settings() -> dict[str, Any]:
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    for row in rows:
        if row["key"] not in DEFAULT_SETTINGS:
            continue
        try:
            settings[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            settings[row["key"]] = row["value"]
    return settings


def get_public_settings() -> dict[str, Any]:
    settings = get_settings()
    settings["read_only_token_set"] = bool(settings.get("read_only_token"))
    settings["read_only_token"] = ""
    settings["notification_channels"] = [
        _public_notification_channel(channel)
        for channel in settings.get("notification_channels", [])
        if isinstance(channel, dict)
    ]
    settings["environment_variables"] = [
        _public_environment_variable(variable)
        for variable in settings.get("environment_variables", [])
        if isinstance(variable, dict)
    ]
    return settings


def update_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_SETTINGS)
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"不支持的设置项：{', '.join(unknown)}")
    normalized_values = normalize_settings_update_values(values)
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        for key, value in normalized_values.items():
            if key not in allowed:
                continue
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), timestamp),
            )
    return get_settings()


def normalize_settings_update_values(values: dict[str, Any]) -> dict[str, Any]:
    values = _preserve_notification_channel_secrets(values)
    values = _preserve_environment_variable_secrets(values)
    return normalize_settings_values(values)


def _public_notification_channel(channel: dict[str, Any]) -> dict[str, Any]:
    public = dict(channel)
    public["dingtalk_secret_set"] = bool(public.get("dingtalk_secret"))
    public["dingtalk_secret"] = ""
    return public


def _public_environment_variable(variable: dict[str, Any]) -> dict[str, Any]:
    public = dict(variable)
    public["value_set"] = bool(public.get("value"))
    if public.get("secret") or is_sensitive_variable_name(str(public.get("name") or "")):
        public["secret"] = True
        public["value"] = ""
    return public


def _preserve_notification_channel_secrets(values: dict[str, Any]) -> dict[str, Any]:
    channels = values.get("notification_channels")
    if not isinstance(channels, list):
        return values

    current_channels = {
        str(channel.get("id")): channel
        for channel in get_settings().get("notification_channels", [])
        if isinstance(channel, dict) and channel.get("id")
    }
    merged_channels: list[Any] = []
    for raw_channel in channels:
        if not isinstance(raw_channel, dict):
            merged_channels.append(raw_channel)
            continue

        channel = dict(raw_channel)
        channel_id = str(channel.get("id") or "")
        has_new_secret = bool(str(channel.get("dingtalk_secret") or "").strip())
        should_clear_secret = bool(channel.pop("dingtalk_secret_clear", False))
        if not has_new_secret and not should_clear_secret and channel_id in current_channels:
            channel["dingtalk_secret"] = current_channels[channel_id].get("dingtalk_secret") or ""
        merged_channels.append(channel)

    next_values = dict(values)
    next_values["notification_channels"] = merged_channels
    return next_values


def _preserve_environment_variable_secrets(values: dict[str, Any]) -> dict[str, Any]:
    variables = values.get("environment_variables")
    if not isinstance(variables, list):
        return values

    current_variables = {
        str(variable.get("id")): variable
        for variable in get_settings().get("environment_variables", [])
        if isinstance(variable, dict) and variable.get("id")
    }
    merged_variables: list[Any] = []
    for raw_variable in variables:
        if not isinstance(raw_variable, dict):
            merged_variables.append(raw_variable)
            continue

        variable = dict(raw_variable)
        variable_id = str(variable.get("id") or "")
        has_new_value = bool(str(variable.get("value") or ""))
        should_clear_value = bool(variable.pop("value_clear", False))
        is_secret = bool(variable.get("secret", False)) or is_sensitive_variable_name(str(variable.get("name") or ""))
        if is_secret and not has_new_value and not should_clear_value and variable_id in current_variables:
            variable["value"] = current_variables[variable_id].get("value") or ""
        merged_variables.append(variable)

    next_values = dict(values)
    next_values["environment_variables"] = merged_variables
    return next_values


def get_overview() -> dict[str, Any]:
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with _LOCK, _connect() as conn:
        ui_count = conn.execute("SELECT COUNT(*) AS count FROM checks WHERE type = 'ui'").fetchone()["count"]
        api_count = conn.execute("SELECT COUNT(*) AS count FROM checks WHERE type = 'api'").fetchone()["count"]
        failing_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM check_status s
            JOIN checks c ON c.id = s.check_id
            WHERE c.enabled = 1 AND s.current_status = 'failed'
            """
        ).fetchone()["count"]
        today_runs = conn.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE check_id > 0 AND started_at >= ?",
            (today,),
        ).fetchone()["count"]
        latest_run = conn.execute(
            "SELECT * FROM runs WHERE check_id > 0 ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        recovered = conn.execute(
            """
            SELECT c.name, c.type, s.last_success_at
            FROM check_status s
            JOIN checks c ON c.id = s.check_id
            WHERE s.last_failed_at IS NOT NULL
              AND s.last_success_at IS NOT NULL
              AND s.last_success_at > s.last_failed_at
            ORDER BY s.last_success_at DESC
            LIMIT 1
            """
        ).fetchone()
        failures = conn.execute(
            """
            SELECT r.*, s.consecutive_failures
            FROM runs r
            LEFT JOIN check_status s ON s.last_run_id = r.id
            WHERE r.status IN ('failed', 'timeout')
              AND r.check_id > 0
            ORDER BY r.started_at DESC, r.id DESC
            LIMIT 8
            """
        ).fetchall()
        trends = _overview_trends(conn)

    return {
        "ui_count": ui_count,
        "api_count": api_count,
        "failing_count": failing_count,
        "today_runs": today_runs,
        "latest_run": _normalize_run(latest_run) if latest_run else None,
        "latest_recovered": dict(recovered) if recovered else None,
        "recent_failures": [_normalize_run(row) for row in failures],
        "trends": trends,
    }


def _overview_trends(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now().astimezone()
    periods = [
        ("24h", "近 24h", now - timedelta(hours=24)),
        ("7d", "近 7d", now - timedelta(days=7)),
    ]
    trends: list[dict[str, Any]] = []
    for key, label, cutoff in periods:
        rows = conn.execute(
            """
            SELECT status, duration_ms
            FROM runs
            WHERE check_id > 0
              AND started_at >= ?
              AND started_at <= ?
              AND status IN ('ok', 'failed', 'timeout')
            """,
            (cutoff.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
        ).fetchall()
        total = len(rows)
        successes = sum(1 for row in rows if row["status"] == "ok")
        failures = sum(1 for row in rows if row["status"] in {"failed", "timeout"})
        durations = sorted(int(row["duration_ms"]) for row in rows if row["duration_ms"] is not None)
        trends.append(
            {
                "key": key,
                "label": label,
                "runs": total,
                "success_rate": round((successes / total) * 100, 1) if total else None,
                "failure_count": failures,
                "duration_p50_ms": _percentile(durations, 0.5),
                "duration_p95_ms": _percentile(durations, 0.95),
            }
        )
    return trends


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(len(values) * percentile + 0.999999) - 1))
    return values[index]


def cleanup_old_data(settings: dict[str, Any] | None = None) -> int:
    settings = settings or get_settings()
    retention_days = int(settings.get("run_retention_days", 30))
    cutoff = (datetime.now().astimezone() - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        _archive_runs_before(conn, cutoff)
        expired_run_ids = [
            int(row["id"])
            for row in conn.execute("SELECT id FROM runs WHERE created_at < ?", (cutoff,)).fetchall()
        ]
        cursor = conn.execute("DELETE FROM runs WHERE created_at < ?", (cutoff,))
        removed_runs = cursor.rowcount
        if expired_run_ids:
            placeholders = ", ".join("?" for _ in expired_run_ids)
            conn.execute(
                f"UPDATE check_status SET last_run_id = NULL WHERE last_run_id IN ({placeholders})",
                expired_run_ids,
            )
    removed_artifacts = cleanup_old_artifacts(settings)
    removed_artifact_count = sum(len(paths) for paths in removed_artifacts.values())
    if removed_artifact_count:
        with _LOCK, _connect() as conn:
            for column, paths in removed_artifacts.items():
                _clear_artifact_paths(conn, column, paths)
    return removed_runs + removed_artifact_count


def _archive_runs_before(conn: sqlite3.Connection, cutoff: str) -> None:
    rows = conn.execute(
        """
        SELECT
            substr(started_at, 1, 10) AS archive_date,
            check_type,
            status,
            COUNT(*) AS run_count,
            COALESCE(SUM(COALESCE(duration_ms, 0)), 0) AS duration_sum_ms,
            SUM(CASE WHEN duration_ms IS NULL THEN 0 ELSE 1 END) AS duration_sample_count,
            MAX(started_at) AS last_run_at
        FROM runs
        WHERE created_at < ?
          AND check_id > 0
          AND status IN ('ok', 'failed', 'timeout', 'skipped')
        GROUP BY archive_date, check_type, status
        """,
        (cutoff,),
    ).fetchall()
    timestamp = now_iso()
    for row in rows:
        conn.execute(
            """
            INSERT INTO run_archives (
                archive_date, check_type, status, run_count, duration_sum_ms,
                duration_sample_count, last_run_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_date, check_type, status) DO UPDATE SET
                run_count = run_archives.run_count + excluded.run_count,
                duration_sum_ms = run_archives.duration_sum_ms + excluded.duration_sum_ms,
                duration_sample_count = run_archives.duration_sample_count + excluded.duration_sample_count,
                last_run_at = CASE
                    WHEN excluded.last_run_at > COALESCE(run_archives.last_run_at, '') THEN excluded.last_run_at
                    ELSE run_archives.last_run_at
                END,
                updated_at = excluded.updated_at
            """,
            (
                row["archive_date"] or "",
                row["check_type"] or "",
                row["status"] or "",
                int(row["run_count"] or 0),
                int(row["duration_sum_ms"] or 0),
                int(row["duration_sample_count"] or 0),
                row["last_run_at"],
                timestamp,
            ),
        )


def _clear_artifact_paths(conn: sqlite3.Connection, column: str, paths: list[str]) -> None:
    if not paths:
        return
    if column not in {"screenshot_path", "trace_path", "response_path"}:
        raise ValueError(f"不支持的产物字段：{column}")
    placeholders = ", ".join("?" for _ in paths)
    conn.execute(f"UPDATE runs SET {column} = NULL WHERE {column} IN ({placeholders})", paths)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_check_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(checks)").fetchall()}
    columns = {
        "assertions_json": "TEXT",
        "viewport_mode": "TEXT NOT NULL DEFAULT 'web'",
        "setup_script": "TEXT NOT NULL DEFAULT ''",
        "alert_policy_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE checks ADD COLUMN {name} {column_type}")


def _ensure_run_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    columns = {
        "request_snapshot": "TEXT",
        "response_snapshot": "TEXT",
        "runner_name": "TEXT",
        "runner_address": "TEXT",
        "runner_region": "TEXT",
        "runner_browser_version": "TEXT",
        "failure_kind": "TEXT",
        "notification_status": "TEXT",
        "notification_channel": "TEXT",
        "notification_error": "TEXT",
        "notification_sent_at": "TEXT",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {column_type}")


def _ensure_default_settings(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), timestamp),
        )


def _mark_interrupted_runs(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        UPDATE runs
        SET status = 'skipped',
            finished_at = COALESCE(finished_at, ?),
            duration_ms = COALESCE(duration_ms, 0),
            error_message = COALESCE(error_message, '服务启动时发现任务未完成，已标记为中断'),
            failure_kind = COALESCE(failure_kind, 'runner'),
            notification_status = COALESCE(notification_status, 'not_required')
        WHERE status IN ('pending', 'running')
        """,
        (timestamp,),
    )


def _seed_demo_checks(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM checks").fetchone()["count"]
    if count:
        return
    timestamp = now_iso()
    for item in DEMO_CHECKS:
        conn.execute(
            """
            INSERT INTO checks (
                name, type, enabled, interval_seconds, timeout_ms, entry_url, viewport_mode, method,
                headers_json, body, assertions_json, setup_script, script, tags, alert_policy_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                item["type"],
                1 if item["enabled"] else 0,
                item["interval_seconds"],
                item["timeout_ms"],
                item["entry_url"],
                item.get("viewport_mode") or "web",
                item["method"],
                item["headers_json"],
                item["body"],
                item.get("assertions_json") or "[]",
                item.get("setup_script") or "",
                item["script"],
                item["tags"],
                item.get("alert_policy_json") or "{}",
                timestamp,
                timestamp,
            ),
        )


def _normalize_check(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data.pop("setup_url", None)
    data["viewport_mode"] = data.get("viewport_mode") or "web"
    data["headers_json"] = data.get("headers_json") or "{}"
    data["body"] = data.get("body") or ""
    data["assertions_json"] = data.get("assertions_json") or "[]"
    data["setup_script"] = data.get("setup_script") or ""
    data["script"] = data.get("script") or ""
    data["tags"] = data.get("tags") or ""
    data["alert_policy_json"] = data.get("alert_policy_json") or "{}"
    data["current_status"] = data.get("current_status")
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    data["last_duration_ms"] = data.get("last_duration_ms")
    return data


def _normalize_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["duration_ms"] = data.get("duration_ms")
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    data["failure_kind"] = _normalize_failure_kind(data.get("failure_kind"), str(data.get("status") or ""))
    return data


def _normalize_failure_kind(value: Any, status: str) -> str:
    failure_kind = str(value or "").strip()
    if failure_kind in {"none", "target", "runner"}:
        return failure_kind
    if status in {"failed", "timeout"}:
        return "target"
    if status == "skipped":
        return "runner"
    return "none"


def _normalize_heartbeat(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["payload"] = json.loads(data.get("payload_json") or "{}")
    except json.JSONDecodeError:
        data["payload"] = {}
    data.pop("payload_json", None)
    return data


def _normalize_audit_event(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["payload"] = json.loads(data.get("payload_json") or "{}")
    except json.JSONDecodeError:
        data["payload"] = {}
    data.pop("payload_json", None)
    return data


def _normalize_check_version(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["snapshot"] = json.loads(data.get("snapshot_json") or "{}")
    except json.JSONDecodeError:
        data["snapshot"] = {}
    data.pop("snapshot_json", None)
    return data


def _normalize_run_archive(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("id", "run_count", "duration_sum_ms", "duration_sample_count"):
        data[key] = int(data.get(key) or 0)
    return data


def _normalize_probe_runner(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["metadata"] = json.loads(data.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        data["metadata"] = {}
    data.pop("metadata_json", None)
    return data


def _check_snapshot(check: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "name",
        "type",
        "enabled",
        "interval_seconds",
        "timeout_ms",
        "entry_url",
        "viewport_mode",
        "method",
        "headers_json",
        "body",
        "assertions_json",
        "setup_script",
        "script",
        "tags",
        "alert_policy_json",
    )
    return {field: check.get(field) for field in fields}
