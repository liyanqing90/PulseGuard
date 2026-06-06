from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RESPONSES_DIR, SCREENSHOTS_DIR, TRACES_DIR


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
