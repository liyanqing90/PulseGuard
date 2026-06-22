from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect

from . import storage
from .config import (
    RELAY_CERT_FILE,
    RELAY_AUTH_BACKOFF_BASE_SECONDS,
    RELAY_AUTH_BACKOFF_MAX_SECONDS,
    RELAY_CONTROL_HOST,
    RELAY_CONTROL_PORT,
    RELAY_ENABLED,
    RELAY_HELLO_TIMEOUT_SECONDS,
    RELAY_INTERNAL_LISTEN_HOST,
    RELAY_KEY_FILE,
    RELAY_MAX_BODY_BYTES,
    RELAY_MAX_CONCURRENT_STREAMS,
    RELAY_MAX_FRAME_BYTES,
    RELAY_MAX_PUBLIC_CONNECTIONS,
    RELAY_PUBLIC_PORT,
    RELAY_STREAM_IDLE_TIMEOUT_SECONDS,
    ensure_runtime_dirs,
    relay_control_token,
)
from .relay_cert import ensure_relay_certificate
from .relay_tunnel import TunnelStream, decode_data_message, json_dumps, json_loads, pump_reader_to_sender


app = FastAPI(title="PulseGuard Relay")
control_app = FastAPI(title="PulseGuard Relay Control")
ACTIVE_SESSIONS: dict[str, "RelaySession"] = {}
SESSION_LOCK = asyncio.Lock()
PUBLIC_CONNECTIONS = 0
PUBLIC_CONNECTION_LOCK = asyncio.Lock()
AUTH_FAILURES: dict[str, tuple[int, float]] = {}


@dataclass
class RelaySession:
    runner_id: str
    token: str
    token_version: int
    websocket: WebSocket
    server: asyncio.AbstractServer
    last_seen_monotonic: float = field(default_factory=time.monotonic)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stream_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
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


def _bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    return authorization[len(prefix) :].strip() if authorization.startswith(prefix) else ""


async def _acquire_public_connection() -> bool:
    global PUBLIC_CONNECTIONS
    async with PUBLIC_CONNECTION_LOCK:
        if PUBLIC_CONNECTIONS >= RELAY_MAX_PUBLIC_CONNECTIONS:
            return False
        PUBLIC_CONNECTIONS += 1
        return True


async def _release_public_connection() -> None:
    global PUBLIC_CONNECTIONS
    async with PUBLIC_CONNECTION_LOCK:
        PUBLIC_CONNECTIONS = max(0, PUBLIC_CONNECTIONS - 1)


async def _receive_json(websocket: WebSocket, timeout_seconds: float | None = None) -> dict[str, Any]:
    if timeout_seconds is None:
        text = await websocket.receive_text()
    else:
        text = await asyncio.wait_for(websocket.receive_text(), timeout=timeout_seconds)
    if len(text.encode("utf-8")) > RELAY_MAX_FRAME_BYTES:
        raise ValueError("relay message too large")
    return json_loads(text)


def _auth_failure_key(websocket: WebSocket, runner_id: str) -> str:
    runner_id = str(runner_id or "").strip()
    if runner_id:
        return runner_id
    client = getattr(websocket, "client", None)
    return str(getattr(client, "host", "") or "unknown")


async def _record_auth_failure(key: str) -> None:
    if len(AUTH_FAILURES) > 1024:
        AUTH_FAILURES.clear()
    count, _last_seen = AUTH_FAILURES.get(key, (0, 0.0))
    count = min(count + 1, 16)
    AUTH_FAILURES[key] = (count, time.monotonic())
    delay = min(RELAY_AUTH_BACKOFF_MAX_SECONDS, RELAY_AUTH_BACKOFF_BASE_SECONDS * (2 ** (count - 1)))
    if delay > 0:
        await asyncio.sleep(delay)


def _clear_auth_failure(key: str) -> None:
    AUTH_FAILURES.pop(key, None)


def _relay_session_credentials_valid(session: RelaySession) -> bool:
    return bool(storage.verify_probe_runner_relay_token(session.runner_id, session.token, session.token_version))


async def revoke_relay_session(runner_id: str, reason: str = "revoked") -> bool:
    async with SESSION_LOCK:
        session = ACTIVE_SESSIONS.pop(runner_id, None)
        if not session:
            return False
        storage.mark_probe_runner_relay_disconnected(runner_id, reason)
        await session.close()
        return True


@control_app.post("/relay/control/revoke")
async def relay_control_revoke(payload: dict[str, Any], authorization: str = Header(default="")) -> dict[str, Any]:
    if not secrets.compare_digest(_bearer_token(authorization), relay_control_token()):
        raise HTTPException(status_code=403, detail="relay control token invalid")
    runner_id = str(payload.get("runner_id") or "").strip()
    if not runner_id:
        raise HTTPException(status_code=400, detail="runner_id is required")
    reason = str(payload.get("reason") or "revoked")[:500]
    revoked = await revoke_relay_session(runner_id, reason)
    return {"ok": True, "revoked": revoked}


async def _tcp_client_connected(session: RelaySession, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    if not _relay_session_credentials_valid(session):
        writer.close()
        await writer.wait_closed()
        await session.websocket.close(code=4403, reason="relay token rotated")
        return
    async with session.stream_lock:
        if len(session.streams) >= RELAY_MAX_CONCURRENT_STREAMS:
            writer.close()
            await writer.wait_closed()
            return
        stream_id = uuid.uuid4().hex
        stream = TunnelStream(reader=reader, writer=writer)
        session.streams[stream_id] = stream
    try:
        await session.send_json({"type": "open", "stream_id": stream_id})
        task = asyncio.create_task(
            pump_reader_to_sender(
                stream_id,
                reader,
                session.send_json,
                max_bytes=RELAY_MAX_BODY_BYTES,
                idle_timeout_seconds=RELAY_STREAM_IDLE_TIMEOUT_SECONDS,
            )
        )
        stream.tasks.add(task)
        await task
    finally:
        async with session.stream_lock:
            session.streams.pop(stream_id, None)
        writer.close()
        await writer.wait_closed()


async def _start_internal_server(handler: Any, port: int) -> asyncio.AbstractServer:
    return await asyncio.start_server(handler, host=RELAY_INTERNAL_LISTEN_HOST, port=port)


async def _handle_data_message(session: RelaySession, message: dict[str, Any]) -> bool:
    if not _relay_session_credentials_valid(session):
        await session.websocket.close(code=4403, reason="relay token rotated")
        return False
    stream_id = str(message.get("stream_id") or "")
    stream = session.streams.get(stream_id)
    if stream:
        data = decode_data_message(message)
        close_stream = False
        if not stream.record_received(len(data), RELAY_MAX_BODY_BYTES):
            close_stream = True
        else:
            stream.writer.write(data)
            try:
                await asyncio.wait_for(stream.writer.drain(), timeout=RELAY_STREAM_IDLE_TIMEOUT_SECONDS)
            except TimeoutError:
                close_stream = True
        if close_stream:
            async with session.stream_lock:
                session.streams.pop(stream_id, None)
            await stream.close()
    return True


async def _receive_session_message(session: RelaySession) -> dict[str, Any]:
    message = await _receive_json(session.websocket, storage.RELAY_HEARTBEAT_TIMEOUT_SECONDS)
    session.last_seen_monotonic = time.monotonic()
    return message


async def _open_relay_session(
    runner_id: str,
    token: str,
    token_version: int,
    websocket: WebSocket,
    port: int,
    handler: Any,
) -> RelaySession | None:
    async with SESSION_LOCK:
        old_session = ACTIVE_SESSIONS.get(runner_id)
        if old_session:
            ACTIVE_SESSIONS.pop(runner_id, None)
            storage.mark_probe_runner_relay_disconnected(runner_id, "relay session replaced")
            await old_session.close()
        server = await _start_internal_server(handler, port)
        session = RelaySession(runner_id=runner_id, token=token, token_version=token_version, websocket=websocket, server=server)
        ACTIVE_SESSIONS[runner_id] = session
        return session


@app.websocket("/relay/connect")
async def relay_connect(websocket: WebSocket) -> None:
    acquired = await _acquire_public_connection()
    if not acquired:
        await websocket.close(code=4408, reason="relay connection limit exceeded")
        return
    await websocket.accept()
    session: RelaySession | None = None
    runner_id = ""
    disconnect_reason = "client disconnected"
    try:
        try:
            hello = await _receive_json(websocket, RELAY_HELLO_TIMEOUT_SECONDS)
        except TimeoutError:
            await websocket.close(code=4408, reason="relay hello timeout")
            return
        except ValueError:
            await websocket.close(code=4400, reason="invalid relay message")
            return
        if hello.get("type") != "hello":
            await websocket.close(code=4400, reason="invalid hello")
            return
        runner_id = str(hello.get("runner_id") or "").strip()
        token = str(hello.get("relay_token") or "").strip()
        token_version_text = str(hello.get("relay_token_version") or "").strip()
        if not token_version_text.isdigit():
            await websocket.close(code=4400, reason="invalid hello")
            return
        token_version = int(token_version_text)
        runner = storage.verify_probe_runner_relay_token(runner_id, token, token_version)
        auth_key = _auth_failure_key(websocket, runner_id)
        if not runner:
            storage.mark_probe_runner_relay_auth_failed(runner_id)
            await _record_auth_failure(auth_key)
            await websocket.close(code=4403, reason="relay token invalid")
            return
        _clear_auth_failure(auth_key)
        port = int(runner.get("allocated_internal_port") or 0)
        if port <= 0:
            await websocket.close(code=4400, reason="runner has no internal port")
            return
        session_holder: dict[str, RelaySession] = {}

        async def handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            current = session_holder.get("session")
            if current is None:
                writer.close()
                await writer.wait_closed()
                return
            await _tcp_client_connected(current, reader, writer)

        session = await _open_relay_session(runner_id, token, token_version, websocket, port, handle_tcp)
        if session is None:
            return
        session_holder["session"] = session
        storage.mark_probe_runner_relay_connected(runner_id)
        await session.send_json({"type": "ready"})
        while True:
            try:
                message = await _receive_session_message(session)
            except TimeoutError:
                disconnect_reason = "relay heartbeat timeout"
                await websocket.close(code=4408, reason="relay heartbeat timeout")
                return
            except ValueError:
                disconnect_reason = "invalid relay message"
                await websocket.close(code=4400, reason="invalid relay message")
                return
            message_type = str(message.get("type") or "")
            if message_type == "heartbeat":
                if not _relay_session_credentials_valid(session):
                    disconnect_reason = "relay token rotated"
                    await websocket.close(code=4403, reason="relay token rotated")
                    return
                session.last_seen_monotonic = time.monotonic()
                storage.mark_probe_runner_relay_seen(runner_id)
                await session.send_json({"type": "heartbeat_ack"})
            elif message_type == "data":
                try:
                    keep_running = await _handle_data_message(session, message)
                except ValueError:
                    disconnect_reason = "invalid relay message"
                    await websocket.close(code=4400, reason="invalid relay message")
                    return
                if not keep_running:
                    disconnect_reason = "relay token rotated"
                    return
            elif message_type in {"close", "error"}:
                async with session.stream_lock:
                    stream = session.streams.pop(str(message.get("stream_id") or ""), None)
                if stream:
                    await stream.close()
            else:
                disconnect_reason = "invalid relay message"
                await websocket.close(code=4400, reason="invalid relay message")
                return
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        if runner_id:
            storage.mark_probe_runner_relay_disconnected(runner_id, str(exc)[:500])
        raise
    finally:
        if session:
            active_session = False
            async with SESSION_LOCK:
                if ACTIVE_SESSIONS.get(runner_id) is session:
                    ACTIVE_SESSIONS.pop(runner_id, None)
                    active_session = True
            if active_session:
                storage.mark_probe_runner_relay_disconnected(runner_id, disconnect_reason)
            await session.close()
        await _release_public_connection()


def main() -> None:
    _prepare_runtime()
    if not RELAY_ENABLED:
        print("PULSEGUARD_RELAY_ENABLED is not enabled; relay server still starts for explicit compose usage.", flush=True)
    asyncio.run(_serve())


def _prepare_runtime() -> None:
    ensure_runtime_dirs()
    storage.init_db()
    ensure_relay_certificate()
    relay_control_token()
    storage.mark_relay_runners_restarted()


async def _serve() -> None:
    public = uvicorn.Server(_public_config())
    control = uvicorn.Server(_control_config())
    await asyncio.gather(public.serve(), control.serve())


def _public_config() -> uvicorn.Config:
    return uvicorn.Config(
        app,
        host="0.0.0.0",
        port=RELAY_PUBLIC_PORT,
        ssl_certfile=str(RELAY_CERT_FILE),
        ssl_keyfile=str(RELAY_KEY_FILE),
        log_level="info",
        ws_max_size=RELAY_MAX_FRAME_BYTES,
        ws_per_message_deflate=False,
    )


def _control_config() -> uvicorn.Config:
    return uvicorn.Config(
        control_app,
        host=RELAY_CONTROL_HOST,
        port=RELAY_CONTROL_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
