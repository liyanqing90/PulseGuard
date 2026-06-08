from __future__ import annotations

import asyncio
import unittest
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


if __name__ == "__main__":
    unittest.main()
