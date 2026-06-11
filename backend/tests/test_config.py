from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest


class ConfigEnvTests(unittest.TestCase):
    def test_worker_env_names_match_readme_without_main_node_url(self) -> None:
        script = """
import json
import os
os.environ["PULSEGUARD_WORKER_RUNNER_ID"] = "worker-readme"
os.environ["PULSEGUARD_RUNNER_ID"] = "worker-legacy"
os.environ["PULSEGUARD_WORKER_NAME"] = "worker-name"
os.environ["PULSEGUARD_WORKER_ADDRESS"] = "http://10.0.0.2:8788"
from backend.app import config
print(json.dumps({
    "runner_id": config.WORKER_RUNNER_ID,
    "name": config.WORKER_NAME,
    "address": config.WORKER_ADDRESS,
}))
"""
        output = subprocess.check_output([sys.executable, "-c", script], text=True)
        payload = json.loads(output)

        self.assertEqual(payload["runner_id"], "worker-readme")
        self.assertEqual(payload["name"], "worker-name")
        self.assertEqual(payload["address"], "http://10.0.0.2:8788")

    def test_worker_mode_generates_and_reuses_local_token_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            script = """
import json
import os
from pathlib import Path
os.environ["PULSEGUARD_NODE_ROLE"] = "worker"
os.environ["PULSEGUARD_WORKER_TOKEN_FILE"] = r"%s"
os.environ.pop("PULSEGUARD_WORKER_TOKEN", None)
from backend.app import config
first = config.WORKER_TOKEN
source = config.WORKER_TOKEN_SOURCE
stored = Path(os.environ["PULSEGUARD_WORKER_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
print(json.dumps({"first": first, "source": source, "stored": stored}))
""" % ((temp_dir + "/worker-token").replace("\\", "\\\\"))
            first_output = subprocess.check_output([sys.executable, "-c", script], text=True)
            second_output = subprocess.check_output([sys.executable, "-c", script], text=True)

        first_payload = json.loads(first_output)
        second_payload = json.loads(second_output)
        self.assertTrue(first_payload["first"].startswith("pgrn_"))
        self.assertEqual(first_payload["first"], first_payload["stored"])
        self.assertEqual(first_payload["source"], second_payload["source"])
        self.assertEqual(first_payload["first"], second_payload["first"])

    def test_worker_cli_can_show_and_rotate_persisted_token_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            token_file = f"{temp_dir}/worker-token"
            base_cmd = [
                sys.executable,
                "-m",
                "backend.app.worker",
                "--token-file",
                token_file,
                "--address",
                "http://127.0.0.1:8788",
            ]
            first_output = subprocess.check_output([*base_cmd, "--show-token"], text=True)
            first_token = self._extract_worker_token(first_output)
            rotated_output = subprocess.check_output([*base_cmd, "--rotate-token"], text=True)
            rotated_token = self._extract_worker_token(rotated_output)
            shown_output = subprocess.check_output([*base_cmd, "--show-token"], text=True)
            shown_token = self._extract_worker_token(shown_output)

        self.assertTrue(first_token.startswith("pgrn_"))
        self.assertTrue(rotated_token.startswith("pgrn_"))
        self.assertNotEqual(first_token, rotated_token)
        self.assertEqual(rotated_token, shown_token)
        self.assertIn("Add this child node manually", rotated_output)

    def _extract_worker_token(self, output: str) -> str:
        match = re.search(r"token: (pgrn_[A-Za-z0-9_-]+)", output)
        self.assertIsNotNone(match, output)
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
