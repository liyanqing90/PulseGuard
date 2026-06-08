from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.app import storage


class OverviewStorageTests(unittest.TestCase):
    def test_overview_excludes_draft_runs_from_task_level_metrics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(
                {
                    "name": "正式任务",
                    "type": "api",
                    "enabled": True,
                    "interval_seconds": 300,
                    "timeout_ms": 10000,
                    "entry_url": "https://example.com",
                    "method": "GET",
                    "headers_json": "{}",
                    "body": "",
                    "script": "async def check(ctx):\n    pass\n",
                    "tags": "",
                }
            )
            saved_run = storage.create_run(check)
            storage.finish_run(int(saved_run["id"]), run_payload("ok"))

            draft_run = storage.create_run({"id": 0, "name": "草稿调试", "type": "api"})
            storage.finish_run(int(draft_run["id"]), run_payload("failed", "草稿失败"))

            overview = storage.get_overview()

        self.assertEqual(overview["today_runs"], 1)
        self.assertEqual(overview["latest_run"]["id"], saved_run["id"])
        self.assertNotIn(draft_run["id"], [run["id"] for run in overview["recent_failures"]])

    def test_overview_trends_count_windows_and_ignore_drafts_and_non_terminal_runs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Trend API"))
            check_id = int(check["id"])
            now = datetime.now().astimezone().replace(microsecond=0)

            insert_trend_run(check_id, "ok", now - timedelta(hours=1), 100)
            insert_trend_run(check_id, "failed", now - timedelta(hours=2), 300)
            insert_trend_run(check_id, "timeout", now - timedelta(hours=3), 500)
            insert_trend_run(check_id, "ok", now - timedelta(hours=4), 700)
            insert_trend_run(check_id, "ok", now - timedelta(days=2), 200)
            insert_trend_run(check_id, "failed", now - timedelta(days=3), 400)
            insert_trend_run(check_id, "ok", now - timedelta(days=4), 600)

            insert_trend_run(check_id, "ok", now - timedelta(days=8), 999)
            insert_trend_run(0, "failed", now - timedelta(hours=5), 1)
            insert_trend_run(-10, "ok", now - timedelta(hours=6), 2)
            insert_trend_run(check_id, "skipped", now - timedelta(hours=7), 3)
            insert_trend_run(check_id, "running", now - timedelta(hours=8), 4)
            insert_trend_run(check_id, "pending", now - timedelta(hours=9), 5)
            insert_trend_run(check_id, "failed", now + timedelta(hours=1), 800)

            overview = storage.get_overview()

        trends = {item["key"]: item for item in overview["trends"]}

        self.assertEqual(set(trends), {"24h", "7d"})
        self.assertEqual(trends["24h"]["runs"], 4)
        self.assertEqual(trends["24h"]["success_rate"], 50.0)
        self.assertEqual(trends["24h"]["failure_count"], 2)
        self.assertEqual(trends["24h"]["duration_p50_ms"], 300)
        self.assertEqual(trends["24h"]["duration_p95_ms"], 700)
        self.assertEqual(trends["7d"]["runs"], 7)
        self.assertEqual(trends["7d"]["success_rate"], 57.1)
        self.assertEqual(trends["7d"]["failure_count"], 3)
        self.assertEqual(trends["7d"]["duration_p50_ms"], 400)
        self.assertEqual(trends["7d"]["duration_p95_ms"], 700)

    def test_overview_trends_return_empty_metrics_without_duration_samples(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Sparse Trend API"))
            now = datetime.now().astimezone().replace(microsecond=0)
            insert_trend_run(int(check["id"]), "ok", now - timedelta(hours=1), None)

            overview = storage.get_overview()

        trends = {item["key"]: item for item in overview["trends"]}
        self.assertEqual(trends["24h"]["runs"], 1)
        self.assertEqual(trends["24h"]["success_rate"], 100.0)
        self.assertEqual(trends["24h"]["failure_count"], 0)
        self.assertIsNone(trends["24h"]["duration_p50_ms"])
        self.assertIsNone(trends["24h"]["duration_p95_ms"])

    def test_ui_setup_fields_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(
                {
                    "name": "登录后页面",
                    "type": "ui",
                    "enabled": True,
                    "interval_seconds": 300,
                    "timeout_ms": 15000,
                    "entry_url": "https://example.com/dashboard",
                    "viewport_mode": "h5",
                    "method": "",
                    "headers_json": "{}",
                    "body": "",
                    "assertions_json": '[{"type":"title_contains","expected_text":"Dashboard"}]',
                    "setup_script": "async def setup(ctx, page):\n    pass\n",
                    "script": "",
                    "tags": "",
                }
            )

            loaded = storage.get_check(int(check["id"]))

        self.assertEqual(loaded["viewport_mode"], "h5")
        self.assertIn("async def setup", loaded["setup_script"])

    def test_pending_run_can_transition_to_running(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(
                {
                    "name": "排队任务",
                    "type": "api",
                    "enabled": True,
                    "interval_seconds": 300,
                    "timeout_ms": 10000,
                    "entry_url": "https://example.com",
                    "method": "GET",
                    "headers_json": "{}",
                    "body": "",
                    "script": "async def check(ctx):\n    pass\n",
                    "tags": "",
                }
            )

            queued = storage.create_run(check, "pending")
            started = storage.start_run(int(queued["id"]))

        self.assertIsNotNone(started)
        self.assertEqual(started["status"], "running")
        self.assertIsNone(started["finished_at"])


class CheckAlertPolicyStorageTests(unittest.TestCase):
    def test_create_get_and_update_check_persist_alert_policy_json(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            defaulted = storage.create_check(api_check_data("Default policy API"))

            policy = {
                "alert_cooldown_minutes": 15,
                "recovery_notification": False,
                "notification_channel_ids": ["ops"],
            }
            created = storage.create_check(
                api_check_data("Policy API", alert_policy_json=json_dumps(policy))
            )
            loaded = storage.get_check(int(created["id"]))

            updated_policy = {
                "alert_cooldown_minutes": 45,
                "recovery_notification": True,
                "notification_channel_ids": ["ops", "backup"],
            }
            update_payload = dict(created)
            update_payload["name"] = "Updated policy API"
            update_payload["alert_policy_json"] = json_dumps(updated_policy)
            updated = storage.update_check(int(created["id"]), update_payload)
            reloaded = storage.get_check(int(created["id"]))

        self.assertEqual(defaulted["alert_policy_json"], "{}")
        self.assertIsNotNone(loaded)
        self.assertIsNotNone(updated)
        self.assertIsNotNone(reloaded)
        self.assertEqual(loaded["alert_policy_json"], json_dumps(policy))
        self.assertEqual(updated["alert_policy_json"], json_dumps(updated_policy))
        self.assertEqual(reloaded["alert_policy_json"], json_dumps(updated_policy))

    def test_legacy_check_rows_receive_empty_alert_policy_json_on_migration(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            db_path = Path(temp_dir) / "pulseguard.db"
            timestamp = storage.now_iso()
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE checks (
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
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO checks (
                        name, type, enabled, interval_seconds, timeout_ms, entry_url, viewport_mode,
                        method, headers_json, body, assertions_json, setup_script, script, tags, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy policy API",
                        "api",
                        1,
                        300,
                        10000,
                        "https://example.com/legacy",
                        "web",
                        "GET",
                        "{}",
                        "",
                        "[]",
                        "",
                        "",
                        "legacy",
                        timestamp,
                        timestamp,
                    ),
                )

            storage.init_db()
            loaded = storage.get_check(1)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["alert_policy_json"], "{}")


class CheckBatchStorageTests(unittest.TestCase):
    def test_check_tag_set_normalizes_comma_and_whitespace_tags(self) -> None:
        self.assertEqual(storage.check_tag_set(" smoke,Prod api  "), {"smoke", "prod", "api"})

    def test_select_checks_for_batch_matches_type_and_exact_tag_token(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            clear_checks()
            smoke_api = storage.create_check(api_check_data("Smoke API", tags="smoke, prod"))
            storage.create_check(api_check_data("Smoketest API", tags="smoketest"))
            storage.create_check(ui_check_data("Smoke UI", tags="smoke"))

            selected = storage.select_checks_for_batch("api", tag="SMOKE")

        self.assertEqual([item["id"] for item in selected], [smoke_api["id"]])

    def test_select_checks_for_batch_can_limit_to_enabled_checks(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            clear_checks()
            enabled = storage.create_check(api_check_data("Enabled API", tags="batch"))
            disabled = storage.create_check(api_check_data("Disabled API", tags="batch", enabled=False))

            selected_enabled = storage.select_checks_for_batch("api", tag="batch", enabled_only=True)
            selected_all = storage.select_checks_for_batch("api", tag="batch", enabled_only=False)

        self.assertEqual([item["id"] for item in selected_enabled], [enabled["id"]])
        self.assertEqual({item["id"] for item in selected_all}, {enabled["id"], disabled["id"]})

    def test_batch_enabled_and_interval_updates_clean_selected_ids(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            clear_checks()
            first = storage.create_check(api_check_data("First API"))
            second = storage.create_check(api_check_data("Second API"))
            third = storage.create_check(api_check_data("Third API"))

            disabled_count = storage.batch_set_check_enabled([int(first["id"]), int(second["id"]), int(first["id"]), 0, -1], False)
            interval_count = storage.batch_update_check_interval([int(second["id"]), int(third["id"])], 120)
            reloaded = {item["id"]: item for item in storage.list_checks("api")}

        self.assertEqual(disabled_count, 2)
        self.assertEqual(interval_count, 2)
        self.assertFalse(reloaded[first["id"]]["enabled"])
        self.assertFalse(reloaded[second["id"]]["enabled"])
        self.assertTrue(reloaded[third["id"]]["enabled"])
        self.assertEqual(reloaded[second["id"]]["interval_seconds"], 120)
        self.assertEqual(reloaded[third["id"]]["interval_seconds"], 120)


class HeartbeatStorageTests(unittest.TestCase):
    def test_record_heartbeat_upserts_latest_payload(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            first = storage.record_heartbeat("nightly-job", status="ok", message="started", payload={"build": 1})
            second = storage.record_heartbeat("nightly-job", status="failed", message="failed", payload={"build": 2})
            loaded = storage.get_heartbeat("nightly-job")

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["payload"], {"build": 2})
        self.assertEqual(loaded["message"], "failed")
        self.assertEqual(loaded["payload"], {"build": 2})


class RunArchiveStorageTests(unittest.TestCase):
    def test_cleanup_old_data_archives_expired_run_summaries_before_delete(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ), patch("backend.app.storage.cleanup_old_artifacts", return_value={}):
            storage.init_db()
            clear_checks()
            check = storage.create_check(api_check_data("Archive API"))
            check_id = int(check["id"])
            old_day = datetime.now().astimezone().replace(microsecond=0) - timedelta(days=3)
            recent = datetime.now().astimezone().replace(microsecond=0)
            insert_trend_run(check_id, "ok", old_day, 100)
            insert_trend_run(check_id, "failed", old_day + timedelta(hours=1), 300)
            insert_trend_run(check_id, "ok", recent, 500)

            removed = storage.cleanup_old_data({"run_retention_days": 1})
            archives = storage.list_run_archives()
            remaining = storage.list_runs(limit=10)

        archive_by_status = {item["status"]: item for item in archives}
        self.assertEqual(removed, 2)
        self.assertEqual(set(archive_by_status), {"failed", "ok"})
        self.assertEqual(archive_by_status["ok"]["run_count"], 1)
        self.assertEqual(archive_by_status["ok"]["duration_sum_ms"], 100)
        self.assertEqual(archive_by_status["failed"]["duration_sample_count"], 1)
        self.assertEqual([run["status"] for run in remaining], ["ok"])


class AuditAndVersionStorageTests(unittest.TestCase):
    def test_record_audit_event_lists_payload(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            event = storage.record_audit_event("updated", "check", 7, "API", "更新任务", {"field": "name"})
            events = storage.list_audit_events()

        self.assertEqual(event["payload"], {"field": "name"})
        self.assertEqual(events[0]["id"], event["id"])
        self.assertEqual(events[0]["summary"], "更新任务")

    def test_record_check_version_stores_definition_snapshot_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            clear_checks()
            check = storage.create_check(api_check_data("Versioned API", tags="audit"))
            check["current_status"] = "failed"
            version = storage.record_check_version(check, "updated")
            versions = storage.list_check_versions(int(check["id"]))

        self.assertEqual(version["snapshot"]["name"], "Versioned API")
        self.assertEqual(version["snapshot"]["tags"], "audit")
        self.assertNotIn("current_status", version["snapshot"])
        self.assertEqual(versions[0]["id"], version["id"])


class RunnerStorageTests(unittest.TestCase):
    def test_run_metadata_is_persisted_from_create_and_finish(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Runner API"))

            run = storage.create_run(
                {
                    **check,
                    "_runner": {
                        "runner_name": "office-runner",
                        "runner_address": "10.0.0.8",
                        "runner_region": "office-lan",
                        "runner_browser_version": "",
                        "failure_kind": "none",
                    },
                },
                "pending",
            )

            payload = run_payload("failed", "target failed")
            payload.update(
                {
                    "runner_name": "office-runner",
                    "runner_address": "10.0.0.8",
                    "runner_region": "office-lan",
                    "runner_browser_version": "chromium 120.0",
                    "failure_kind": "target",
                }
            )
            finished = storage.finish_run(int(run["id"]), payload)

        self.assertEqual(run["runner_name"], "office-runner")
        self.assertEqual(run["runner_region"], "office-lan")
        self.assertEqual(run["failure_kind"], "none")
        self.assertIsNotNone(finished)
        self.assertEqual(finished["runner_name"], "office-runner")
        self.assertEqual(finished["runner_address"], "10.0.0.8")
        self.assertEqual(finished["runner_region"], "office-lan")
        self.assertEqual(finished["runner_browser_version"], "chromium 120.0")
        self.assertEqual(finished["failure_kind"], "target")

    def test_failed_run_without_failure_kind_defaults_to_target(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            run = storage.create_run(
                {
                    "id": 3,
                    "name": "Legacy failure",
                    "type": "api",
                },
                "failed",
                "legacy failure",
            )
            loaded = storage.get_run(int(run["id"]))

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["failure_kind"], "target")

    def test_probe_runner_heartbeat_upserts_and_lists_metadata(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            first = storage.upsert_probe_runner(
                {
                    "runner_id": "office-1",
                    "name": "Office Runner",
                    "address": "http://10.0.0.8:8787",
                    "network_region": "office-lan",
                    "browser_version": "chromium 120.0",
                    "status": "ok",
                    "metadata": {"capability": "ui"},
                }
            )
            updated = storage.upsert_probe_runner(
                {
                    "runner_id": "office-1",
                    "name": "Office Runner 2",
                    "address": "http://10.0.0.9:8787",
                    "network_region": "office-lan",
                    "browser_version": "chromium 121.0",
                    "status": "warning",
                    "metadata": {"capability": "api"},
                }
            )
            runners = storage.list_probe_runners()

        self.assertEqual(first["runner_id"], "office-1")
        self.assertEqual(updated["name"], "Office Runner 2")
        self.assertEqual(updated["address"], "http://10.0.0.9:8787")
        self.assertEqual(updated["browser_version"], "chromium 121.0")
        self.assertEqual(updated["status"], "warning")
        self.assertEqual(updated["metadata"], {"capability": "api"})
        self.assertEqual([runner["runner_id"] for runner in runners], ["office-1"])


class SettingsVariableStorageTests(unittest.TestCase):
    def test_public_settings_masks_secret_environment_variable_value_but_reports_value_set(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            storage.update_settings(
                {
                    "read_only_token": "read-token-secret-123",
                    "environment_variables": [
                        {"id": "host", "name": "API_HOST", "value": "https://api.example.com", "secret": False},
                        {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True},
                    ]
                }
            )

            raw = storage.get_settings()
            public = storage.get_public_settings()

        raw_variables = {item["id"]: item for item in raw["environment_variables"]}
        public_variables = {item["id"]: item for item in public["environment_variables"]}

        self.assertEqual(raw_variables["token"]["value"], "token-secret-123")
        self.assertEqual(raw["read_only_token"], "read-token-secret-123")
        self.assertEqual(public["read_only_token"], "")
        self.assertTrue(public["read_only_token_set"])
        self.assertEqual(public_variables["host"]["value"], "https://api.example.com")
        self.assertEqual(public_variables["token"]["value"], "")
        self.assertTrue(public_variables["token"]["value_set"])

    def test_secret_environment_variable_empty_update_preserves_existing_value_and_value_clear_removes_it(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            storage.update_settings(
                {
                    "environment_variables": [
                        {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True},
                    ]
                }
            )
            storage.update_settings(
                {
                    "environment_variables": [
                        {"id": "token", "name": "SERVICE_TOKEN", "value": "", "secret": True},
                    ]
                }
            )
            preserved = storage.get_settings()["environment_variables"][0]

            storage.update_settings(
                {
                    "environment_variables": [
                        {"id": "token", "name": "SERVICE_TOKEN", "value": "", "value_clear": True, "secret": True},
                    ]
                }
            )
            cleared = storage.get_settings()["environment_variables"][0]
            public = storage.get_public_settings()["environment_variables"][0]

        self.assertEqual(preserved["value"], "token-secret-123")
        self.assertEqual(cleared["value"], "")
        self.assertFalse(public["value_set"])


def run_payload(status: str, error_message: str | None = None) -> dict[str, object]:
    return {
        "status": status,
        "finished_at": storage.now_iso(),
        "duration_ms": 10,
        "error_message": error_message,
        "error_stack": None,
        "logs": "",
        "screenshot_path": None,
        "trace_path": None,
        "response_path": None,
        "request_snapshot": None,
        "response_snapshot": None,
    }


def insert_trend_run(check_id: int, status: str, started_at: datetime, duration_ms: int | None) -> None:
    timestamp = started_at.isoformat(timespec="seconds")
    finished_at = None if status in {"pending", "running"} else timestamp
    with storage._connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                check_id, check_name, check_type, status, started_at, finished_at,
                duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                check_id,
                "Trend API",
                "api",
                status,
                timestamp,
                finished_at,
                duration_ms,
                timestamp,
            ),
        )


def clear_checks() -> None:
    with storage._connect() as conn:
        conn.execute("DELETE FROM check_status")
        conn.execute("DELETE FROM runs")
        conn.execute("DELETE FROM checks")


def api_check_data(name: str, alert_policy_json: str | None = None, tags: str = "", enabled: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "type": "api",
        "enabled": enabled,
        "interval_seconds": 300,
        "timeout_ms": 10000,
        "entry_url": "https://example.com",
        "method": "GET",
        "headers_json": "{}",
        "body": "",
        "script": "",
        "tags": tags,
    }
    if alert_policy_json is not None:
        payload["alert_policy_json"] = alert_policy_json
    return payload


def ui_check_data(name: str, tags: str = "") -> dict[str, object]:
    return {
        "name": name,
        "type": "ui",
        "enabled": True,
        "interval_seconds": 300,
        "timeout_ms": 15000,
        "entry_url": "https://example.com",
        "viewport_mode": "web",
        "method": "",
        "headers_json": "{}",
        "body": "",
        "assertions_json": "[]",
        "setup_script": "",
        "script": "",
        "tags": tags,
    }


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
