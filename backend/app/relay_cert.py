from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .config import RELAY_CERT_FILE, RELAY_KEY_FILE


def ensure_relay_certificate() -> tuple[Path, Path]:
    cert = RELAY_CERT_FILE
    key = RELAY_KEY_FILE
    if cert.exists() and key.exists():
        return cert, key
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "3650",
            "-subj",
            "/CN=PulseGuard Relay",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        key.chmod(0o600)
    except OSError:
        pass
    return cert, key


def relay_fingerprint() -> str:
    cert, _ = ensure_relay_certificate()
    data = cert.read_text(encoding="utf-8")
    body = "".join(line.strip() for line in data.splitlines() if "CERTIFICATE" not in line)
    import base64

    der = base64.b64decode(body)
    return hashlib.sha256(der).hexdigest()
