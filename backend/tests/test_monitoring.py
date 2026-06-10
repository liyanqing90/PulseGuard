from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import storage
from backend.app.monitoring import next_health_state, run_metadata


class MonitoringStateTests(unittest.TestCase):
    def test_only_draft_runs_do_not_affect_health(self) -> None:
        for trigger in ("scheduled", "confirm-recovery", "manual", "manual-batch", "rerun:12", "cli"):
            with self.subTest(trigger=trigger):
                metadata = run_metadata(trigger)
                self.assertTrue(metadata["affects_health"])
                self.assertEqual(metadata["observation_kind"], "observation")

        draft = run_metadata("draft-debug")
        self.assertFalse(draft["affects_health"])
        self.assertEqual(draft["observation_kind"], "draft")

    def test_target_failures_require_confirmation(self) -> None:
        settings = {"api_failure_confirmation_count": 2, "recovery_confirmation_count": 2}
        first = next_health_state(None, {"status": "failed", "failure_kind": "target", "check_type": "api"}, settings)
        second = next_health_state(
            {"monitor_status": first["current_status"], "consecutive_failures": first["consecutive_failures"]},
            {"status": "failed", "failure_kind": "target", "check_type": "api"},
            settings,
        )
        self.assertEqual(first["current_status"], "suspected_failing")
        self.assertEqual(second["current_status"], "failing")

    def test_ui_failures_use_ui_confirmation_threshold(self) -> None:
        settings = {"ui_failure_confirmation_count": 3, "recovery_confirmation_count": 2}
        first = next_health_state(None, {"status": "failed", "failure_kind": "target", "check_type": "ui"}, settings)
        second = next_health_state(
            {"monitor_status": first["current_status"], "consecutive_failures": first["consecutive_failures"]},
            {"status": "failed", "failure_kind": "target", "check_type": "ui"},
            settings,
        )
        third = next_health_state(
            {"monitor_status": second["current_status"], "consecutive_failures": second["consecutive_failures"]},
            {"status": "failed", "failure_kind": "target", "check_type": "ui"},
            settings,
        )
        self.assertEqual(first["current_status"], "suspected_failing")
        self.assertEqual(second["current_status"], "suspected_failing")
        self.assertEqual(third["current_status"], "failing")

    def test_runner_failure_becomes_unknown(self) -> None:
        state = next_health_state(
            {"monitor_status": "healthy", "consecutive_failures": 0},
            {"status": "failed", "failure_kind": "runner"},
            {"api_failure_confirmation_count": 1},
        )
        self.assertEqual(state["current_status"], "unknown")
        self.assertEqual(state["consecutive_failures"], 0)

    def test_first_success_becomes_healthy_without_recovery_confirmation(self) -> None:
        state = next_health_state(
            {"monitor_status": "unknown", "consecutive_successes": 0},
            {"status": "ok", "failure_kind": "none", "check_type": "api", "trigger": "scheduled"},
            {"recovery_confirmation_count": 2},
        )
        self.assertEqual(state["current_status"], "healthy")

    def test_confirm_recovery_is_explicit_and_immediate(self) -> None:
        state = next_health_state(
            {"monitor_status": "failing", "consecutive_failures": 3},
            {"status": "ok", "failure_kind": "none", "trigger": "confirm-recovery"},
            {"recovery_confirmation_count": 3},
        )
        self.assertEqual(state["current_status"], "healthy")

    def test_recovery_stays_failing_until_confirmation_completes(self) -> None:
        settings = {"recovery_confirmation_count": 2}
        first = next_health_state(
            {"monitor_status": "failing", "consecutive_failures": 3},
            {"status": "ok", "failure_kind": "none", "trigger": "scheduled"},
            settings,
        )
        second = next_health_state(
            {"monitor_status": first["current_status"], "consecutive_successes": first["consecutive_successes"]},
            {"status": "ok", "failure_kind": "none", "trigger": "scheduled"},
            settings,
        )
        self.assertEqual(first["current_status"], "suspected_recovery")
        self.assertEqual(second["previous_status"], "suspected_recovery")
        self.assertEqual(second["current_status"], "healthy")


class MonitoringStorageTests(unittest.TestCase):
    def test_run_pagination_filters_observation_kind_and_backup_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.object(
            storage, "DB_PATH", Path(temp_dir) / "pulseguard.db"
        ), patch.object(storage, "BACKUPS_DIR", Path(temp_dir) / "backups"):
            storage.init_db()
            check = storage.list_checks("api")[0]
            observation = storage.create_run({**check, "_run": run_metadata("scheduled")}, "skipped")
            draft = storage.create_run({**check, "id": 0, "_run": run_metadata("draft-debug")}, "skipped")

            page = storage.list_runs_page({"observation_kind": "observation"}, page=1, page_size=10)
            backup = storage.create_database_backup()
            added = storage.create_check(
                {
                    "name": "Restore marker",
                    "type": "api",
                    "enabled": True,
                    "interval_seconds": 300,
                    "timeout_ms": 10000,
                    "entry_url": "https://example.com/restore-marker",
                    "method": "GET",
                    "headers_json": "{}",
                    "body": "",
                    "assertions_json": "[]",
                    "setup_script": "",
                    "script": "async def check(ctx):\n    pass\n",
                    "tags": "",
                }
            )
            storage.restore_database_backup(backup["filename"])
            restored_marker = storage.get_check(int(added["id"]))
            backups = storage.list_database_backups()

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], observation["id"])
        self.assertNotEqual(page["items"][0]["id"], draft["id"])
        self.assertIsNone(restored_marker)
        self.assertGreaterEqual(len(backups), 2)
