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

    def test_overview_excludes_runner_failures_from_business_failure_metrics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            storage.update_settings({"api_failure_confirmation_count": 1})
            target_check = storage.create_check(api_check_data("Target API"))
            runner_check = storage.create_check(api_check_data("Runner API"))

            target_run = storage.create_run(target_check)
            target_finished = storage.finish_run(int(target_run["id"]), run_payload("failed", "target failed"))
            assert target_finished is not None
            storage.update_check_status(int(target_check["id"]), target_finished)

            runner_run = storage.create_run(
                {
                    **runner_check,
                    "_runner": storage.runner_metadata(
                        {"runner_id": "edge-1", "name": "Edge 1"},
                        failure_kind="runner",
                    ),
                }
            )
            runner_finished = storage.finish_run(
                int(runner_run["id"]),
                {
                    **run_payload("failed", "runner failed"),
                    **storage.runner_metadata({"runner_id": "edge-1", "name": "Edge 1"}, failure_kind="runner"),
                },
            )
            assert runner_finished is not None
            storage.update_check_status(int(runner_check["id"]), runner_finished)

            overview = storage.get_overview()

        trend_24h = {item["check_type"]: item for item in overview["trends"][0]["series"]}
        self.assertEqual(overview["failing_count"], 1)
        self.assertEqual([run["id"] for run in overview["recent_failures"]], [target_run["id"]])
        self.assertEqual(trend_24h["api"]["runs"], 1)
        self.assertEqual(trend_24h["api"]["failure_count"], 1)

    def test_recent_business_incidents_exclude_runner_and_non_health_failures(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Incident API"))
            target_run = storage.create_run(check)
            storage.finish_run(int(target_run["id"]), run_payload("failed", "legacy target failure"))

            runner_run = storage.create_run(
                {
                    **check,
                    "_runner": storage.runner_metadata(
                        {"runner_id": "edge-1", "name": "Edge 1"},
                        failure_kind="runner",
                    ),
                }
            )
            storage.finish_run(
                int(runner_run["id"]),
                {
                    **run_payload("failed", "runner failed"),
                    **storage.runner_metadata({"runner_id": "edge-1", "name": "Edge 1"}, failure_kind="runner"),
                },
            )

            draft_run = storage.create_run({"id": 0, "name": "Draft API", "type": "api"})
            storage.finish_run(int(draft_run["id"]), run_payload("failed", "draft failure"))

            incidents = storage.list_recent_business_incidents(limit=10)

        self.assertEqual([run["id"] for run in incidents], [target_run["id"]])

    def test_overview_trends_split_ui_and_api_windows_and_ignore_invalid_runs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            api_check = storage.create_check(api_check_data("Trend API"))
            ui_check = storage.create_check(ui_check_data("Trend UI"))
            api_check_id = int(api_check["id"])
            ui_check_id = int(ui_check["id"])
            now = datetime.now().astimezone().replace(microsecond=0)

            insert_trend_run(api_check_id, "api", "ok", now - timedelta(hours=1), 100)
            insert_trend_run(api_check_id, "api", "failed", now - timedelta(hours=2), 300)
            insert_trend_run(api_check_id, "api", "timeout", now - timedelta(hours=3), 500)
            insert_trend_run(api_check_id, "api", "failed", now - timedelta(hours=3, minutes=30), 900, failure_kind="runner")
            insert_trend_run(api_check_id, "api", "ok", now - timedelta(hours=4), 700)
            insert_trend_run(api_check_id, "api", "ok", now - timedelta(days=2), 200)
            insert_trend_run(api_check_id, "api", "failed", now - timedelta(days=3), 400)
            insert_trend_run(api_check_id, "api", "ok", now - timedelta(days=4), 600)

            insert_trend_run(ui_check_id, "ui", "ok", now - timedelta(hours=1), 120)
            insert_trend_run(ui_check_id, "ui", "failed", now - timedelta(hours=2), 320)
            insert_trend_run(ui_check_id, "ui", "ok", now - timedelta(days=2), 220)
            insert_trend_run(ui_check_id, "ui", "timeout", now - timedelta(days=3), 420)
            insert_trend_run(ui_check_id, "ui", "ok", now - timedelta(days=4), 620)

            insert_trend_run(api_check_id, "api", "ok", now - timedelta(days=8), 999)
            insert_trend_run(ui_check_id, "ui", "ok", now - timedelta(days=8), 998)
            insert_trend_run(0, "api", "failed", now - timedelta(hours=5), 1)
            insert_trend_run(-10, "ui", "ok", now - timedelta(hours=6), 2)
            insert_trend_run(api_check_id, "api", "skipped", now - timedelta(hours=7), 3)
            insert_trend_run(api_check_id, "api", "running", now - timedelta(hours=8), 4)
            insert_trend_run(ui_check_id, "ui", "pending", now - timedelta(hours=9), 5)
            insert_trend_run(api_check_id, "api", "failed", now + timedelta(hours=1), 800)

            overview = storage.get_overview()

        trends = {item["key"]: item for item in overview["trends"]}
        trend_24h = {item["check_type"]: item for item in trends["24h"]["series"]}
        trend_7d = {item["check_type"]: item for item in trends["7d"]["series"]}

        self.assertEqual(set(trends), {"24h", "7d"})
        self.assertEqual(set(trend_24h), {"ui", "api"})
        self.assertEqual(trend_24h["ui"]["label"], "UI")
        self.assertEqual(trend_24h["api"]["label"], "API")
        self.assertNotIn("runs", trends["24h"])
        self.assertEqual(trend_24h["api"]["runs"], 4)
        self.assertEqual(trend_24h["api"]["success_count"], 2)
        self.assertEqual(trend_24h["api"]["success_rate"], 50.0)
        self.assertEqual(trend_24h["api"]["failure_count"], 2)
        self.assertEqual(trend_24h["api"]["duration_p50_ms"], 300)
        self.assertEqual(trend_24h["api"]["duration_p95_ms"], 700)
        self.assertEqual(trend_24h["ui"]["runs"], 2)
        self.assertEqual(trend_24h["ui"]["success_count"], 1)
        self.assertEqual(trend_24h["ui"]["success_rate"], 50.0)
        self.assertEqual(trend_24h["ui"]["failure_count"], 1)
        self.assertEqual(trend_24h["ui"]["duration_p50_ms"], 120)
        self.assertEqual(trend_24h["ui"]["duration_p95_ms"], 320)
        self.assertEqual(trend_7d["api"]["runs"], 7)
        self.assertEqual(trend_7d["api"]["success_rate"], 57.1)
        self.assertEqual(trend_7d["api"]["failure_count"], 3)
        self.assertEqual(trend_7d["api"]["duration_p50_ms"], 400)
        self.assertEqual(trend_7d["api"]["duration_p95_ms"], 700)
        self.assertEqual(trend_7d["ui"]["runs"], 5)
        self.assertEqual(trend_7d["ui"]["success_rate"], 60.0)
        self.assertEqual(trend_7d["ui"]["failure_count"], 2)
        self.assertEqual(trend_7d["ui"]["duration_p50_ms"], 320)
        self.assertEqual(trend_7d["ui"]["duration_p95_ms"], 620)

    def test_overview_trends_return_empty_metrics_without_duration_samples(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Sparse Trend API"))
            now = datetime.now().astimezone().replace(microsecond=0)
            insert_trend_run(int(check["id"]), "api", "ok", now - timedelta(hours=1), None)

            overview = storage.get_overview()

        trends = {item["key"]: item for item in overview["trends"]}
        series = {item["check_type"]: item for item in trends["24h"]["series"]}
        self.assertEqual(series["api"]["runs"], 1)
        self.assertEqual(series["api"]["success_rate"], 100.0)
        self.assertEqual(series["api"]["failure_count"], 0)
        self.assertIsNone(series["api"]["duration_p50_ms"])
        self.assertIsNone(series["api"]["duration_p95_ms"])
        self.assertEqual(series["ui"]["runs"], 0)
        self.assertIsNone(series["ui"]["success_rate"])
        self.assertEqual(series["ui"]["failure_count"], 0)
        self.assertIsNone(series["ui"]["duration_p50_ms"])
        self.assertIsNone(series["ui"]["duration_p95_ms"])

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

    def test_ui_check_browser_selection_fields_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(
                {
                    **ui_check_data("Browser matrix UI"),
                    "browser_selection_mode": "round_robin_all",
                    "browser_types": ["firefox", "chromium"],
                }
            )
            loaded = storage.get_check(int(check["id"]))

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["browser_selection_mode"], "round_robin_all")
        self.assertEqual(loaded["browser_types"], ["firefox", "chromium"])

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

    def test_member_settings_support_multiple_channels_and_prune_deleted_task_references(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            members = [
                {
                    "id": "alice",
                    "name": "Alice",
                    "feishu_open_id": "ou_alice",
                    "wecom_user_id": "alice.wx",
                    "wecom_mobile": "13800000001",
                    "dingtalk_user_id": "alice.ding",
                    "dingtalk_mobile": "13900000001",
                },
                {
                    "id": "bob",
                    "name": "Bob",
                    "feishu_open_id": "ou_bob",
                    "wecom_user_id": "",
                    "wecom_mobile": "",
                    "dingtalk_user_id": "",
                    "dingtalk_mobile": "",
                },
            ]
            storage.update_settings({"members": members})
            check = storage.create_check(
                api_check_data(
                    "Member policy API",
                    alert_policy_json=json_dumps({"member_ids": ["alice", "bob"]}),
                )
            )

            storage.update_settings({"members": [members[1]]})
            loaded = storage.get_check(int(check["id"]))
            saved_members = storage.get_settings()["members"]

        self.assertEqual(saved_members, [members[1]])
        self.assertEqual(json.loads(loaded["alert_policy_json"])["member_ids"], ["bob"])


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
            insert_trend_run(check_id, "api", "ok", old_day, 100)
            insert_trend_run(check_id, "api", "failed", old_day + timedelta(hours=1), 300)
            insert_trend_run(check_id, "api", "ok", recent, 500)

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

    def test_runs_can_be_filtered_by_run_group_id_for_multi_runner_results(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            check = storage.create_check(api_check_data("Grouped Runner API"))
            first = storage.create_run(
                {
                    **check,
                    "_runner": storage.runner_metadata({"runner_id": "edge-1", "name": "Edge 1"}),
                    "_run": {**storage.run_metadata("manual"), "run_group_id": "rg-test-1"},
                },
                "pending",
            )
            second = storage.create_run(
                {
                    **check,
                    "_runner": storage.runner_metadata({"runner_id": "edge-2", "name": "Edge 2"}),
                    "_run": {**storage.run_metadata("manual"), "run_group_id": "rg-test-1"},
                },
                "pending",
            )
            other = storage.create_run(
                {
                    **check,
                    "_runner": storage.runner_metadata({"runner_id": "edge-3", "name": "Edge 3"}),
                    "_run": {**storage.run_metadata("manual"), "run_group_id": "rg-test-2"},
                },
                "pending",
            )
            storage.finish_run(int(first["id"]), {**run_payload("ok"), **storage.runner_metadata({"runner_id": "edge-1", "name": "Edge 1"})})
            storage.finish_run(int(second["id"]), {**run_payload("failed", "target failed"), **storage.runner_metadata({"runner_id": "edge-2", "name": "Edge 2"}, failure_kind="target")})
            storage.finish_run(int(other["id"]), {**run_payload("ok"), **storage.runner_metadata({"runner_id": "edge-3", "name": "Edge 3"})})

            grouped = storage.list_runs({"run_group_id": "rg-test-1"}, limit=10)
            grouped_page = storage.list_runs_page({"run_group_id": "rg-test-1"}, page=1, page_size=10)

        self.assertEqual({run["runner_id"] for run in grouped}, {"edge-1", "edge-2"})
        self.assertEqual(grouped_page["total"], 2)
        self.assertEqual({run["runner_id"] for run in grouped_page["items"]}, {"edge-1", "edge-2"})
        self.assertNotIn("logs", grouped_page["items"][0])
        self.assertNotIn("error_stack", grouped_page["items"][0])
        self.assertNotIn("request_snapshot", grouped_page["items"][0])
        self.assertNotIn("response_snapshot", grouped_page["items"][0])

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
        self.assertEqual({runner["runner_id"] for runner in runners}, {"local", "office-1"})

    def test_probe_runner_browser_types_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            runner = storage.upsert_probe_runner(
                {
                    "runner_id": "office-1",
                    "name": "Office Runner",
                    "address": "http://10.0.0.8:8787",
                    "network_region": "office-lan",
                    "browser_version": "chromium 120.0",
                    "installed_browser_types": ["chromium", "firefox"],
                    "available_browser_types": ["chromium"],
                    "status": "ok",
                    "metadata": {},
                }
            )

        self.assertEqual(runner["installed_browser_types"], ["chromium", "firefox"])
        self.assertEqual(runner["available_browser_types"], ["chromium"])
        self.assertTrue(runner["browser_type_status"]["chromium"]["installed"])

    def test_local_runner_update_persists_to_settings(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            updated = storage.update_probe_runner(
                "local",
                {
                    "name": "Main Node",
                    "address": "http://127.0.0.1:8787",
                    "network_region": "office",
                    "enabled": True,
                },
            )
            settings = storage.get_settings()
            storage.init_db()
            reloaded = storage.get_probe_runner("local")

        self.assertIsNotNone(updated)
        self.assertEqual(settings["local_runner_name"], "Main Node")
        self.assertEqual(settings["local_runner_address"], "http://127.0.0.1:8787")
        self.assertEqual(settings["local_runner_region"], "office")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["name"], "Main Node")
        self.assertEqual(reloaded["address"], "http://127.0.0.1:8787")
        self.assertEqual(reloaded["network_region"], "office")

    def test_managed_runner_supplied_token_is_hidden_and_rotation_invalidates_old_token(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            created = storage.create_probe_runner(
                {
                    "runner_id": "edge-1",
                    "name": "Edge Runner",
                    "address": "http://10.0.0.8:8787",
                    "token": "runner-secret-1",
                }
            )
            public = storage.get_probe_runner("edge-1")
            listed = next(runner for runner in storage.list_probe_runners() if runner["runner_id"] == "edge-1")
            verified = storage.verify_probe_runner_token("edge-1", "runner-secret-1")
            rotated = storage.rotate_probe_runner_token("edge-1")
            old_verified = storage.verify_probe_runner_token("edge-1", "runner-secret-1")
            new_verified = storage.verify_probe_runner_token("edge-1", str(rotated["token"]))

        self.assertNotIn("token", created)
        self.assertIsNotNone(public)
        self.assertNotIn("token", public)
        self.assertNotIn("token_value", public)
        self.assertTrue(public["token_set"])
        self.assertEqual(public["token_hint"], "cret-1")
        self.assertNotIn("token", listed)
        self.assertIsNotNone(verified)
        self.assertIsNone(old_verified)
        self.assertIsNotNone(new_verified)
        self.assertNotEqual(rotated["token"], "runner-secret-1")

    def test_runner_unavailable_notification_is_deduped_until_recovery(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            storage.create_probe_runner(
                {
                    "runner_id": "edge-2",
                    "name": "Edge Runner",
                    "address": "http://10.0.0.9:8787",
                    "token": "runner-secret-2",
                }
            )
            unavailable = storage.mark_probe_runner_unavailable("edge-2")
            should_notify_first = storage.should_notify_probe_runner_unavailable(unavailable or {})
            notified = storage.mark_probe_runner_unavailable_notified("edge-2")
            should_notify_second = storage.should_notify_probe_runner_unavailable(notified or {})
            recovered = storage.mark_probe_runner_available(
                "edge-2",
                {"browser_version": "chromium 120", "status": "ok", "metadata": {"source": "poll"}},
            )
            unavailable_again = storage.mark_probe_runner_unavailable("edge-2")
            should_notify_after_recovery = storage.should_notify_probe_runner_unavailable(unavailable_again or {})

        self.assertTrue(should_notify_first)
        self.assertFalse(should_notify_second)
        self.assertTrue(recovered["available"])
        self.assertEqual(recovered["metadata"], {"source": "poll"})
        self.assertIsNone(recovered["unavailable_notified_at"])
        self.assertTrue(should_notify_after_recovery)

    def test_runner_cursor_round_robins_per_scope(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            first_scope = [storage.next_runner_cursor("check:1", 3) for _ in range(5)]
            second_scope = [storage.next_runner_cursor("check:2", 2) for _ in range(3)]

        self.assertEqual(first_scope, [0, 1, 2, 0, 1])
        self.assertEqual(second_scope, [0, 1, 0])


class DeploymentStorageTests(unittest.TestCase):
    def test_deployment_window_discards_interrupted_runs_on_startup(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            clear_checks()
            check = storage.create_check(api_check_data("Deploy API"))
            completed = storage.create_run(check)
            storage.finish_run(int(completed["id"]), run_payload("ok"))
            pending = storage.create_run(check, "pending")
            running = storage.create_run(check, "pending")
            storage.start_run(int(running["id"]))

            state = storage.start_deployment_window("unit-test")
            storage.init_db()
            remaining_runs = storage.list_runs(limit=10)
            deployment = storage.get_deployment_state()

        self.assertTrue(state["active"])
        self.assertTrue(deployment["active"])
        self.assertEqual({run["id"] for run in remaining_runs}, {completed["id"]})
        self.assertNotIn(pending["id"], {run["id"] for run in remaining_runs})
        self.assertNotIn(running["id"], {run["id"] for run in remaining_runs})

    def test_deployment_window_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ):
            storage.init_db()
            started = storage.start_deployment_window("unit-test")
            active = storage.get_deployment_state()
            finished = storage.finish_deployment_window()
            inactive = storage.get_deployment_state()

        self.assertTrue(started["active"])
        self.assertTrue(active["active"])
        self.assertEqual(active["reason"], "unit-test")
        self.assertFalse(finished["active"])
        self.assertFalse(inactive["active"])
        self.assertIsNotNone(inactive["finished_at"])


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


def insert_trend_run(
    check_id: int,
    check_type: str,
    status: str,
    started_at: datetime,
    duration_ms: int | None,
    failure_kind: str | None = None,
) -> None:
    timestamp = started_at.isoformat(timespec="seconds")
    finished_at = None if status in {"pending", "running"} else timestamp
    with storage._connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                check_id, check_name, check_type, status, started_at, finished_at,
                duration_ms, failure_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                check_id,
                "Trend UI" if check_type == "ui" else "Trend API",
                check_type,
                status,
                timestamp,
                finished_at,
                duration_ms,
                failure_kind,
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
