from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


class FakeConcurrentRunner:
    def __init__(self) -> None:
        self.running = 0
        self.max_running = 0

    async def run_check(self, check_id: int, trigger: str = "manual") -> dict[str, object]:
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(0.01)
            return {"id": check_id, "check_id": check_id, "trigger": trigger}
        finally:
            self.running -= 1


class FakeInspectRunner:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    async def inspect_ui_rules(self, payload: dict[str, object]) -> dict[str, object]:
        self.payload = payload
        return {
            "title": "Example",
            "url": payload["entry_url"],
            "results": [{"id": "visible", "type": "element_visible", "selector": "#app", "status": "ok", "count": 1, "message": "selector 当前匹配正常"}],
        }


class FakeScheduler:
    def __init__(self) -> None:
        self.synced: list[int] = []

    def sync_check(self, check_id: int) -> None:
        self.synced.append(check_id)


class RunAllRouteTests(unittest.TestCase):
    def test_run_all_submits_enabled_checks_concurrently(self) -> None:
        runner = FakeConcurrentRunner()

        with patch.object(app.state, "runner", runner, create=True), patch(
            "backend.app.main.storage.list_checks",
            return_value=[
                {"id": 1, "name": "API 1", "type": "api"},
                {"id": 2, "name": "API 2", "type": "api"},
            ],
        ) as list_checks:
            response = TestClient(app).post("/api/checks/run-all?type=api")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([run["check_id"] for run in response.json()["runs"]], [1, 2])
        self.assertGreaterEqual(runner.max_running, 2)
        list_checks.assert_called_once_with("api", enabled_only=True)

    def test_batch_enable_route_uses_tag_selection_and_syncs_matches(self) -> None:
        scheduler = FakeScheduler()
        checks = [
            {"id": 1, "name": "API 1", "type": "api"},
            {"id": 2, "name": "API 2", "type": "api"},
        ]

        with patch.object(app.state, "scheduler", scheduler, create=True), patch(
            "backend.app.main.storage.select_checks_for_batch",
            return_value=checks,
        ) as select_checks, patch(
            "backend.app.main.storage.batch_set_check_enabled",
            return_value=2,
        ) as batch_set_enabled, patch(
            "backend.app.main.storage.record_audit_event"
        ) as record_audit_event:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "enable", "type": "api", "tag": "smoke", "expected_count": 2},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"matched": 2, "changed": 2, "ids": [1, 2], "runs": []})
        select_checks.assert_called_once_with("api", "smoke", enabled_only=False)
        batch_set_enabled.assert_called_once_with([1, 2], True)
        record_audit_event.assert_called_once()
        self.assertEqual(scheduler.synced, [1, 2])

    def test_batch_disable_route_updates_storage_and_syncs_matches(self) -> None:
        scheduler = FakeScheduler()

        with patch.object(app.state, "scheduler", scheduler, create=True), patch(
            "backend.app.main.storage.select_checks_for_batch",
            return_value=[{"id": 5, "name": "API 5", "type": "api"}],
        ) as select_checks, patch(
            "backend.app.main.storage.batch_set_check_enabled",
            return_value=1,
        ) as batch_set_enabled, patch(
            "backend.app.main.storage.record_audit_event"
        ) as record_audit_event:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "disable", "type": "api", "tag": "smoke", "expected_count": 1},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"matched": 1, "changed": 1, "ids": [5], "runs": []})
        select_checks.assert_called_once_with("api", "smoke", enabled_only=False)
        batch_set_enabled.assert_called_once_with([5], False)
        record_audit_event.assert_called_once()
        self.assertEqual(scheduler.synced, [5])

    def test_batch_update_interval_route_syncs_matches(self) -> None:
        scheduler = FakeScheduler()

        with patch.object(app.state, "scheduler", scheduler, create=True), patch(
            "backend.app.main.storage.select_checks_for_batch",
            return_value=[{"id": 3, "name": "UI 1", "type": "ui"}],
        ) as select_checks, patch(
            "backend.app.main.storage.batch_update_check_interval",
            return_value=1,
        ) as batch_update_interval, patch(
            "backend.app.main.storage.record_audit_event"
        ) as record_audit_event:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "update_interval", "type": "ui", "tag": "", "expected_count": 1, "interval_seconds": 600},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"matched": 1, "changed": 1, "ids": [3], "runs": []})
        select_checks.assert_called_once_with("ui", "", enabled_only=False)
        batch_update_interval.assert_called_once_with([3], 600)
        record_audit_event.assert_called_once()
        self.assertEqual(scheduler.synced, [3])

    def test_batch_update_interval_requires_interval_seconds(self) -> None:
        with patch("backend.app.main.storage.select_checks_for_batch") as select_checks:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "update_interval", "type": "api", "expected_count": 1},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("批量调整频率必须提供执行频率", response.json()["detail"])
        select_checks.assert_not_called()

    def test_batch_run_route_uses_enabled_selection_and_manual_batch_trigger(self) -> None:
        runner = FakeConcurrentRunner()
        checks = [
            {"id": 1, "name": "API 1", "type": "api"},
            {"id": 2, "name": "API 2", "type": "api"},
        ]

        with patch.object(app.state, "runner", runner, create=True), patch(
            "backend.app.main.storage.select_checks_for_batch",
            return_value=checks,
        ) as select_checks:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "run", "type": "api", "tag": "smoke", "expected_count": 2},
            )

        body: dict[str, Any] = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["matched"], 2)
        self.assertEqual(body["changed"], 0)
        self.assertEqual(body["ids"], [1, 2])
        self.assertEqual([run["trigger"] for run in body["runs"]], ["manual-batch", "manual-batch"])
        self.assertGreaterEqual(runner.max_running, 2)
        select_checks.assert_called_once_with("api", "smoke", enabled_only=True)

    def test_batch_route_rejects_stale_expected_count(self) -> None:
        with patch(
            "backend.app.main.storage.select_checks_for_batch",
            return_value=[{"id": 1, "name": "API 1", "type": "api"}],
        ), patch("backend.app.main.storage.batch_set_check_enabled") as batch_set_enabled:
            response = TestClient(app).post(
                "/api/checks/batch",
                json={"action": "disable", "type": "api", "tag": "smoke", "expected_count": 2},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("命中数量已变化", response.json()["detail"])
        batch_set_enabled.assert_not_called()

    def test_inspect_ui_rules_route_delegates_to_runner(self) -> None:
        runner = FakeInspectRunner()
        payload = {
            "type": "ui",
            "entry_url": "https://example.com",
            "timeout_ms": 15000,
            "viewport_mode": "web",
            "viewport_width": 1440,
            "viewport_height": 900,
            "setup_script": "",
            "assertions_json": '[{"id":"visible","type":"element_visible","selector":"#app"}]',
        }

        with patch.object(app.state, "runner", runner, create=True), patch("backend.app.main.storage.get_settings", return_value={}):
            response = TestClient(app).post("/api/checks/inspect-ui-rules", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "ok")
        self.assertEqual(json.loads(str(runner.payload["assertions_json"])), json.loads(payload["assertions_json"]))


class HeartbeatRouteTests(unittest.TestCase):
    def test_record_heartbeat_route_persists_json_payload(self) -> None:
        heartbeat = {
            "key": "nightly-job",
            "status": "ok",
            "message": "done",
            "payload": {"build": 42},
            "received_at": "2026-06-08T12:00:00+08:00",
            "updated_at": "2026-06-08T12:00:00+08:00",
        }

        with patch("backend.app.main.storage.get_settings", return_value={}), patch(
            "backend.app.main.storage.record_heartbeat", return_value=heartbeat
        ) as record_heartbeat:
            response = TestClient(app).post(
                "/api/heartbeats/nightly-job",
                json={"status": "ok", "message": "done", "payload": {"build": 42}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["heartbeat"]["payload"], {"build": 42})
        record_heartbeat.assert_called_once_with("nightly-job", status="ok", message="done", payload={"build": 42})

    def test_heartbeat_routes_mask_sensitive_payload_fields(self) -> None:
        settings = {"read_only_token": "read-token-123", "environment_variables": []}
        heartbeat = {
            "key": "nightly-job",
            "status": "ok",
            "message": "read-token-123 done",
            "payload": {"Authorization": "Bearer literal-token", "build": 42},
            "received_at": "2026-06-08T12:00:00+08:00",
            "updated_at": "2026-06-08T12:00:00+08:00",
        }

        with patch("backend.app.main.storage.get_settings", return_value=settings), patch(
            "backend.app.main.storage.record_heartbeat", return_value=heartbeat
        ) as record_heartbeat:
            response = TestClient(app).post(
                "/api/heartbeats/nightly-job",
                json={"status": "ok", "message": "read-token-123 done", "payload": {"Authorization": "Bearer literal-token", "build": 42}},
            )

        self.assertEqual(response.status_code, 200)
        record_heartbeat.assert_called_once_with("nightly-job", status="ok", message="*** done", payload={"Authorization": "***", "build": 42})
        response_text = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn("read-token-123", response_text)
        self.assertNotIn("Bearer literal-token", response_text)

        with patch("backend.app.main.storage.get_settings", return_value=settings), patch(
            "backend.app.main.storage.get_heartbeat", return_value=heartbeat
        ):
            detail = TestClient(app).get("/api/heartbeats/nightly-job")

        self.assertEqual(detail.status_code, 200)
        detail_text = json.dumps(detail.json(), ensure_ascii=False)
        self.assertNotIn("read-token-123", detail_text)
        self.assertNotIn("Bearer literal-token", detail_text)

    def test_record_heartbeat_route_rejects_invalid_status(self) -> None:
        response = TestClient(app).post("/api/heartbeats/nightly-job", json={"status": "unknown"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("心跳状态必须是 ok 或 failed", response.json()["detail"])

    def test_heartbeat_detail_route_returns_404_when_missing(self) -> None:
        with patch("backend.app.main.storage.get_heartbeat", return_value=None):
            response = TestClient(app).get("/api/heartbeats/missing-job")

        self.assertEqual(response.status_code, 404)


class RunnerRouteTests(unittest.TestCase):
    def test_runner_heartbeat_route_upserts_runner(self) -> None:
        runner = {
            "runner_id": "office-1",
            "name": "Office Runner",
            "address": "http://10.0.0.8:8787",
            "network_region": "office-lan",
            "browser_version": "chromium 120.0",
            "status": "ok",
            "metadata": {"capability": "ui"},
            "last_seen_at": "2026-06-08T12:00:00+08:00",
            "updated_at": "2026-06-08T12:00:00+08:00",
        }

        with patch("backend.app.main.storage.upsert_probe_runner", return_value=runner) as upsert_probe_runner, patch(
            "backend.app.main.storage.get_settings", return_value={}
        ):
            response = TestClient(app).post(
                "/api/runners/heartbeat",
                json={
                    "runner_id": "office-1",
                    "name": "Office Runner",
                    "address": "http://10.0.0.8:8787",
                    "network_region": "office-lan",
                    "browser_version": "chromium 120.0",
                    "status": "ok",
                    "metadata": {"capability": "ui"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["runner"]["runner_id"], "office-1")
        upsert_probe_runner.assert_called_once()
        self.assertEqual(upsert_probe_runner.call_args.args[0]["network_region"], "office-lan")

    def test_runners_route_lists_probe_runners(self) -> None:
        runners = [
            {
                "runner_id": "office-1",
                "name": "Office Runner",
                "address": "http://10.0.0.8:8787",
                "network_region": "office-lan",
                "browser_version": "chromium 120.0",
                "status": "ok",
                "metadata": {},
                "last_seen_at": "2026-06-08T12:00:00+08:00",
                "updated_at": "2026-06-08T12:00:00+08:00",
            }
        ]

        with patch("backend.app.main.storage.list_probe_runners", return_value=runners) as list_probe_runners, patch(
            "backend.app.main.storage.get_settings", return_value={}
        ):
            response = TestClient(app).get("/api/runners?limit=10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["runner_id"], "office-1")
        list_probe_runners.assert_called_once_with(limit=10)


class OperationsRouteTests(unittest.TestCase):
    def test_status_page_returns_sanitized_internal_snapshot(self) -> None:
        settings = {
            "maintenance_enabled": True,
            "maintenance_title": "DB maintenance",
            "maintenance_message": "Read-only window",
            "maintenance_starts_at": "2026-06-08T22:00:00+08:00",
            "maintenance_ends_at": "2026-06-08T23:00:00+08:00",
            "environment_variables": [
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True}
            ],
        }
        checks = [
            {
                "id": 1,
                "name": "API",
                "type": "api",
                "enabled": True,
                "tags": "public",
                "current_status": "failed",
                "last_run_at": "2026-06-08T12:00:00+08:00",
                "last_error": "token-secret-123 failed",
                "headers_json": '{"Authorization":"Bearer token-secret-123"}',
                "script": "async def check(ctx): pass",
            }
        ]
        runs = [
            {
                "id": 2,
                "check_id": 1,
                "check_name": "API",
                "check_type": "api",
                "status": "failed",
                "started_at": "2026-06-08T12:00:00+08:00",
                "duration_ms": 120,
                "failure_kind": "target",
                "runner_name": "local",
                "runner_region": "local",
                "error_message": "token-secret-123 failed",
                "error_stack": "secret stack",
                "response_snapshot": '{"body":"token-secret-123"}',
            }
        ]

        with patch("backend.app.main.storage.get_settings", return_value=settings), patch(
            "backend.app.main.storage.get_overview", return_value={"failing_count": 1, "today_runs": 3}
        ), patch("backend.app.main.storage.list_checks", return_value=checks), patch(
            "backend.app.main.storage.list_runs", return_value=runs
        ):
            response = TestClient(app).get("/api/status-page")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["maintenance"]["enabled"])
        self.assertEqual(payload["summary"]["checks_failing"], 1)
        self.assertEqual(payload["checks"][0]["status"], "failed")
        self.assertEqual(payload["recent_incidents"][0]["failure_kind"], "target")
        payload_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("token-secret-123", payload_text)
        self.assertNotIn("headers_json", payload_text)
        self.assertNotIn("script", payload_text)
        self.assertNotIn("error_stack", payload_text)

    def test_status_page_excludes_manual_verification_failures(self) -> None:
        runs = [
            {
                "id": 2,
                "check_id": 1,
                "check_name": "API",
                "check_type": "api",
                "status": "failed",
                "started_at": "2026-06-08T12:00:00+08:00",
                "failure_kind": "target",
                "affects_health": False,
            }
        ]

        with patch("backend.app.main.storage.get_settings", return_value={}), patch(
            "backend.app.main.storage.get_overview", return_value={}
        ), patch("backend.app.main.storage.list_checks", return_value=[]), patch(
            "backend.app.main.storage.list_runs", return_value=runs
        ):
            response = TestClient(app).get("/api/status-page")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recent_incidents"], [])

    def test_read_only_snapshot_requires_configured_token(self) -> None:
        with patch("backend.app.main.storage.get_settings", return_value={"read_only_token": ""}):
            unconfigured = TestClient(app).get("/api/read-only/snapshot")

        self.assertEqual(unconfigured.status_code, 403)

        with patch("backend.app.main.storage.get_settings", return_value={"read_only_token": "secret"}):
            denied = TestClient(app).get("/api/read-only/snapshot?token=wrong")

        self.assertEqual(denied.status_code, 403)

        settings = {
            "read_only_token": "secret",
            "environment_variables": [
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True}
            ],
        }
        checks = [{"id": 1, "headers_json": '{"Authorization":"Bearer token-secret-123"}'}]
        runs = [{"id": 2, "response_snapshot": '{"body":"token-secret-123"}'}]
        overview = {
            "today_runs": 1,
            "latest_run": {
                "id": 3,
                "check_id": 1,
                "check_name": "API",
                "check_type": "api",
                "status": "failed",
                "error_stack": "stack token-secret-123",
                "response_snapshot": '{"body":"token-secret-123"}',
            },
            "recent_failures": [
                {
                    "id": 4,
                    "check_id": 1,
                    "check_name": "API",
                    "check_type": "api",
                    "status": "failed",
                    "logs": "token-secret-123",
                    "request_snapshot": '{"headers":{"Authorization":"token-secret-123"}}',
                }
            ],
        }
        with patch("backend.app.main.storage.get_settings", return_value=settings), patch(
            "backend.app.main.storage.get_overview", return_value=overview
        ), patch("backend.app.main.storage.list_checks", return_value=checks), patch("backend.app.main.storage.list_runs", return_value=runs):
            allowed = TestClient(app).get("/api/read-only/snapshot?token=secret")

        self.assertEqual(allowed.status_code, 200)
        payload = allowed.json()
        self.assertEqual(payload["overview"]["today_runs"], 1)
        payload_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("token-secret-123", payload_text)
        self.assertNotIn("headers_json", payload_text)
        self.assertNotIn("response_snapshot", payload_text)
        self.assertNotIn("request_snapshot", payload_text)
        self.assertNotIn("error_stack", payload_text)
        self.assertNotIn("logs", payload_text)

    def test_read_only_snapshot_accepts_bearer_token(self) -> None:
        with patch("backend.app.main.storage.get_settings", return_value={"read_only_token": "secret"}), patch(
            "backend.app.main.storage.get_overview", return_value={"today_runs": 1}
        ), patch("backend.app.main.storage.list_checks", return_value=[]), patch("backend.app.main.storage.list_runs", return_value=[]):
            response = TestClient(app).get("/api/read-only/snapshot", headers={"Authorization": "Bearer secret"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overview"]["today_runs"], 1)

    def test_audit_events_and_version_list_mask_secret_values(self) -> None:
        settings = {
            "environment_variables": [
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True}
            ],
        }
        with patch("backend.app.main.storage.get_settings", return_value=settings), patch(
            "backend.app.main.storage.list_audit_events",
            return_value=[{"id": 1, "payload": {"message": "token-secret-123"}}],
        ):
            audit_response = TestClient(app).get("/api/audit-events")

        self.assertEqual(audit_response.status_code, 200)
        audit_text = json.dumps(audit_response.json(), ensure_ascii=False)
        self.assertNotIn("token-secret-123", audit_text)
        self.assertIn("***", audit_text)

        versions = [{"id": 2, "check_id": 9, "snapshot": {"headers_json": '{"Authorization":"token-secret-123"}'}}]
        with patch("backend.app.main.storage.get_check", return_value={"id": 9}), patch(
            "backend.app.main.storage.get_settings", return_value=settings
        ), patch("backend.app.main.storage.list_check_versions", return_value=versions):
            version_response = TestClient(app).get("/api/checks/9/versions")

        self.assertEqual(version_response.status_code, 200)
        version_text = json.dumps(version_response.json(), ensure_ascii=False)
        self.assertNotIn("token-secret-123", version_text)
        self.assertIn("***", version_text)

    def test_metrics_routes_return_json_and_prometheus_text(self) -> None:
        overview = {
            "failing_count": 1,
            "today_runs": 3,
            "trends": [
                {
                    "key": "24h",
                    "series": [
                        {"check_type": "ui", "runs": 1, "success_count": 1, "failure_count": 0},
                        {"check_type": "api", "runs": 3, "success_count": 2, "failure_count": 1},
                    ],
                }
            ],
        }
        checks = [{"id": 1, "enabled": True}, {"id": 2, "enabled": False}]

        with patch("backend.app.main.storage.get_overview", return_value=overview), patch(
            "backend.app.main.storage.list_checks", return_value=checks
        ):
            json_response = TestClient(app).get("/api/metrics.json")
            text_response = TestClient(app).get("/api/metrics")

        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.json()["checks_total"], 2)
        self.assertIn("pulseguard_checks_total 2", text_response.text)
        self.assertIn("pulseguard_success_rate_24h 75.0", text_response.text)

    def test_failure_summary_masks_error_and_reports_runner_kind(self) -> None:
        settings = {
            "environment_variables": [
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True}
            ],
        }
        run = {
            "id": 8,
            "check_id": 3,
            "check_name": "API",
            "status": "failed",
            "failure_kind": "runner",
            "runner_name": "local",
            "runner_region": "office",
            "duration_ms": 25,
            "error_message": "token-secret-123 browser failed",
        }

        with patch("backend.app.main.storage.get_run", return_value=run), patch(
            "backend.app.main.storage.get_previous_successful_run", return_value=None
        ), patch(
            "backend.app.main.storage.get_settings", return_value=settings
        ):
            response = TestClient(app).get("/api/runs/8/failure-summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["failure_kind"], "runner")
        self.assertIn("Runner", payload["summary"])
        self.assertNotIn("token-secret-123", json.dumps(payload, ensure_ascii=False))

    def test_failure_summary_uses_assertion_evidence_and_success_baseline(self) -> None:
        current_assertions = [
            {
                "rule": "元素可见",
                "path": "span.store-tag:nth-of-type(2)",
                "status": "failed",
                "actual": "未找到",
                "message": "校验失败：元素未找到：span.store-tag:nth-of-type(2)",
            },
            {
                "rule": "组件不为空",
                "path": "h3.store-title",
                "status": "failed",
                "actual": "未找到",
                "message": "校验失败：元素未找到：h3.store-title",
            },
            {"rule": "文本出现", "path": "详情", "status": "ok", "actual": "出现", "message": "文本出现"},
        ]
        baseline_assertions = [
            {**current_assertions[0], "status": "ok", "actual": "可见", "message": "元素可见"},
            {**current_assertions[1], "status": "ok", "actual": "购车门店", "message": "组件不为空"},
            current_assertions[2],
        ]
        run = {
            "id": 2941,
            "check_id": 11,
            "check_name": "商品详情",
            "check_type": "ui",
            "status": "failed",
            "failure_kind": "target",
            "runner_name": "local",
            "runner_region": "local",
            "duration_ms": 8869,
            "error_message": "UI 结构化校验失败",
            "response_snapshot": json.dumps(
                {"page": {"url": "https://example.test/new"}, "assertions": current_assertions},
                ensure_ascii=False,
            ),
        }
        baseline = {
            "id": 885,
            "response_snapshot": json.dumps(
                {"page": {"url": "https://example.test/old"}, "assertions": baseline_assertions},
                ensure_ascii=False,
            ),
        }

        with patch("backend.app.main.storage.get_run", return_value=run), patch(
            "backend.app.main.storage.get_previous_successful_run", return_value=baseline
        ), patch("backend.app.main.storage.get_settings", return_value={}):
            response = TestClient(app).get("/api/runs/2941/failure-summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"], "2/3 项 UI 校验失败，其中 2 项为相对最近成功运行的新增失败。")
        self.assertNotIn("error_message", payload)
        self.assertIn({"label": "失败来源", "value": "目标页面/API"}, payload["signals"])
        self.assertIn({"label": "对比基线", "value": "成功运行 #885"}, payload["signals"])
        self.assertNotIn("span.store-tag:nth-of-type(2)", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            payload["next_steps"],
            [
                "当前访问地址与成功运行 #885 不同，确认地址变更是否符合预期。",
                "在“对比”中查看 2 项新增失败的变化。",
                "在“校验”中逐项确认页面内容或校验规则是否需要更新。",
            ],
        )

    def test_failure_summary_uses_masked_target_error_when_assertions_are_unavailable(self) -> None:
        run = {
            "id": 9,
            "check_id": 3,
            "check_name": "API",
            "check_type": "api",
            "status": "failed",
            "failure_kind": "target",
            "duration_ms": 25,
            "error_message": "token-secret-123 connection refused",
        }
        settings = {
            "environment_variables": [
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True}
            ],
        }

        with patch("backend.app.main.storage.get_run", return_value=run), patch(
            "backend.app.main.storage.get_previous_successful_run", return_value=None
        ), patch("backend.app.main.storage.get_settings", return_value=settings):
            response = TestClient(app).get("/api/runs/9/failure-summary")

        payload = response.json()
        self.assertEqual(payload["summary"], "目标检查失败：*** connection refused")
        self.assertNotIn("token-secret-123", json.dumps(payload, ensure_ascii=False))

    def test_run_archives_route_returns_archive_summaries(self) -> None:
        archive = {
            "id": 1,
            "archive_date": "2026-06-01",
            "check_type": "api",
            "status": "ok",
            "run_count": 4,
            "duration_sum_ms": 1200,
            "duration_sample_count": 4,
            "last_run_at": "2026-06-01T23:00:00+08:00",
            "updated_at": "2026-06-08T10:00:00+08:00",
        }
        with patch("backend.app.main.storage.list_run_archives", return_value=[archive]) as list_run_archives:
            response = TestClient(app).get("/api/run-archives?limit=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [archive])
        list_run_archives.assert_called_once_with(limit=30)

    def test_restore_check_version_updates_existing_check_and_syncs_scheduler(self) -> None:
        scheduler = FakeScheduler()
        snapshot = check_snapshot("Restored API")
        restored = {**snapshot, "id": 9, "created_at": "now", "updated_at": "now", "current_status": None, "consecutive_failures": 0}

        with patch.object(app.state, "scheduler", scheduler, create=True), patch(
            "backend.app.main.storage.get_check_version",
            return_value={"id": 3, "check_id": 9, "snapshot": snapshot},
        ), patch("backend.app.main.storage.get_check", return_value={**restored, "name": "Current API"}), patch(
            "backend.app.main.storage.record_check_version"
        ) as record_check_version, patch(
            "backend.app.main.storage.update_check", return_value=restored
        ) as update_check, patch(
            "backend.app.main.storage.record_audit_event"
        ) as record_audit_event:
            response = TestClient(app).post("/api/check-versions/3/restore")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Restored API")
        update_check.assert_called_once()
        record_check_version.assert_called_once()
        record_audit_event.assert_called_once()
        self.assertEqual(scheduler.synced, [9])


def check_snapshot(name: str) -> dict[str, object]:
    return {
        "name": name,
        "type": "api",
        "enabled": True,
        "interval_seconds": 300,
        "timeout_ms": 10000,
        "entry_url": "https://example.com/health",
        "viewport_mode": "web",
        "method": "GET",
        "headers_json": "{}",
        "body": "",
        "assertions_json": '[{"type":"status_code","enabled":true,"expected_status":200}]',
        "setup_script": "",
        "script": "",
        "tags": "audit",
        "alert_policy_json": "{}",
    }


if __name__ == "__main__":
    unittest.main()
