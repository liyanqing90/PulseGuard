from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import storage
from .config import RELAY_CERT_FILE, RELAY_ENABLED, RELAY_KEY_FILE, RELAY_MAX_BODY_BYTES, RELAY_PUBLIC_PORT, ensure_runtime_dirs
from .relay_cert import ensure_relay_certificate
from .relay_tunnel import TunnelStream, decode_data_message, json_dumps, json_loads, pump_reader_to_sender


app = FastAPI(title="PulseGuard Relay")
ACTIVE_SESSIONS: dict[str, "RelaySession"] = {}


@dataclass
class RelaySession:
    runner_id: str
    token: str
    token_version: int
    websocket: WebSocket
    server: asyncio.AbstractServer
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    streams: dict[str, TunnelStream] = field(default_factory=dict)

    async def send_json(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_text(json_dumps(message))

    async def close(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        for stream in list(self.streams.values()):
            await stream.close()
        try:
            await self.websocket.close()
        except Exception:
            pass


async def _tcp_client_connected(session: RelaySession, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    if not storage.verify_probe_runner_relay_token(session.runner_id, session.token, session.token_version):
        writer.close()
        await writer.wait_closed()
        await session.websocket.close(code=4403, reason="relay token rotated")
        return
    stream_id = uuid.uuid4().hex
    stream = TunnelStream(reader=reader, writer=writer)
    session.streams[stream_id] = stream
    try:
        await session.send_json({"type": "open", "stream_id": stream_id})
        task = asyncio.create_task(pump_reader_to_sender(stream_id, reader, session.send_json, max_bytes=RELAY_MAX_BODY_BYTES))
        stream.tasks.add(task)
        await task
    finally:
        session.streams.pop(stream_id, None)
        writer.close()
        await writer.wait_closed()


@app.websocket("/relay/connect")
async def relay_connect(websocket: WebSocket) -> None:
    await websocket.accept()
    session: RelaySession | None = None
    runner_id = ""
    try:
        hello = json_loads(await websocket.receive_text())
        if hello.get("type") != "hello":
            await websocket.close(code=4400, reason="invalid hello")
            return
        runner_id = str(hello.get("runner_id") or "").strip()
        token = str(hello.get("relay_token") or "").strip()
        token_version = int(hello.get("relay_token_version") or 0)
        runner = storage.verify_probe_runner_relay_token(runner_id, token, token_version)
        if not runner:
            storage.mark_probe_runner_relay_auth_failed(runner_id)
            await websocket.close(code=4403, reason="relay token invalid")
            return
        port = int(runner.get("allocated_internal_port") or 0)
        if port <= 0:
            await websocket.close(code=4400, reason="runner has no internal port")
            return
        old_session = ACTIVE_SESSIONS.pop(runner_id, None)
        if old_session:
            await old_session.close()
        session_holder: dict[str, RelaySession] = {}

        async def handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            current = session_holder.get("session")
            if current is None:
                writer.close()
                await writer.wait_closed()
                return
            await _tcp_client_connected(current, reader, writer)

        server = await asyncio.start_server(handle_tcp, host="0.0.0.0", port=port)
        session = RelaySession(runner_id=runner_id, token=token, token_version=token_version, websocket=websocket, server=server)
        session_holder["session"] = session
        ACTIVE_SESSIONS[runner_id] = session
        storage.mark_probe_runner_relay_connected(runner_id)
        await session.send_json({"type": "ready"})
        while True:
            message = json_loads(await websocket.receive_text())
            message_type = str(message.get("type") or "")
            if message_type == "heartbeat":
                if not storage.verify_probe_runner_relay_token(runner_id, token, token_version):
                    await websocket.close(code=4403, reason="relay token rotated")
                    return
                storage.mark_probe_runner_relay_seen(runner_id)
                await session.send_json({"type": "heartbeat_ack"})
            elif message_type == "data":
                stream = session.streams.get(str(message.get("stream_id") or ""))
                if stream:
                    data = decode_data_message(message)
                    if not stream.record_received(len(data), RELAY_MAX_BODY_BYTES):
                        await stream.close()
                    else:
                        stream.writer.write(data)
                        await stream.writer.drain()
            elif message_type in {"close", "error"}:
                stream = session.streams.pop(str(message.get("stream_id") or ""), None)
                if stream:
                    await stream.close()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        if runner_id:
            storage.mark_probe_runner_relay_disconnected(runner_id, str(exc)[:500])
        raise
    finally:
        if session:
            if ACTIVE_SESSIONS.get(runner_id) is session:
                ACTIVE_SESSIONS.pop(runner_id, None)
                storage.mark_probe_runner_relay_disconnected(runner_id, "client disconnected")
            await session.close()


def main() -> None:
    ensure_runtime_dirs()
    ensure_relay_certificate()
    if not RELAY_ENABLED:
        print("PULSEGUARD_RELAY_ENABLED is not enabled; relay server still starts for explicit compose usage.", flush=True)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=RELAY_PUBLIC_PORT,
        ssl_certfile=str(RELAY_CERT_FILE),
        ssl_keyfile=str(RELAY_KEY_FILE),
        log_level="info",
    )


if __name__ == "__main__":
    main()
