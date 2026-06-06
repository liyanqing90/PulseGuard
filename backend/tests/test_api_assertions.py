from __future__ import annotations

import unittest

import httpx

from backend.app.api_assertions import extract_json_paths, find_json_path, normalize_api_assertions
from backend.app.api_assertions import _evaluate_assertion


class ApiAssertionTests(unittest.TestCase):
    def test_extract_json_paths_returns_selectable_nested_fields(self) -> None:
        paths = extract_json_paths({"data": {"id": 7, "items": [{"name": "first"}]}, "ok": True})
        path_values = {item["path"] for item in paths}

        self.assertIn("$.data.id", path_values)
        self.assertIn("$.data.items[0].name", path_values)
        self.assertIn("$.ok", path_values)

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


if __name__ == "__main__":
    unittest.main()
