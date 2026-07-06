from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from backend.app import worker_updater


class WorkerUpdaterTokenTests(unittest.TestCase):
    def test_current_token_prefers_environment_token(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            token_file = Path(temp_dir) / "worker-token"
            token_file.write_text("file-token\n", encoding="utf-8")

            with patch.object(worker_updater, "TOKEN_FILE", token_file), patch.dict(
                os.environ, {"PULSEGUARD_WORKER_TOKEN": "env-token"}, clear=False
            ):
                self.assertEqual(worker_updater._current_token(), "env-token")

    def test_current_token_falls_back_to_token_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            token_file = Path(temp_dir) / "worker-token"
            token_file.write_text("file-token\n", encoding="utf-8")

            with patch.object(worker_updater, "TOKEN_FILE", token_file), patch.dict(
                os.environ, {"PULSEGUARD_WORKER_TOKEN": ""}, clear=False
            ):
                self.assertEqual(worker_updater._current_token(), "file-token")

    def test_current_token_returns_empty_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            token_file = Path(temp_dir) / "missing-token"

            with patch.object(worker_updater, "TOKEN_FILE", token_file), patch.dict(
                os.environ, {"PULSEGUARD_WORKER_TOKEN": ""}, clear=False
            ):
                self.assertEqual(worker_updater._current_token(), "")


class WorkerUpdaterImageTests(unittest.TestCase):
    def test_ensure_image_available_uses_pulled_image(self) -> None:
        with patch.object(worker_updater, "_run", return_value="pulled") as run:
            worker_updater._ensure_image_available("pulseguard-worker:local")

        run.assert_called_once_with(["docker", "pull", "pulseguard-worker:local"])

    def test_ensure_image_available_accepts_existing_local_image_when_pull_fails(self) -> None:
        with patch.object(
            worker_updater,
            "_run",
            side_effect=[RuntimeError("pull access denied"), "[]"],
        ) as run:
            worker_updater._ensure_image_available("pulseguard-worker:local")

        self.assertEqual(
            run.mock_calls,
            [
                call(["docker", "pull", "pulseguard-worker:local"]),
                call(["docker", "image", "inspect", "pulseguard-worker:local"]),
            ],
        )

    def test_ensure_image_available_raises_when_pull_and_local_lookup_fail(self) -> None:
        with patch.object(
            worker_updater,
            "_run",
            side_effect=[RuntimeError("pull access denied"), RuntimeError("missing image")],
        ):
            with self.assertRaises(RuntimeError):
                worker_updater._ensure_image_available("pulseguard-worker:missing")


if __name__ == "__main__":
    unittest.main()
