from __future__ import annotations

import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
