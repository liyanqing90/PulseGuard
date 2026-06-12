from __future__ import annotations

import json
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RESPONSES_DIR, SCREENSHOTS_DIR, TRACES_DIR

MAX_UPLOADED_ARTIFACT_BYTES = 10 * 1024 * 1024


class ArtifactStore:
    def __init__(self) -> None:
        self.screenshots_dir = SCREENSHOTS_DIR
        self.traces_dir = TRACES_DIR
        self.responses_dir = RESPONSES_DIR

    def screenshot_target(self, run_id: int, name: str = "failure") -> tuple[Path, str]:
        filename = self._filename(run_id, name, "png")
        return self.screenshots_dir / filename, f"screenshots/{filename}"

    def trace_target(self, run_id: int) -> tuple[Path, str]:
        filename = self._filename(run_id, "trace", "zip")
        return self.traces_dir / filename, f"traces/{filename}"

    def response_target(self, run_id: int) -> tuple[Path, str]:
        filename = self._filename(run_id, "response", "json")
        return self.responses_dir / filename, f"responses/{filename}"

    def save_response(self, run_id: int, payload: dict[str, Any]) -> str:
        path, relative = self.response_target(run_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return relative

    def save_uploaded_artifact(self, run_id: int, artifact_type: str, content_base64: str) -> str | None:
        if artifact_type == "screenshot_path":
            path, relative = self.screenshot_target(run_id, "remote")
        elif artifact_type == "trace_path":
            path, relative = self.trace_target(run_id)
        elif artifact_type == "response_path":
            path, relative = self.response_target(run_id)
        else:
            return None
        content = base64.b64decode(content_base64.encode("ascii"), validate=True)
        if len(content) > MAX_UPLOADED_ARTIFACT_BYTES:
            raise ValueError("uploaded artifact exceeds size limit")
        path.write_bytes(content)
        return relative

    @staticmethod
    def artifact_url(relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        clean_path = relative_path.replace("\\", "/")
        return f"/artifacts/{clean_path}"

    @staticmethod
    def _filename(run_id: int, label: str, extension: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label)[:48]
        return f"run-{run_id}-{safe_label}-{stamp}.{extension}"


def cleanup_old_artifacts(settings: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "screenshot_path": _cleanup_directory(
            SCREENSHOTS_DIR,
            "screenshots",
            int(settings.get("screenshot_retention_days", 30)),
        ),
        "trace_path": _cleanup_directory(TRACES_DIR, "traces", int(settings.get("trace_retention_days", 7))),
        "response_path": _cleanup_directory(
            RESPONSES_DIR,
            "responses",
            int(settings.get("response_retention_days", 30)),
        ),
    }


def _cleanup_directory(directory: Path, relative_prefix: str, retention_days: int) -> list[str]:
    root = directory.resolve()
    if not root.exists():
        return []

    cutoff = time.time() - max(1, retention_days) * 86400
    removed: list[str] = []
    for path in root.iterdir():
        resolved = path.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        try:
            if resolved.stat().st_mtime < cutoff:
                resolved.unlink()
                removed.append(f"{relative_prefix}/{resolved.name}")
        except FileNotFoundError:
            continue
    return removed
