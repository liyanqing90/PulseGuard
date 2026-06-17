from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.app.variables import VariableResolutionError, mask_data, resolve_data, resolve_text, variable_lookup


class EnvironmentVariableTests(unittest.TestCase):
    def test_resolve_text_uses_settings_variables_before_process_environment(self) -> None:
        settings = {
            "environment_variables": [
                {"id": "api-host", "name": "API_HOST", "value": "https://api.example.com", "secret": False},
                {"id": "token", "name": "SERVICE_TOKEN", "value": "settings-token", "secret": True},
            ]
        }

        with patch.dict(os.environ, {"SERVICE_TOKEN": "process-token"}, clear=False):
            resolved = resolve_text("${API_HOST}/health?token=${SERVICE_TOKEN}", settings)

        self.assertEqual(resolved, "https://api.example.com/health?token=settings-token")

    def test_resolve_data_replaces_placeholders_recursively(self) -> None:
        settings = {
            "environment_variables": [
                {"id": "host", "name": "API_HOST", "value": "https://api.example.com", "secret": False},
                {"id": "token", "name": "SERVICE_TOKEN", "value": "token-secret-123", "secret": True},
            ]
        }

        resolved = resolve_data(
            {
                "url": "${API_HOST}/v1",
                "headers": {"Authorization": "Bearer ${SERVICE_TOKEN}"},
                "items": ["${SERVICE_TOKEN}"],
            },
            settings,
        )

        self.assertEqual(resolved["url"], "https://api.example.com/v1")
        self.assertEqual(resolved["headers"]["Authorization"], "Bearer token-secret-123")
        self.assertEqual(resolved["items"], ["token-secret-123"])

    def test_missing_placeholder_raises_without_substituting_partial_text(self) -> None:
        with self.assertRaises(VariableResolutionError) as cm:
            resolve_text("https://example.com/${MISSING_TOKEN}", {"environment_variables": []})

        self.assertIn("MISSING_TOKEN", str(cm.exception))

    def test_mask_data_masks_explicit_secret_and_sensitive_name_values(self) -> None:
        settings = {
            "environment_variables": [
                {"id": "plain", "name": "API_HOST", "value": "https://api.example.com", "secret": False},
                {"id": "explicit", "name": "SESSION_ID", "value": "session-secret-123", "secret": True},
                {"id": "named", "name": "SERVICE_TOKEN", "value": "token-secret-456", "secret": False},
            ]
        }

        masked = mask_data(
            {
                "url": "https://api.example.com",
                "headers": {
                    "Cookie": "session=session-secret-123",
                    "Authorization": "Bearer token-secret-456",
                },
            },
            settings,
        )

        self.assertEqual(masked["url"], "https://api.example.com")
        self.assertEqual(masked["headers"]["Cookie"], "***")
        self.assertEqual(masked["headers"]["Authorization"], "***")

    def test_mask_data_masks_sensitive_field_names_and_read_only_token(self) -> None:
        settings = {"read_only_token": "readonly-secret-123", "environment_variables": []}

        masked = mask_data(
            {
                "read_only_token": "readonly-secret-123",
                "message": "token readonly-secret-123",
                "payload": {
                    "access_token": "literal-access-token",
                    "nested": {"Set-Cookie": "sid=literal-cookie"},
                    "count": 2,
                },
            },
            settings,
        )

        self.assertEqual(masked["read_only_token"], "***")
        self.assertEqual(masked["message"], "token ***")
        self.assertEqual(masked["payload"]["access_token"], "***")
        self.assertEqual(masked["payload"]["nested"]["Set-Cookie"], "***")
        self.assertEqual(masked["payload"]["count"], 2)

    def test_variable_lookup_inherits_process_environment(self) -> None:
        settings = {"environment_variables": [{"id": "local", "name": "LOCAL_ONLY", "value": "local", "secret": False}]}

        with patch.dict(os.environ, {"PROCESS_ONLY": "process"}, clear=False):
            lookup = variable_lookup(settings)

        self.assertEqual(lookup["LOCAL_ONLY"], "local")
        self.assertEqual(lookup["PROCESS_ONLY"], "process")


if __name__ == "__main__":
    unittest.main()
