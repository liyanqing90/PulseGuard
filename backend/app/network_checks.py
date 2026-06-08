from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


def normalize_host_port(target: str, default_port: int) -> tuple[str, int]:
    text = str(target or "").strip()
    if not text:
        raise ValueError("目标主机不能为空")
    try:
        parsed = urlsplit(text if "://" in text else f"//{text}")
        host = parsed.hostname or ""
        port = parsed.port or int(default_port)
    except ValueError as exc:
        raise ValueError("目标端口无效") from exc
    if not host:
        raise ValueError("目标主机不能为空")
    if port <= 0 or port > 65535:
        raise ValueError("目标端口必须在 1 到 65535 之间")
    return host, port


def tcp_connect(host: str, port: int, timeout_seconds: float) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    with socket.create_connection((host, int(port)), timeout=float(timeout_seconds)):
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {"host": host, "port": int(port), "duration_ms": duration_ms}


def resolve_hostname(host: str) -> dict[str, Any]:
    rows = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses = sorted({row[4][0] for row in rows if row and row[4]})
    if not addresses:
        raise ValueError("DNS 未返回可用地址")
    return {"host": host, "addresses": addresses}


def tls_certificate(host: str, port: int, timeout_seconds: float) -> dict[str, Any]:
    context = ssl.create_default_context()
    with socket.create_connection((host, int(port)), timeout=float(timeout_seconds)) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls_sock:
            cert = tls_sock.getpeercert()

    not_after = str(cert.get("notAfter") or "")
    if not not_after:
        raise ValueError("证书未返回到期时间")
    expires_at = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    seconds_remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    return {
        "host": host,
        "port": int(port),
        "subject": cert.get("subject"),
        "issuer": cert.get("issuer"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "days_remaining": seconds_remaining // 86400,
    }
