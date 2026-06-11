from __future__ import annotations

import json
import re
import secrets
import hashlib
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from .artifacts import cleanup_old_artifacts
from .config import BACKUPS_DIR, DB_PATH, ensure_runtime_dirs
from .defaults import DEFAULT_SETTINGS, DEMO_CHECKS
from .monitoring import HEALTH_STATES, next_health_state, run_metadata
from .schemas import normalize_settings_values
from .variables import is_sensitive_variable_name


_LOCK = threading.RLock()
_TAG_SPLIT_PATTERN = re.compile(r"[,\s]+")
LOCAL_RUNNER_ID = "local"
RUNNER_HEARTBEAT_TIMEOUT_SECONDS = 120
RUNNER_ROLES = {"local", "child"}
RUNNER_SELECTION_MODES = {"selected_parallel", "round_robin_all"}


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
                runner_selection_mode TEXT NOT NULL DEFAULT 'selected_parallel',
                runner_ids_json TEXT NOT NULL DEFAULT '["local"]',
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
                runner_id TEXT,
                runner_name TEXT,
                runner_address TEXT,
                runner_region TEXT,
                runner_browser_version TEXT,
                failure_kind TEXT,
                notification_status TEXT,
                notification_channel TEXT,
                notification_error TEXT,
                notification_sent_at TEXT,
                trigger TEXT NOT NULL DEFAULT 'legacy',
                observation_kind TEXT NOT NULL DEFAULT 'observation',
                affects_health INTEGER NOT NULL DEFAULT 1,
                run_group_id TEXT,
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
                monitor_status TEXT NOT NULL DEFAULT 'unknown',
                consecutive_successes INTEGER NOT NULL DEFAULT 0,
                last_scheduled_at TEXT,
                last_scheduled_run_id INTEGER,
                last_state_changed_at TEXT,
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
                enabled INTEGER NOT NULL DEFAULT 1,
                role TEXT NOT NULL DEFAULT 'child',
                token_value TEXT NOT NULL DEFAULT '',
                token_hash TEXT NOT NULL DEFAULT '',
                token_hint TEXT NOT NULL DEFAULT '',
                unavailable_since TEXT,
                unavailable_notified_at TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runner_cursors (
                scope TEXT PRIMARY KEY,
                cursor INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS anomaly_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at TEXT NOT NULL,
                resolved_at TEXT,
                first_run_id INTEGER NOT NULL,
                last_run_id INTEGER NOT NULL,
                failure_count INTEGER NOT NULL DEFAULT 1,
                failure_kind TEXT NOT NULL DEFAULT 'target',
                summary TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_checks_type ON checks(type);
            CREATE INDEX IF NOT EXISTS idx_runs_check_id ON runs(check_id);
            CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_type_status ON runs(check_type, status);
            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_check_versions_check_id ON check_versions(check_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_run_archives_date ON run_archives(archive_date DESC);
            CREATE INDEX IF NOT EXISTS idx_probe_runners_region ON probe_runners(network_region, status);
            CREATE INDEX IF NOT EXISTS idx_anomaly_cycles_check_status ON anomaly_cycles(check_id, status, opened_at DESC);
            """
        )
        _ensure_check_columns(conn)
        _ensure_run_columns(conn)
        _ensure_check_status_columns(conn)
        _ensure_probe_runner_columns(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_observation ON runs(affects_health, started_at DESC)")
        conn.execute("INSERT OR IGNORE INTO schema_versions(version, applied_at) VALUES (1, ?)", (now_iso(),))
        _ensure_default_settings(conn)
        _migrate_read_only_tokens(conn)
        _ensure_local_probe_runner(conn)
        _mark_interrupted_runs(conn)
        _seed_demo_checks(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_runner_id ON runs(runner_id, started_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_group_id ON runs(run_group_id, started_at DESC)")


def list_checks(check_type: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
    refresh_stale_statuses()
    sql = """
        SELECT c.*, s.current_status, s.monitor_status, s.consecutive_failures,
               s.consecutive_successes, s.last_success_at, s.last_failed_at,
               s.last_run_at, s.last_run_id, s.last_error, s.last_scheduled_at,
               s.last_scheduled_run_id, s.last_state_changed_at,
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
    refresh_stale_statuses(check_id)
    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT c.*, s.current_status, s.monitor_status, s.consecutive_failures,
                   s.consecutive_successes, s.last_success_at, s.last_failed_at,
                   s.last_run_at, s.last_run_id, s.last_error, s.last_scheduled_at,
                   s.last_scheduled_run_id, s.last_state_changed_at,
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
                headers_json, body, assertions_json, setup_script, script, tags, alert_policy_json,
                runner_selection_mode, runner_ids_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _normalize_runner_selection_mode(data.get("runner_selection_mode")),
                json.dumps(_normalize_runner_ids(data.get("runner_ids") or data.get("runner_ids_json")), ensure_ascii=False),
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
                script = ?, tags = ?, alert_policy_json = ?, runner_selection_mode = ?, runner_ids_json = ?, updated_at = ?
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
                _normalize_runner_selection_mode(data.get("runner_selection_mode")),
                json.dumps(_normalize_runner_ids(data.get("runner_ids") or data.get("runner_ids_json")), ensure_ascii=False),
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
    metadata = check.get("_run") if isinstance(check.get("_run"), dict) else run_metadata(
        "scheduled" if int(check.get("id") or 0) > 0 else "draft"
    )
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                check_id, check_name, check_type, status, started_at, finished_at,
                duration_ms, error_message, error_stack, logs, screenshot_path,
                trace_path, response_path, request_snapshot, response_snapshot,
                runner_id, runner_name, runner_address, runner_region, runner_browser_version, failure_kind,
                notification_status, notification_channel, notification_error,
                notification_sent_at, trigger, observation_kind, affects_health, run_group_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                runner.get("runner_id"),
                runner.get("runner_name"),
                runner.get("runner_address"),
                runner.get("runner_region"),
                runner.get("runner_browser_version"),
                runner.get("failure_kind"),
                notification_status,
                None,
                None,
                None,
                metadata["trigger"],
                metadata["observation_kind"],
                1 if metadata["affects_health"] else 0,
                metadata.get("run_group_id"),
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
                runner_id = ?, runner_name = ?, runner_address = ?, runner_region = ?,
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
                data.get("runner_id"),
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
        if str(data.get("status") or "ok").strip() in {"ok", "warning"}:
            conn.execute(
                """
                UPDATE probe_runners
                SET unavailable_since = NULL,
                    unavailable_notified_at = NULL
                WHERE runner_id = ?
                """,
                (runner_id,),
            )
    return get_probe_runner(runner_id)  # type: ignore[return-value]


def create_probe_runner(data: dict[str, Any], *, generate_token: bool = True) -> dict[str, Any]:
    raw_token = str(data.get("token") or "").strip()
    generated_token = bool(generate_token and not raw_token)
    token = raw_token or (create_runner_token() if generate_token else "")
    runner_id = _normalize_runner_id(data.get("runner_id") or f"runner-{uuid.uuid4().hex[:8]}")
    timestamp = now_iso()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    with _LOCK, _connect() as conn:
        if conn.execute("SELECT 1 FROM probe_runners WHERE runner_id = ?", (runner_id,)).fetchone():
            raise ValueError("Runner ID already exists")
        conn.execute(
            """
            INSERT INTO probe_runners (
                runner_id, name, address, network_region, browser_version, status,
                metadata_json, enabled, role, token_value, token_hash, token_hint, created_at,
                last_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                runner_id,
                str(data.get("name") or runner_id).strip(),
                str(data.get("address") or "").strip(),
                str(data.get("network_region") or "local").strip(),
                str(data.get("browser_version") or "").strip(),
                "offline",
                json.dumps(metadata, ensure_ascii=False),
                1 if data.get("enabled", True) else 0,
                _normalize_runner_role(data.get("role") or "child"),
                token,
                runner_token_hash(token) if token else "",
                _token_hint(token),
                timestamp,
                timestamp,
                timestamp,
            ),
        )
    runner = get_probe_runner(runner_id) or {}
    if generated_token:
        runner["token"] = token
    return runner


def update_probe_runner(runner_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        current = conn.execute("SELECT * FROM probe_runners WHERE runner_id = ?", (runner_id,)).fetchone()
        if not current:
            return None
        name = str(data["name"] if data.get("name") is not None else current["name"] or runner_id).strip() or runner_id
        address = str(data["address"] if data.get("address") is not None else current["address"] or "").strip()
        network_region = str(data["network_region"] if data.get("network_region") is not None else current["network_region"] or "local").strip() or "local"
        enabled = bool(data["enabled"] if data.get("enabled") is not None else current["enabled"])
        assignments = ["name = ?", "address = ?", "network_region = ?", "enabled = ?", "updated_at = ?"]
        params: list[Any] = [name, address, network_region, 1 if enabled else 0, timestamp]
        token = str(data.get("token") or "").strip()
        if token:
            assignments.extend(["token_value = ?", "token_hash = ?", "token_hint = ?"])
            params.extend([token, runner_token_hash(token), _token_hint(token)])
        params.append(runner_id)
        cursor = conn.execute(
            f"""
            UPDATE probe_runners
            SET {", ".join(assignments)}
            WHERE runner_id = ?
            """,
            params,
        )
        if cursor.rowcount == 0:
            return None
        if runner_id == LOCAL_RUNNER_ID:
            for key, value in {
                "local_runner_name": name,
                "local_runner_address": address,
                "local_runner_region": network_region,
            }.items():
                conn.execute(
                    """
                    INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value, ensure_ascii=False), timestamp),
                )
    return get_probe_runner(runner_id)


def mark_probe_runner_available(runner_id: str, health: dict[str, Any] | None = None) -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    health = health if isinstance(health, dict) else {}
    status = str(health.get("status") or "ok").strip().lower()
    if status not in {"ok", "warning"}:
        status = "ok"
    browser_version = str(health.get("browser_version") or "").strip()
    metadata = health.get("metadata") if isinstance(health.get("metadata"), dict) else {}
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE probe_runners
            SET status = ?,
                browser_version = ?,
                metadata_json = ?,
                unavailable_since = NULL,
                unavailable_notified_at = NULL,
                last_seen_at = ?,
                updated_at = ?
            WHERE runner_id = ?
            """,
            (status, browser_version, json.dumps(metadata, ensure_ascii=False), timestamp, timestamp, runner_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_probe_runner(runner_id)


def delete_probe_runner(runner_id: str) -> bool:
    runner_id = _normalize_runner_id(runner_id)
    if runner_id == LOCAL_RUNNER_ID:
        raise ValueError("local Runner cannot be deleted")
    with _LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM probe_runners WHERE runner_id = ?", (runner_id,))
        return cursor.rowcount > 0


def rotate_probe_runner_token(runner_id: str) -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    token = create_runner_token()
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE probe_runners
            SET token_value = ?, token_hash = ?, token_hint = ?, updated_at = ?
            WHERE runner_id = ?
            """,
            (token, runner_token_hash(token), _token_hint(token), timestamp, runner_id),
        )
        if cursor.rowcount == 0:
            return None
    runner = get_probe_runner(runner_id) or {}
    runner["token"] = token
    return runner


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


def list_enabled_probe_runners() -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM probe_runners
            WHERE enabled = 1
            ORDER BY role = 'local' DESC, runner_id ASC
            """
        ).fetchall()
    return [_normalize_probe_runner(row) for row in rows]


def list_probe_runners_by_ids(runner_ids: list[str]) -> list[dict[str, Any]]:
    ids = _normalize_runner_ids(runner_ids)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _LOCK, _connect() as conn:
        rows = conn.execute(f"SELECT * FROM probe_runners WHERE runner_id IN ({placeholders})", ids).fetchall()
    by_id = {_normalize_probe_runner(row)["runner_id"]: _normalize_probe_runner(row) for row in rows}
    return [by_id[runner_id] for runner_id in ids if runner_id in by_id]


def runner_metadata(runner: dict[str, Any], failure_kind: str = "none", browser_version: str | None = None) -> dict[str, str]:
    return {
        "runner_id": str(runner.get("runner_id") or LOCAL_RUNNER_ID),
        "runner_name": str(runner.get("name") or runner.get("runner_id") or LOCAL_RUNNER_ID),
        "runner_address": str(runner.get("address") or ""),
        "runner_region": str(runner.get("network_region") or "local"),
        "runner_browser_version": str(browser_version if browser_version is not None else runner.get("browser_version") or ""),
        "failure_kind": failure_kind if failure_kind in {"none", "target", "runner"} else "runner",
    }


def create_runner_token() -> str:
    return f"pgrn_{secrets.token_urlsafe(32)}"


def runner_token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def verify_probe_runner_token(runner_id: str, token: str) -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    token = str(token or "").strip()
    if not runner_id or not token:
        return None
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM probe_runners WHERE runner_id = ?", (runner_id,)).fetchone()
    if not row:
        return None
    expected_hash = str(row["token_hash"] or "")
    expected_value = str(row["token_value"] or "") if "token_value" in row.keys() else ""
    valid = bool(expected_value and secrets.compare_digest(expected_value, token))
    valid = valid or bool(expected_hash and secrets.compare_digest(expected_hash, runner_token_hash(token)))
    if not valid:
        return None
    return _normalize_probe_runner(row)


def get_probe_runner_token(runner_id: str) -> str:
    runner_id = _normalize_runner_id(runner_id)
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT token_value FROM probe_runners WHERE runner_id = ?", (runner_id,)).fetchone()
    return str(row["token_value"] or "") if row else ""


def mark_probe_runner_unavailable(runner_id: str, status: str = "offline") -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE probe_runners
            SET status = ?,
                unavailable_since = COALESCE(unavailable_since, ?),
                updated_at = ?
            WHERE runner_id = ?
            """,
            (status, timestamp, timestamp, runner_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_probe_runner(runner_id)


def mark_probe_runner_unavailable_notified(runner_id: str) -> dict[str, Any] | None:
    runner_id = _normalize_runner_id(runner_id)
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE probe_runners
            SET unavailable_notified_at = ?, updated_at = ?
            WHERE runner_id = ?
            """,
            (timestamp, timestamp, runner_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_probe_runner(runner_id)


def should_notify_probe_runner_unavailable(runner: dict[str, Any]) -> bool:
    return bool(runner.get("enabled")) and str(runner.get("role") or "") != "local" and not runner.get("available") and not runner.get("unavailable_notified_at")


def next_runner_cursor(scope: str, count: int) -> int:
    count = max(1, int(count))
    timestamp = now_iso()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT cursor FROM runner_cursors WHERE scope = ?", (scope,)).fetchone()
        current = int(row["cursor"] or 0) if row else 0
        next_cursor = (current + 1) % count
        conn.execute(
            """
            INSERT INTO runner_cursors(scope, cursor, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(scope) DO UPDATE SET cursor = excluded.cursor, updated_at = excluded.updated_at
            """,
            (scope, next_cursor, timestamp),
        )
    return current % count


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
    timestamp = run.get("finished_at") or now_iso()
    settings = get_settings()

    with _LOCK, _connect() as conn:
        previous = conn.execute(
            "SELECT * FROM check_status WHERE check_id = ?",
            (check_id,),
        ).fetchone()
        previous_dict = dict(previous) if previous else None
        transition = next_health_state(previous_dict, run, settings)
        current_status = transition["current_status"]
        previous_status = transition["previous_status"]
        last_success_at = timestamp if run["status"] == "ok" else (previous_dict or {}).get("last_success_at")
        last_failed_at = (
            timestamp
            if run["status"] in {"failed", "timeout"} and run.get("failure_kind") != "runner"
            else (previous_dict or {}).get("last_failed_at")
        )
        state_changed_at = timestamp if current_status != previous_status else (previous_dict or {}).get("last_state_changed_at")

        conn.execute(
            """
            INSERT INTO check_status (
                check_id, current_status, consecutive_failures, last_success_at,
                last_failed_at, last_run_at, last_run_id, last_error, last_notified_at,
                monitor_status, consecutive_successes, last_scheduled_at,
                last_scheduled_run_id, last_state_changed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(check_id) DO UPDATE SET
                current_status = excluded.current_status,
                consecutive_failures = excluded.consecutive_failures,
                last_success_at = excluded.last_success_at,
                last_failed_at = excluded.last_failed_at,
                last_run_at = excluded.last_run_at,
                last_run_id = excluded.last_run_id,
                last_error = excluded.last_error,
                monitor_status = excluded.monitor_status,
                consecutive_successes = excluded.consecutive_successes,
                last_scheduled_at = excluded.last_scheduled_at,
                last_scheduled_run_id = excluded.last_scheduled_run_id,
                last_state_changed_at = excluded.last_state_changed_at,
                updated_at = excluded.updated_at
            """,
            (
                check_id,
                current_status,
                transition["consecutive_failures"],
                last_success_at,
                last_failed_at,
                timestamp,
                run["id"],
                run.get("error_message"),
                (previous_dict or {}).get("last_notified_at"),
                current_status,
                transition["consecutive_successes"],
                timestamp,
                run["id"],
                state_changed_at,
                timestamp,
            ),
        )
        _update_anomaly_cycle(conn, check_id, run, transition, timestamp)

    return transition


def refresh_stale_statuses(check_id: int | None = None) -> int:
    settings = get_settings()
    stale_after = max(1, int(settings.get("stale_after_intervals", 2)))
    clauses = ["c.enabled = 1", "s.last_scheduled_at IS NOT NULL", "s.monitor_status != 'stale'"]
    params: list[Any] = []
    if check_id is not None:
        clauses.append("c.id = ?")
        params.append(check_id)
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.interval_seconds, s.last_scheduled_at
            FROM checks c
            JOIN check_status s ON s.check_id = c.id
            WHERE {" AND ".join(clauses)}
            """,
            params,
        ).fetchall()
        stale_ids: list[int] = []
        now = datetime.now().astimezone()
        for row in rows:
            try:
                last_scheduled = datetime.fromisoformat(str(row["last_scheduled_at"]))
            except ValueError:
                continue
            if now - last_scheduled > timedelta(seconds=max(5, int(row["interval_seconds"])) * stale_after):
                stale_ids.append(int(row["id"]))
        if not stale_ids:
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        timestamp = now_iso()
        conn.execute(
            f"""
            UPDATE check_status
            SET current_status = 'stale', monitor_status = 'stale',
                last_state_changed_at = ?, updated_at = ?
            WHERE check_id IN ({placeholders})
            """,
            [timestamp, timestamp, *stale_ids],
        )
        return len(stale_ids)


def _update_anomaly_cycle(
    conn: sqlite3.Connection,
    check_id: int,
    run: dict[str, Any],
    transition: dict[str, Any],
    timestamp: str,
) -> None:
    current = transition["current_status"]
    previous = transition["previous_status"]
    if current == "failing":
        open_cycle = conn.execute(
            "SELECT id FROM anomaly_cycles WHERE check_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (check_id,),
        ).fetchone()
        if open_cycle:
            conn.execute(
                """
                UPDATE anomaly_cycles
                SET last_run_id = ?, failure_count = ?, failure_kind = ?, summary = ?
                WHERE id = ?
                """,
                (
                    run["id"],
                    transition["consecutive_failures"],
                    run.get("failure_kind") or "target",
                    run.get("error_message") or "",
                    open_cycle["id"],
                ),
            )
        elif previous != "failing":
            conn.execute(
                """
                INSERT INTO anomaly_cycles (
                    check_id, status, opened_at, first_run_id, last_run_id,
                    failure_count, failure_kind, summary
                ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?)
                """,
                (
                    check_id,
                    timestamp,
                    run["id"],
                    run["id"],
                    transition["consecutive_failures"],
                    run.get("failure_kind") or "target",
                    run.get("error_message") or "",
                ),
            )
    elif current == "healthy":
        conn.execute(
            """
            UPDATE anomaly_cycles
            SET status = 'resolved', resolved_at = ?, last_run_id = ?
            WHERE check_id = ? AND status = 'open'
            """,
            (timestamp, run["id"], check_id),
        )


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
    if filters.get("runner_id"):
        clauses.append("runner_id = ?")
        params.append(filters["runner_id"])
    if filters.get("run_group_id"):
        clauses.append("run_group_id = ?")
        params.append(filters["run_group_id"])
    if filters.get("trigger"):
        clauses.append("trigger = ?")
        params.append(filters["trigger"])
    if filters.get("observation_kind"):
        clauses.append("observation_kind = ?")
        params.append(filters["observation_kind"])
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


def list_runs_page(
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    filters = filters or {}
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    clauses, params = _run_filter_clauses(filters)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK, _connect() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) AS count FROM runs{where}", params).fetchone()["count"])
        rows = conn.execute(
            f"SELECT * FROM runs{where} ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [_normalize_run(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _run_filter_clauses(filters: dict[str, Any]) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    mappings = (
        ("check_type", "check_type"),
        ("notification_status", "notification_status"),
        ("runner_id", "runner_id"),
        ("run_group_id", "run_group_id"),
        ("trigger", "trigger"),
        ("observation_kind", "observation_kind"),
    )
    for key, column in mappings:
        if filters.get(key):
            clauses.append(f"{column} = ?")
            params.append(filters[key])
    if filters.get("status"):
        if filters["status"] == "failed":
            clauses.append("status IN ('failed', 'timeout')")
        else:
            clauses.append("status = ?")
            params.append(filters["status"])
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
    return clauses, params


def list_anomaly_cycles(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if status:
        where = "WHERE a.status = ?"
        params.append(status)
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.*, c.name AS check_name, c.type AS check_type
            FROM anomaly_cycles a
            JOIN checks c ON c.id = a.check_id
            {where}
            ORDER BY a.opened_at DESC, a.id DESC
            LIMIT ?
            """,
            [*params, max(1, min(500, int(limit)))],
        ).fetchall()
    return [dict(row) for row in rows]


def create_database_backup(preserve_filename: str | None = None) -> dict[str, Any]:
    ensure_runtime_dirs()
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"pulseguard-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')}.db"
    target = BACKUPS_DIR / filename
    with _LOCK:
        source = sqlite3.connect(DB_PATH, timeout=30)
        destination = sqlite3.connect(target, timeout=30)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    _cleanup_database_backups(preserve_filename)
    return _database_backup_info(target)


def list_database_backups() -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return [_database_backup_info(path) for path in sorted(BACKUPS_DIR.glob("pulseguard-*.db"), reverse=True)]


def restore_database_backup(filename: str) -> dict[str, Any]:
    source_path = (BACKUPS_DIR / filename).resolve()
    if source_path.parent != BACKUPS_DIR.resolve() or not source_path.is_file():
        raise ValueError("数据库备份不存在")
    safety_backup = create_database_backup(preserve_filename=source_path.name)
    with _LOCK:
        source = sqlite3.connect(source_path, timeout=30)
        destination = sqlite3.connect(DB_PATH, timeout=30)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
    init_db()
    return {"restored": _database_backup_info(source_path), "safety_backup": safety_backup}


def _database_backup_info(path: Any) -> dict[str, Any]:
    stat = path.stat()
    return {
        "filename": path.name,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    }


def _cleanup_database_backups(preserve_filename: str | None = None) -> None:
    retention = max(1, int(get_settings().get("database_backup_retention", 7)))
    removable = [
        path
        for path in sorted(BACKUPS_DIR.glob("pulseguard-*.db"), reverse=True)
        if path.name != preserve_filename
    ]
    for path in removable[retention:]:
        path.unlink(missing_ok=True)


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
    settings["read_only_tokens"] = [
        _public_read_only_token(token)
        for token in settings.get("read_only_tokens", [])
        if isinstance(token, dict)
    ]
    settings["read_only_token_set"] = bool(settings.get("read_only_token") or settings["read_only_tokens"])
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
        if "members" in normalized_values:
            member_ids = {
                str(member.get("id") or "")
                for member in normalized_values["members"]
                if isinstance(member, dict) and member.get("id")
            }
            _prune_unknown_member_references(conn, member_ids, timestamp)
    return get_settings()


def normalize_settings_update_values(values: dict[str, Any]) -> dict[str, Any]:
    values = _preserve_notification_channel_secrets(values)
    values = _preserve_environment_variable_secrets(values)
    return normalize_settings_values(values)


def create_read_only_token(name: str) -> dict[str, Any]:
    token = f"pgro_{secrets.token_urlsafe(32)}"
    item = {
        "id": f"rot_{uuid.uuid4().hex}",
        "name": str(name or "").strip() or "未命名令牌",
        "token": token,
        "created_at": now_iso(),
    }
    settings = get_settings()
    tokens = [
        token_item
        for token_item in settings.get("read_only_tokens", [])
        if isinstance(token_item, dict)
    ]
    tokens.append(item)
    update_settings({"read_only_tokens": tokens})
    public = _public_read_only_token(item)
    public["token"] = token
    return public


def delete_read_only_token(token_id: str) -> dict[str, Any]:
    target = str(token_id or "").strip()
    settings = get_settings()
    tokens = [
        token_item
        for token_item in settings.get("read_only_tokens", [])
        if isinstance(token_item, dict)
    ]
    next_tokens = [token_item for token_item in tokens if str(token_item.get("id") or "") != target]
    if len(next_tokens) == len(tokens):
        raise ValueError("只读访问令牌不存在")
    update_settings({"read_only_tokens": next_tokens})
    return get_public_settings()


def _public_read_only_token(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(token.get("id") or ""),
        "name": str(token.get("name") or "未命名令牌"),
        "created_at": str(token.get("created_at") or ""),
    }


def _prune_unknown_member_references(conn: sqlite3.Connection, member_ids: set[str], timestamp: str) -> None:
    for row in conn.execute("SELECT id, alert_policy_json FROM checks").fetchall():
        try:
            policy = json.loads(row["alert_policy_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(policy, dict) or not isinstance(policy.get("member_ids"), list):
            continue
        selected = [str(member_id) for member_id in policy["member_ids"] if str(member_id) in member_ids]
        if selected == policy["member_ids"]:
            continue
        if selected:
            policy["member_ids"] = selected
        else:
            policy.pop("member_ids", None)
        conn.execute(
            "UPDATE checks SET alert_policy_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(policy, ensure_ascii=False), timestamp, int(row["id"])),
        )


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
    refresh_stale_statuses()
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with _LOCK, _connect() as conn:
        ui_count = conn.execute("SELECT COUNT(*) AS count FROM checks WHERE type = 'ui'").fetchone()["count"]
        api_count = conn.execute("SELECT COUNT(*) AS count FROM checks WHERE type = 'api'").fetchone()["count"]
        state_counts = {
            str(row["monitor_status"] or "unknown"): int(row["count"])
            for row in conn.execute(
                """
                SELECT COALESCE(s.monitor_status, 'unknown') AS monitor_status, COUNT(*) AS count
                FROM checks c
                LEFT JOIN check_status s ON s.check_id = c.id
                WHERE c.enabled = 1
                GROUP BY COALESCE(s.monitor_status, 'unknown')
                """
            ).fetchall()
        }
        failing_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM check_status s
            JOIN checks c ON c.id = s.check_id
            WHERE c.enabled = 1 AND s.monitor_status = 'failing'
            """
        ).fetchone()["count"]
        today_runs = conn.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE check_id > 0 AND affects_health = 1 AND started_at >= ?",
            (today,),
        ).fetchone()["count"]
        latest_run = conn.execute(
            "SELECT * FROM runs WHERE check_id > 0 AND affects_health = 1 ORDER BY started_at DESC, id DESC LIMIT 1"
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
            FROM check_status s
            JOIN runs r ON r.id = s.last_scheduled_run_id
            JOIN checks c ON c.id = s.check_id
            WHERE c.enabled = 1
              AND s.monitor_status = 'failing'
              AND r.status IN ('failed', 'timeout')
            ORDER BY r.started_at DESC, r.id DESC
            LIMIT 8
            """
        ).fetchall()
        trends = _overview_trends(conn)

    return {
        "ui_count": ui_count,
        "api_count": api_count,
        "failing_count": failing_count,
        "suspected_failing_count": state_counts.get("suspected_failing", 0),
        "suspected_recovery_count": state_counts.get("suspected_recovery", 0),
        "suspected_count": state_counts.get("suspected_failing", 0) + state_counts.get("suspected_recovery", 0),
        "unknown_count": state_counts.get("unknown", 0),
        "stale_count": state_counts.get("stale", 0),
        "healthy_count": state_counts.get("healthy", 0),
        "today_runs": today_runs,
        "latest_run": _normalize_run(latest_run) if latest_run else None,
        "latest_recovered": dict(recovered) if recovered else None,
        "recent_failures": [_normalize_run(row) for row in failures],
        "trends": trends,
    }


def _overview_trends(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now().astimezone()
    periods = [
        ("24h", "近 24 小时", now - timedelta(hours=24)),
        ("7d", "近 7 天", now - timedelta(days=7)),
    ]
    trend_types = [("ui", "UI"), ("api", "API")]
    trends: list[dict[str, Any]] = []
    for key, label, cutoff in periods:
        rows = conn.execute(
            """
            SELECT check_type, status, duration_ms
            FROM runs
            WHERE check_id > 0
              AND affects_health = 1
              AND started_at >= ?
              AND started_at <= ?
              AND check_type IN ('ui', 'api')
              AND status IN ('ok', 'failed', 'timeout')
            """,
            (cutoff.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
        ).fetchall()
        rows_by_type: dict[str, list[sqlite3.Row]] = {check_type: [] for check_type, _ in trend_types}
        for row in rows:
            rows_by_type[str(row["check_type"])].append(row)
        trends.append(
            {
                "key": key,
                "label": label,
                "series": [
                    {
                        "check_type": check_type,
                        "label": type_label,
                        **_overview_trend_metrics(rows_by_type[check_type]),
                    }
                    for check_type, type_label in trend_types
                ],
            }
        )
    return trends


def _overview_trend_metrics(rows: list[sqlite3.Row]) -> dict[str, Any]:
    total = len(rows)
    successes = sum(1 for row in rows if row["status"] == "ok")
    failures = sum(1 for row in rows if row["status"] in {"failed", "timeout"})
    durations = sorted(int(row["duration_ms"]) for row in rows if row["duration_ms"] is not None)
    return {
        "runs": total,
        "success_count": successes,
        "success_rate": round((successes / total) * 100, 1) if total else None,
        "failure_count": failures,
        "duration_p50_ms": _percentile(durations, 0.5),
        "duration_p95_ms": _percentile(durations, 0.95),
    }


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
        "runner_selection_mode": "TEXT NOT NULL DEFAULT 'selected_parallel'",
        "runner_ids_json": "TEXT NOT NULL DEFAULT '[\"local\"]'",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE checks ADD COLUMN {name} {column_type}")


def _ensure_run_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    columns = {
        "request_snapshot": "TEXT",
        "response_snapshot": "TEXT",
        "runner_id": "TEXT",
        "runner_name": "TEXT",
        "runner_address": "TEXT",
        "runner_region": "TEXT",
        "runner_browser_version": "TEXT",
        "failure_kind": "TEXT",
        "notification_status": "TEXT",
        "notification_channel": "TEXT",
        "notification_error": "TEXT",
        "notification_sent_at": "TEXT",
        "trigger": "TEXT NOT NULL DEFAULT 'legacy'",
        "observation_kind": "TEXT NOT NULL DEFAULT 'observation'",
        "affects_health": "INTEGER NOT NULL DEFAULT 1",
        "run_group_id": "TEXT",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {column_type}")


def _ensure_check_status_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(check_status)").fetchall()}
    columns = {
        "monitor_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "consecutive_successes": "INTEGER NOT NULL DEFAULT 0",
        "last_scheduled_at": "TEXT",
        "last_scheduled_run_id": "INTEGER",
        "last_state_changed_at": "TEXT",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE check_status ADD COLUMN {name} {column_type}")
    conn.execute(
        """
        UPDATE check_status
        SET monitor_status = CASE current_status
            WHEN 'ok' THEN 'healthy'
            WHEN 'failed' THEN 'failing'
            ELSE COALESCE(NULLIF(monitor_status, ''), 'unknown')
        END
        WHERE monitor_status = 'unknown' AND current_status IN ('ok', 'failed')
        """
    )
    conn.execute(
        """
        UPDATE check_status
        SET current_status = 'unknown',
            monitor_status = 'unknown',
            consecutive_failures = 0,
            consecutive_successes = 0
        WHERE current_status = 'suspected' OR monitor_status = 'suspected'
        """
    )


def _ensure_probe_runner_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(probe_runners)").fetchall()}
    columns = {
        "enabled": "INTEGER NOT NULL DEFAULT 1",
        "role": "TEXT NOT NULL DEFAULT 'child'",
        "token_value": "TEXT NOT NULL DEFAULT ''",
        "token_hash": "TEXT NOT NULL DEFAULT ''",
        "token_hint": "TEXT NOT NULL DEFAULT ''",
        "unavailable_since": "TEXT",
        "unavailable_notified_at": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE probe_runners ADD COLUMN {name} {column_type}")
    timestamp = now_iso()
    conn.execute(
        "UPDATE probe_runners SET created_at = COALESCE(NULLIF(created_at, ''), updated_at, last_seen_at, ?) WHERE created_at = ''",
        (timestamp,),
    )


def _ensure_local_probe_runner(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    name = str(_read_setting_value(conn, "local_runner_name") or "local").strip() or "local"
    address = str(_read_setting_value(conn, "local_runner_address") or "127.0.0.1").strip()
    region = str(_read_setting_value(conn, "local_runner_region") or "local").strip() or "local"
    conn.execute(
        """
        INSERT INTO probe_runners (
            runner_id, name, address, network_region, browser_version, status,
            metadata_json, enabled, role, token_hash, token_hint, created_at,
            last_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(runner_id) DO UPDATE SET
            name = excluded.name,
            address = excluded.address,
            network_region = excluded.network_region,
            status = 'ok',
            role = 'local',
            last_seen_at = excluded.last_seen_at,
            updated_at = excluded.updated_at
        """,
        (
            LOCAL_RUNNER_ID,
            name,
            address,
            region,
            "",
            "ok",
            "{}",
            1,
            "local",
            "",
            "",
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def _ensure_default_settings(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), timestamp),
        )


def _migrate_read_only_tokens(conn: sqlite3.Connection) -> None:
    legacy_token = str(_read_setting_value(conn, "read_only_token") or "").strip()
    legacy_name = str(_read_setting_value(conn, "read_only_token_name") or "").strip() or "旧版只读令牌"
    tokens_value = _read_setting_value(conn, "read_only_tokens")
    tokens = tokens_value if isinstance(tokens_value, list) else []
    timestamp = now_iso()

    if legacy_token:
        normalized_tokens = [token for token in tokens if isinstance(token, dict)]
        if not any(str(token.get("token") or "") == legacy_token for token in normalized_tokens):
            normalized_tokens.append(
                {
                    "id": f"rot_{uuid.uuid4().hex}",
                    "name": legacy_name,
                    "token": legacy_token,
                    "created_at": timestamp,
                }
            )
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            ("read_only_tokens", json.dumps(normalized_tokens, ensure_ascii=False), timestamp),
        )
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            ("read_only_token", json.dumps("", ensure_ascii=False), timestamp),
        )
    conn.execute("DELETE FROM settings WHERE key = 'read_only_token_name'")


def _read_setting_value(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


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
    data["runner_selection_mode"] = _normalize_runner_selection_mode(data.get("runner_selection_mode"))
    data["runner_ids"] = _normalize_runner_ids(data.get("runner_ids_json"))
    if not data["enabled"]:
        data["monitor_status"] = "disabled"
    else:
        data["monitor_status"] = data.get("monitor_status") or "unknown"
        if data["monitor_status"] not in HEALTH_STATES:
            data["monitor_status"] = "unknown"
    data["current_status"] = data["monitor_status"]
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    data["consecutive_successes"] = int(data.get("consecutive_successes") or 0)
    data["last_duration_ms"] = data.get("last_duration_ms")
    return data


def _normalize_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["duration_ms"] = data.get("duration_ms")
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    data["failure_kind"] = _normalize_failure_kind(data.get("failure_kind"), str(data.get("status") or ""))
    data["runner_id"] = data.get("runner_id") or (LOCAL_RUNNER_ID if data.get("runner_name") else "")
    data["trigger"] = data.get("trigger") or "legacy"
    data["observation_kind"] = data.get("observation_kind") or "observation"
    data["affects_health"] = bool(data.get("affects_health"))
    data["run_group_id"] = data.get("run_group_id") or ""
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
    data["enabled"] = bool(data.get("enabled", True))
    data["role"] = _normalize_runner_role(data.get("role"))
    data["token_set"] = bool(data.get("token_hash"))
    data["available"] = _runner_available(data)
    data.pop("token_value", None)
    data.pop("token_hash", None)
    return data


def _normalize_runner_id(value: Any) -> str:
    runner_id = str(value or "").strip()
    if not runner_id:
        raise ValueError("Runner ID cannot be empty")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", runner_id):
        raise ValueError("Runner ID format is invalid")
    return runner_id


def _normalize_runner_role(value: Any) -> str:
    role = str(value or "child").strip().lower()
    return role if role in RUNNER_ROLES else "child"


def _normalize_runner_selection_mode(value: Any) -> str:
    mode = str(value or "selected_parallel").strip()
    return mode if mode in RUNNER_SELECTION_MODES else "selected_parallel"


def _normalize_runner_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    else:
        parsed = value
    if not isinstance(parsed, list):
        parsed = []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        runner_id = str(item or "").strip()
        if not runner_id or runner_id in seen:
            continue
        seen.add(runner_id)
        result.append(runner_id)
    return result or [LOCAL_RUNNER_ID]


def _token_hint(token: str) -> str:
    token = str(token or "")
    return token[-6:] if len(token) >= 6 else token


def _runner_available(data: dict[str, Any]) -> bool:
    if not data.get("enabled"):
        return False
    if str(data.get("role") or "") == "local":
        return str(data.get("status") or "ok") != "offline"
    if str(data.get("status") or "ok") == "offline":
        return False
    try:
        last_seen = datetime.fromisoformat(str(data.get("last_seen_at") or ""))
    except ValueError:
        return False
    age = datetime.now(last_seen.tzinfo) - last_seen
    return age.total_seconds() <= RUNNER_HEARTBEAT_TIMEOUT_SECONDS


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
        "runner_selection_mode",
        "runner_ids",
    )
    return {field: check.get(field) for field in fields}
