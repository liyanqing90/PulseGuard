from __future__ import annotations

import asyncio
import unittest

import httpx

from backend.app.api_assertions import extract_json_paths, find_json_path, normalize_api_assertions, run_structured_api_check
from backend.app.api_assertions import _evaluate_assertion


class ApiAssertionTests(unittest.TestCase):
    def test_extract_json_paths_returns_selectable_nested_fields(self) -> None:
        paths = extract_json_paths({"data": {"id": 7, "items": [{"name": "first"}]}, "ok": True})
        path_values = {item["path"] for item in paths}

        self.assertIn("$.data.id", path_values)
        self.assertIn("$.data.items[0].name", path_values)
        self.assertIn("$.ok", path_values)

    def test_extract_json_paths_returns_metadata_for_frontend_rule_generation(self) -> None:
        paths = extract_json_paths({"items": [{"name": "first"}], "meta.info": {"tags": ["a", "b"]}})
        by_path = {item["path"]: item for item in paths}

        self.assertEqual(by_path["$.items"]["type"], "array")
        self.assertEqual(by_path["$.items"]["length"], 1)
        self.assertEqual(by_path["$.items[0].name"]["type"], "string")
        self.assertEqual(by_path["$.items[0].name"]["length"], 5)
        self.assertEqual(by_path['$["meta.info"].tags']["type"], "array")
        self.assertEqual(by_path['$["meta.info"].tags']["length"], 2)

    def test_find_json_path_supports_bracket_keys(self) -> None:
        exists, value = find_json_path({"a.b": {"value": 1}}, '$["a.b"].value')

        self.assertTrue(exists)
        self.assertEqual(value, 1)

    def test_status_and_json_assertions_report_actionable_errors(self) -> None:
        response = httpx.Response(404, json={"ok": False})
        status_assertion = normalize_api_assertions('[{"type":"status_code","expected_status":200}]')[0]
        path_assertion = normalize_api_assertions('[{"type":"json_path_exists","path":"$.data.id"}]')[0]

        self.assertEqual(_evaluate_assertion(status_assertion, response, 20, {"ok": False}, True), "状态码不匹配：期望 200，实际 404")
        self.assertEqual(_evaluate_assertion(path_assertion, response, 20, {"ok": False}, True), "JSON 字段不存在：$.data.id")

    def test_json_equals_parses_expected_json_literals(self) -> None:
        response = httpx.Response(200, json={"count": 3})
        assertion = normalize_api_assertions('[{"type":"json_path_equals","path":"$.count","expected_value":"3"}]')[0]

        self.assertIsNone(_evaluate_assertion(assertion, response, 20, {"count": 3}, True))

    def test_field_type_contains_not_empty_and_length_assertions(self) -> None:
        response = httpx.Response(200, json={"name": "PulseGuard", "items": [{"id": 1}], "meta": {"env": "test"}})
        body = response.json()
        assertions = normalize_api_assertions(
            """
            [
              {"type":"json_path_type","path":"$.items","expected_type":"array"},
              {"type":"json_path_contains","path":"$.name","expected_value":"Pulse"},
              {"type":"json_path_not_empty","path":"$.meta"},
              {"type":"json_path_length","path":"$.items","operator":"eq","expected_length":1}
            ]
            """
        )

        for assertion in assertions:
            self.assertIsNone(_evaluate_assertion(assertion, response, 20, body, True))

    def test_length_assertion_rejects_non_sized_values(self) -> None:
        response = httpx.Response(200, json={"count": 3})
        assertion = normalize_api_assertions('[{"type":"json_path_length","path":"$.count","operator":"gte","expected_length":1}]')[0]

        self.assertEqual(_evaluate_assertion(assertion, response, 20, {"count": 3}, True), "JSON 字段不支持长度校验：$.count")


    def test_structured_api_assertions_resolve_variable_placeholders(self) -> None:
        ctx = FakeApiContext(
            {
                "assertions_json": '[{"type":"json_path_equals","path":"$.state","expected_value":"${EXPECTED_STATE}"}]',
            },
            {"environment_variables": [{"id": "state", "name": "EXPECTED_STATE", "value": "active", "secret": False}]},
            httpx.Response(200, json={"state": "active"}),
        )

        asyncio.run(run_structured_api_check(ctx))  # type: ignore[arg-type]

        self.assertEqual(ctx.response_snapshot["assertions"][0]["status"], "ok")
        self.assertIn("duration_ms", ctx.response_snapshot)
        self.assertIn("request_ms", ctx.response_snapshot["timings"])


class FakeApiContext:
    def __init__(self, check: dict[str, str], settings: dict[str, object], response: httpx.Response) -> None:
        self.check = check
        self.settings = settings
        self._response = response
        self.response_snapshot: dict[str, object] | None = None
        self.logs: list[str] = []

    async def request(self) -> httpx.Response:
        return self._response

    def log(self, message: object) -> None:
        self.logs.append(str(message))

    def save_response(self, response: httpx.Response) -> None:
        self.response_snapshot = {"status_code": response.status_code, "body": response.text}


if __name__ == "__main__":
    unittest.main()
