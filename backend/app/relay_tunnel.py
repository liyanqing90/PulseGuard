from __future__ import annotations

import asyncio
import base64
import json
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


JsonSender = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class TunnelStream:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    received_bytes: int = 0
    tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def record_received(self, byte_count: int, max_bytes: int | None = None) -> bool:
        self.received_bytes += max(0, int(byte_count))
        return max_bytes is None or self.received_bytes <= max_bytes

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        self.writer.close()
        await self.writer.wait_closed()


async def pump_reader_to_sender(
    stream_id: str,
    reader: asyncio.StreamReader,
    send_json: JsonSender,
    max_bytes: int | None = None,
) -> None:
    sent_bytes = 0
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            sent_bytes += len(chunk)
            if max_bytes is not None and sent_bytes > max_bytes:
                break
            await send_json({"type": "data", "stream_id": stream_id, "data": base64.b64encode(chunk).decode("ascii")})
    finally:
        await send_json({"type": "close", "stream_id": stream_id})


def decode_data_message(message: dict[str, Any]) -> bytes:
    return base64.b64decode(str(message.get("data") or ""))


def json_dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def json_loads(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("relay message must be an object")
    return value


def insecure_fingerprint_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
