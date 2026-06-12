from __future__ import annotations

import asyncio
import io
import json
import unittest
from unittest.mock import Mock, patch

from backend.app import cli


class CliFilterTests(unittest.TestCase):
    def test_parse_filters_defaults_enabled_only_and_dedupes_ids(self) -> None:
        filters, pretty = cli.parse_filters(["--id", "2", "--id", "2", "--type", "api", "--tag", "Smoke", "--pretty"])

        self.assertTrue(pretty)
        self.assertEqual(filters.ids, (2,))
        self.assertEqual(filters.check_type, "api")
        self.assertEqual(filters.tag, "smoke")
        self.assertTrue(filters.enabled_only)

    def test_parse_filters_rejects_multi_token_tag(self) -> None:
        with self.assertRaises(cli.CliUsageError):
            cli.parse_filters(["--tag", "smoke api"])

    def test_select_checks_filters_ids_by_type_tag_and_enabled_state(self) -> None:
        checks = {
            1: check(1, "api", True, "smoke prod"),
            2: check(2, "api", False, "smoke"),
            3: check(3, "ui", True, "smoke"),
            4: check(4, "api", True, "smoketest"),
        }
        filters = cli.CliFilters(ids=(1, 2, 3, 4), check_type="api", tag="smoke", enabled_only=True)

        with patch("backend.app.cli.storage.get_check", side_effect=lambda check_id: checks.get(check_id)):
            selected = cli.select_checks(filters)

        self.assertEqual([item["id"] for item in selected], [1])

    def test_select_checks_without_ids_delegates_to_batch_selector(self) -> None:
        filters = cli.CliFilters(ids=(), check_type="ui", tag="smoke", enabled_only=True)

        with patch("backend.app.cli.storage.select_checks_for_batch", return_value=[check(7, "ui", True, "smoke")]) as select_checks:
            selected = cli.select_checks(filters)

        self.assertEqual([item["id"] for item in selected], [7])
        select_checks.assert_called_once_with("ui", "smoke", enabled_only=True)


class CliMainTests(unittest.TestCase):
    def test_async_main_returns_no_match_exit_code(self) -> None:
        stdout = io.StringIO()

        with patch("backend.app.cli.storage.init_db"), patch("backend.app.cli.select_checks", return_value=[]):
            code = asyncio.run(cli.async_main(["--type", "api"], stdout=stdout))

        body = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_NO_MATCH)
        self.assertFalse(body["ok"])
        self.assertEqual(body["matched"], 0)

    def test_async_main_runs_selected_checks_with_cli_trigger(self) -> None:
        stdout = io.StringIO()
        fake_runner = FakeRunner({1: "ok", 2: "ok"})

        with patch("backend.app.cli.storage.init_db"), patch(
            "backend.app.cli.select_checks",
            return_value=[check(1, "api", True, "smoke"), check(2, "api", True, "smoke")],
        ):
            code = asyncio.run(cli.async_main(["--tag", "smoke"], stdout=stdout, runner_factory=lambda: fake_runner))

        body = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(body["ok"])
        self.assertEqual(body["matched"], 2)
        self.assertEqual(fake_runner.calls, [(1, "cli"), (2, "cli")])
        self.assertTrue(fake_runner.started)
        self.assertTrue(fake_runner.shutdown_called)

    def test_async_main_returns_failure_exit_code_for_non_ok_runs(self) -> None:
        stdout = io.StringIO()
        fake_runner = FakeRunner({1: "ok", 2: "failed"})

        with patch("backend.app.cli.storage.init_db"), patch(
            "backend.app.cli.select_checks",
            return_value=[check(1, "api", True, "smoke"), check(2, "api", True, "smoke")],
        ):
            code = asyncio.run(cli.async_main(["--tag", "smoke"], stdout=stdout, runner_factory=lambda: fake_runner))

        body = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_RUN_FAILED)
        self.assertFalse(body["ok"])
        self.assertEqual([run["status"] for run in body["runs"]], ["ok", "failed"])

    def test_async_main_returns_usage_exit_code_for_bad_args(self) -> None:
        stderr = io.StringIO()

        with patch("backend.app.cli.storage.init_db") as init_db:
            code = asyncio.run(cli.async_main(["--tag", "bad tag"], stderr=stderr))

        body = json.loads(stderr.getvalue())
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("标签必须是单个 token", body["message"])
        init_db.assert_not_called()

    def test_async_main_returns_internal_error_exit_code(self) -> None:
        stderr = io.StringIO()

        with patch("backend.app.cli.storage.init_db", Mock(side_effect=RuntimeError("database unavailable"))):
            code = asyncio.run(cli.async_main(["--type", "api"], stderr=stderr))

        body = json.loads(stderr.getvalue())
        self.assertEqual(code, cli.EXIT_INTERNAL_ERROR)
        self.assertEqual(body["message"], "database unavailable")


class FakeRunner:
    def __init__(self, statuses: dict[int, str]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[int, str]] = []
        self.started = False
        self.shutdown_called = False

    async def start(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def run_check(self, check_id: int, trigger: str = "manual") -> dict[str, object]:
        self.calls.append((check_id, trigger))
        status = self.statuses[check_id]
        return {
            "id": check_id + 100,
            "check_id": check_id,
            "check_name": f"Check {check_id}",
            "check_type": "api",
            "status": status,
            "duration_ms": 10,
            "error_message": None if status == "ok" else "failed",
        }


def check(check_id: int, check_type: str, enabled: bool, tags: str) -> dict[str, object]:
    return {
        "id": check_id,
        "name": f"Check {check_id}",
        "type": check_type,
        "enabled": enabled,
        "tags": tags,
    }


if __name__ == "__main__":
    unittest.main()
