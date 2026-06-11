from __future__ import annotations

import os
import secrets
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
NODE_ROLE = os.getenv("PULSEGUARD_NODE_ROLE", "main").strip().lower() or "main"
WORKER_TOKEN_FILE = Path(os.getenv("PULSEGUARD_WORKER_TOKEN_FILE", DATA_DIR / "worker-token")).resolve()
RUNNER_HEALTH_POLL_SECONDS = max(10, int(os.getenv("PULSEGUARD_RUNNER_HEALTH_POLL_SECONDS", "30")))


def _new_worker_token() -> str:
    return f"pgrn_{secrets.token_urlsafe(32)}"


def _worker_token() -> tuple[str, str]:
    env_token = os.getenv("PULSEGUARD_WORKER_TOKEN", "").strip()
    if env_token:
        return env_token, "env"
    if NODE_ROLE != "worker":
        return "", "unset"
    WORKER_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if WORKER_TOKEN_FILE.exists():
        token = WORKER_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token, str(WORKER_TOKEN_FILE)
    token = _new_worker_token()
    WORKER_TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        WORKER_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return token, str(WORKER_TOKEN_FILE)


WORKER_NAME = os.getenv("PULSEGUARD_WORKER_NAME", "worker").strip() or "worker"
WORKER_RUNNER_ID = os.getenv("PULSEGUARD_WORKER_RUNNER_ID", os.getenv("PULSEGUARD_RUNNER_ID", WORKER_NAME)).strip() or WORKER_NAME
WORKER_ADDRESS = os.getenv("PULSEGUARD_WORKER_ADDRESS", "").strip()
WORKER_REGION = os.getenv("PULSEGUARD_WORKER_REGION", "local").strip() or "local"
WORKER_TOKEN, WORKER_TOKEN_SOURCE = _worker_token()

SCREENSHOTS_DIR = REPORTS_DIR / "screenshots"
TRACES_DIR = REPORTS_DIR / "traces"
RESPONSES_DIR = REPORTS_DIR / "responses"


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, BACKUPS_DIR, REPORTS_DIR, SCREENSHOTS_DIR, TRACES_DIR, RESPONSES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
