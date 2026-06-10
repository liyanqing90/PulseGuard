from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.getenv("PULSEGUARD_DATA_DIR", PROJECT_ROOT / "data")).resolve()
REPORTS_DIR = Path(os.getenv("PULSEGUARD_REPORTS_DIR", PROJECT_ROOT / "reports")).resolve()
DB_PATH = Path(os.getenv("PULSEGUARD_DB_PATH", DATA_DIR / "pulseguard.db")).resolve()
BACKUPS_DIR = Path(os.getenv("PULSEGUARD_BACKUPS_DIR", DATA_DIR / "backups")).resolve()
STATIC_DIR = Path(os.getenv("PULSEGUARD_STATIC_DIR", PROJECT_ROOT / "frontend" / "dist")).resolve()

HOST = os.getenv("PULSEGUARD_HOST", "127.0.0.1")
PORT = int(os.getenv("PULSEGUARD_PORT", "8787"))
TIMEZONE = os.getenv("TZ", "Asia/Shanghai")
ALERT_DETAIL_BASE_URL = (os.getenv("PULSEGUARD_ALERT_DETAIL_BASE_URL") or "http://localhost:8787").rstrip("/")

SCREENSHOTS_DIR = REPORTS_DIR / "screenshots"
TRACES_DIR = REPORTS_DIR / "traces"
RESPONSES_DIR = REPORTS_DIR / "responses"


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, BACKUPS_DIR, REPORTS_DIR, SCREENSHOTS_DIR, TRACES_DIR, RESPONSES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
