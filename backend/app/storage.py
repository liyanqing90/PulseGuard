from __future__ import annotations

import json
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


_LOCK = threading.RLock()


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

            CREATE INDEX IF NOT EXISTS idx_checks_type ON checks(type);
            CREATE INDEX IF NOT EXISTS idx_runs_check_id ON runs(check_id);
            CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_type_status ON runs(check_type, status);
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
                headers_json, body, assertions_json, setup_script, script, tags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                script = ?, tags = ?, updated_at = ?
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


def create_run(check: dict[str, Any], status: str = "running", error_message: str | None = None) -> dict[str, Any]:
    timestamp = now_iso()
    finished_at = timestamp if status == "skipped" else None
    duration_ms = 0 if status == "skipped" else None
    notification_status = "not_required" if status == "skipped" else None
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (
                check_id, check_name, check_type, status, started_at, finished_at,
                duration_ms, error_message, error_stack, logs, screenshot_path,
                trace_path, response_path, request_snapshot, response_snapshot,
                notification_status, notification_channel, notification_error,
                notification_sent_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                response_path = ?, request_snapshot = ?, response_snapshot = ?
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
                run_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
    return get_run(run_id)


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
    settings["notification_channels"] = [
        _public_notification_channel(channel)
        for channel in settings.get("notification_channels", [])
        if isinstance(channel, dict)
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
    return normalize_settings_values(_preserve_notification_channel_secrets(values))


def _public_notification_channel(channel: dict[str, Any]) -> dict[str, Any]:
    public = dict(channel)
    public["dingtalk_secret_set"] = bool(public.get("dingtalk_secret"))
    public["dingtalk_secret"] = ""
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

    return {
        "ui_count": ui_count,
        "api_count": api_count,
        "failing_count": failing_count,
        "today_runs": today_runs,
        "latest_run": _normalize_run(latest_run) if latest_run else None,
        "latest_recovered": dict(recovered) if recovered else None,
        "recent_failures": [_normalize_run(row) for row in failures],
    }


def cleanup_old_data(settings: dict[str, Any] | None = None) -> int:
    settings = settings or get_settings()
    retention_days = int(settings.get("run_retention_days", 30))
    cutoff = (datetime.now().astimezone() - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
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
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE checks ADD COLUMN {name} {column_type}")


def _ensure_run_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    columns = {
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
                headers_json, body, assertions_json, setup_script, script, tags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    data["current_status"] = data.get("current_status")
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    data["last_duration_ms"] = data.get("last_duration_ms")
    return data


def _normalize_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["duration_ms"] = data.get("duration_ms")
    data["consecutive_failures"] = int(data.get("consecutive_failures") or 0)
    return data
