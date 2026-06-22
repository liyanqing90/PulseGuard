from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any
from urllib.parse import urlsplit

import websockets

from .config import RELAY_MAX_BODY_BYTES, RELAY_MAX_FRAME_BYTES, RELAY_STREAM_IDLE_TIMEOUT_SECONDS
from .relay_tunnel import TunnelStream, decode_data_message, insecure_fingerprint_context, json_dumps, json_loads, pump_reader_to_sender


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


async def _send_json(websocket: Any, lock: asyncio.Lock, message: dict[str, Any]) -> None:
    async with lock:
        await websocket.send(json_dumps(message))


def _worker_endpoint() -> tuple[str, int]:
    url = _env("PULSEGUARD_WORKER_URL", "http://pulseguard-worker:8788")
    parts = urlsplit(url)
    if parts.scheme not in {"http", ""}:
        raise RuntimeError("PULSEGUARD_WORKER_URL only supports http in relay mode")
    host = parts.hostname or "pulseguard-worker"
    return host, int(parts.port or 8788)


def _assert_fingerprint(websocket: Any, expected: str) -> None:
    normalized = expected.lower().replace(":", "")
    if not normalized:
        raise RuntimeError("PULSEGUARD_RELAY_FINGERPRINT is required")
    ssl_object = websocket.transport.get_extra_info("ssl_object")
    cert = ssl_object.getpeercert(binary_form=True) if ssl_object else None
    if not cert:
        raise RuntimeError("relay server TLS certificate is unavailable")
    actual = hashlib.sha256(cert).hexdigest()
    if actual != normalized:
        raise RuntimeError("relay server fingerprint mismatch")


async def _heartbeat(websocket: Any, send_lock: asyncio.Lock) -> None:
    while True:
        await asyncio.sleep(15)
        await _send_json(websocket, send_lock, {"type": "heartbeat"})


async def _pump_worker_to_relay(
    stream_id: str,
    reader: asyncio.StreamReader,
    websocket: Any,
    send_lock: asyncio.Lock,
    streams: dict[str, TunnelStream],
) -> None:
    try:
        await pump_reader_to_sender(
            stream_id,
            reader,
            lambda message: _send_json(websocket, send_lock, message),
            max_bytes=RELAY_MAX_BODY_BYTES,
            idle_timeout_seconds=RELAY_STREAM_IDLE_TIMEOUT_SECONDS,
        )
    finally:
        stream = streams.pop(stream_id, None)
        if stream:
            await stream.close()


async def _open_worker_stream(stream_id: str, websocket: Any, send_lock: asyncio.Lock, streams: dict[str, TunnelStream]) -> None:
    if stream_id in streams:
        raise RuntimeError("invalid relay message")
    host, port = _worker_endpoint()
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except Exception as exc:
        await _send_json(websocket, send_lock, {"type": "error", "stream_id": stream_id, "message": str(exc)[:500]})
        return
    stream = TunnelStream(reader=reader, writer=writer)
    streams[stream_id] = stream
    task = asyncio.create_task(_pump_worker_to_relay(stream_id, reader, websocket, send_lock, streams))
    stream.tasks.add(task)


async def _handle_relay_data_message(stream_id: str, message: dict[str, Any], streams: dict[str, TunnelStream]) -> None:
    data = decode_data_message(message)
    stream = streams.get(stream_id)
    if not stream:
        return
    if not stream.record_received(len(data), RELAY_MAX_BODY_BYTES):
        streams.pop(stream_id, None)
        await stream.close()
        return
    stream.writer.write(data)
    try:
        await asyncio.wait_for(stream.writer.drain(), timeout=RELAY_STREAM_IDLE_TIMEOUT_SECONDS)
    except TimeoutError:
        streams.pop(stream_id, None)
        await stream.close()


async def _handle_relay_message(
    message: dict[str, Any],
    websocket: Any,
    send_lock: asyncio.Lock,
    streams: dict[str, TunnelStream],
) -> None:
    message_type = str(message.get("type") or "")
    stream_id = str(message.get("stream_id") or "")
    if message_type == "heartbeat_ack":
        return
    if message_type == "open" and stream_id:
        await _open_worker_stream(stream_id, websocket, send_lock, streams)
    elif message_type == "data" and stream_id:
        await _handle_relay_data_message(stream_id, message, streams)
    elif message_type in {"close", "error"} and stream_id:
        stream = streams.pop(stream_id, None)
        if stream:
            await stream.close()
    else:
        raise RuntimeError("invalid relay message")


async def run_once() -> None:
    relay_url = _env("PULSEGUARD_RELAY_URL")
    runner_id = _env("PULSEGUARD_RUNNER_ID")
    relay_token = _env("PULSEGUARD_RELAY_TOKEN")
    fingerprint = _env("PULSEGUARD_RELAY_FINGERPRINT")
    token_version = int(_env("PULSEGUARD_RELAY_TOKEN_VERSION", "1"))
    if not relay_url or not runner_id or not relay_token:
        raise RuntimeError("PULSEGUARD_RELAY_URL, PULSEGUARD_RUNNER_ID, and PULSEGUARD_RELAY_TOKEN are required")
    if urlsplit(relay_url).scheme != "wss":
        raise RuntimeError("PULSEGUARD_RELAY_URL must use wss:// in relay mode")
    send_lock = asyncio.Lock()
    streams: dict[str, TunnelStream] = {}
    async with websockets.connect(
        relay_url,
        ssl=insecure_fingerprint_context(),
        max_size=RELAY_MAX_FRAME_BYTES,
        compression=None,
    ) as websocket:
        _assert_fingerprint(websocket, fingerprint)
        await _send_json(
            websocket,
            send_lock,
            {"type": "hello", "runner_id": runner_id, "relay_token": relay_token, "relay_token_version": token_version},
        )
        ready = json_loads(await websocket.recv())
        if ready.get("type") != "ready":
            raise RuntimeError("relay server did not accept the connection")
        heartbeat = asyncio.create_task(_heartbeat(websocket, send_lock))
        try:
            async for raw in websocket:
                message = json_loads(raw)
                await _handle_relay_message(message, websocket, send_lock, streams)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            for stream in list(streams.values()):
                await stream.close()


async def main_loop() -> None:
    while True:
        try:
            await run_once()
        except Exception as exc:
            print(f"relay client disconnected: {exc}", flush=True)
            await asyncio.sleep(5)


def main() -> None:
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
