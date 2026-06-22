from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import relay_server


class FakeServer:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.close_args: tuple[object, ...] | None = None
        self.close_kwargs: dict[str, object] | None = None

    async def send_text(self, message: str) -> None:
        self.messages.append(message)

    async def close(self, *args: object, **kwargs: object) -> None:
        self.close_args = args
        self.close_kwargs = kwargs


class TextWebSocket:
    def __init__(self, text: str) -> None:
        self.text = text

    async def receive_text(self) -> str:
        return self.text


class WaitingWebSocket:
    async def receive_text(self) -> str:
        await asyncio.Event().wait()
        return "{}"


class BlockingReader:
    def __init__(self) -> None:
        self.done = asyncio.Event()

    async def read(self, _size: int) -> bytes:
        await self.done.wait()
        return b""


class EmptyReader:
    async def read(self, _size: int) -> bytes:
        return b""


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class SlowDrainWriter(FakeWriter):
    async def drain(self) -> None:
        await asyncio.Event().wait()


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class RelayServerControlTests(unittest.TestCase):
    def tearDown(self) -> None:
        relay_server.ACTIVE_SESSIONS.clear()

    def test_control_revoke_requires_token(self) -> None:
        with patch("backend.app.relay_server.relay_control_token", return_value="pgrc_secret"):
            response = TestClient(relay_server.control_app).post(
                "/relay/control/revoke",
                json={"runner_id": "edge-1"},
                headers={"Authorization": "Bearer wrong"},
            )

        self.assertEqual(response.status_code, 403)

    def test_control_revoke_closes_active_session(self) -> None:
        session = FakeSession()
        relay_server.ACTIVE_SESSIONS["edge-1"] = session  # type: ignore[assignment]

        with patch("backend.app.relay_server.relay_control_token", return_value="pgrc_secret"), patch(
            "backend.app.relay_server.storage.mark_probe_runner_relay_disconnected"
        ) as mark_disconnected:
            response = TestClient(relay_server.control_app).post(
                "/relay/control/revoke",
                json={"runner_id": "edge-1", "reason": "deployment command regenerated"},
                headers={"Authorization": "Bearer pgrc_secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "revoked": True})
        self.assertTrue(session.closed)
        self.assertNotIn("edge-1", relay_server.ACTIVE_SESSIONS)
        mark_disconnected.assert_called_once_with("edge-1", "deployment command regenerated")

    def test_prepare_runtime_invalidates_stale_relay_sessions(self) -> None:
        with patch("backend.app.relay_server.ensure_runtime_dirs") as ensure_runtime_dirs, patch(
            "backend.app.relay_server.storage.init_db"
        ) as init_db, patch("backend.app.relay_server.ensure_relay_certificate") as ensure_relay_certificate, patch(
            "backend.app.relay_server.relay_control_token"
        ) as relay_control_token, patch(
            "backend.app.relay_server.storage.mark_relay_runners_restarted"
        ) as mark_restarted:
            relay_server._prepare_runtime()

        ensure_runtime_dirs.assert_called_once()
        init_db.assert_called_once()
        ensure_relay_certificate.assert_called_once()
        relay_control_token.assert_called_once()
        mark_restarted.assert_called_once()

    def test_public_config_caps_frames_and_disables_compression(self) -> None:
        with patch("backend.app.relay_server.RELAY_MAX_FRAME_BYTES", 12345):
            config = relay_server._public_config()

        self.assertEqual(config.ws_max_size, 12345)
        self.assertFalse(config.ws_per_message_deflate)


class RelayServerEntryGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        relay_server.PUBLIC_CONNECTIONS = 0
        relay_server.AUTH_FAILURES.clear()

    async def test_public_connection_limit_rejects_after_cap(self) -> None:
        with patch("backend.app.relay_server.RELAY_MAX_PUBLIC_CONNECTIONS", 1):
            self.assertTrue(await relay_server._acquire_public_connection())
            self.assertFalse(await relay_server._acquire_public_connection())
            await relay_server._release_public_connection()

        self.assertEqual(relay_server.PUBLIC_CONNECTIONS, 0)

    async def test_receive_json_times_out_waiting_for_hello(self) -> None:
        with self.assertRaises(TimeoutError):
            await relay_server._receive_json(WaitingWebSocket(), timeout_seconds=0.01)  # type: ignore[arg-type]

    async def test_session_receive_uses_relay_heartbeat_timeout(self) -> None:
        session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=WaitingWebSocket(),  # type: ignore[arg-type]
            server=FakeServer(),  # type: ignore[arg-type]
        )

        with patch("backend.app.relay_server.storage.RELAY_HEARTBEAT_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(TimeoutError):
                await relay_server._receive_session_message(session)

    async def test_receive_json_rejects_oversized_message(self) -> None:
        with patch("backend.app.relay_server.RELAY_MAX_FRAME_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "too large"):
                await relay_server._receive_json(TextWebSocket('{"type":"hello"}'))  # type: ignore[arg-type]

    async def test_auth_failure_backoff_increases_and_is_cleared(self) -> None:
        with patch("backend.app.relay_server.RELAY_AUTH_BACKOFF_BASE_SECONDS", 0.25), patch(
            "backend.app.relay_server.RELAY_AUTH_BACKOFF_MAX_SECONDS", 1.0
        ), patch("backend.app.relay_server.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await relay_server._record_auth_failure("edge-1")
            await relay_server._record_auth_failure("edge-1")
            relay_server._clear_auth_failure("edge-1")

        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.25, 0.5])
        self.assertNotIn("edge-1", relay_server.AUTH_FAILURES)


class RelayServerStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        relay_server.ACTIVE_SESSIONS.clear()

    async def test_duplicate_fresh_session_is_rejected_without_replacing_old_session(self) -> None:
        old_server = FakeServer()
        old_websocket = FakeWebSocket()
        old_session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=old_websocket,  # type: ignore[arg-type]
            server=old_server,  # type: ignore[arg-type]
        )
        new_websocket = FakeWebSocket()
        relay_server.ACTIVE_SESSIONS["edge-1"] = old_session

        async def handler(_reader: object, _writer: object) -> None:
            return None

        with patch("backend.app.relay_server.storage.verify_probe_runner_relay_token", return_value={"ok": True}), patch(
            "backend.app.relay_server._start_internal_server",
            new=AsyncMock(),
        ) as start_server:
            result = await relay_server._open_relay_session(  # type: ignore[arg-type]
                "edge-1",
                "relay-token",
                1,
                new_websocket,
                18001,
                handler,
            )

        self.assertIsNone(result)
        self.assertIs(relay_server.ACTIVE_SESSIONS["edge-1"], old_session)
        self.assertFalse(old_server.closed)
        self.assertEqual(new_websocket.close_kwargs, {"code": 4409, "reason": "runner already connected"})
        start_server.assert_not_called()

    async def test_duplicate_stale_session_is_replaced(self) -> None:
        old_server = FakeServer()
        old_session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=FakeWebSocket(),  # type: ignore[arg-type]
            server=old_server,  # type: ignore[arg-type]
        )
        old_session.last_seen_monotonic -= relay_server.storage.RELAY_HEARTBEAT_TIMEOUT_SECONDS + 1
        new_server = FakeServer()
        new_websocket = FakeWebSocket()
        relay_server.ACTIVE_SESSIONS["edge-1"] = old_session

        async def handler(_reader: object, _writer: object) -> None:
            return None

        with patch("backend.app.relay_server.storage.mark_probe_runner_relay_disconnected") as mark_disconnected, patch(
            "backend.app.relay_server._start_internal_server",
            new=AsyncMock(return_value=new_server),
        ):
            result = await relay_server._open_relay_session(  # type: ignore[arg-type]
                "edge-1",
                "relay-token",
                1,
                new_websocket,
                18001,
                handler,
            )

        self.assertIsNotNone(result)
        self.assertIs(relay_server.ACTIVE_SESSIONS["edge-1"], result)
        self.assertTrue(old_server.closed)
        self.assertIs(result.server, new_server)
        mark_disconnected.assert_called_once_with("edge-1", "stale relay session replaced")

    async def test_data_frame_revalidates_relay_token_before_writing_stream(self) -> None:
        websocket = FakeWebSocket()
        writer = FakeWriter()
        session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=websocket,  # type: ignore[arg-type]
            server=FakeServer(),  # type: ignore[arg-type]
        )
        session.streams["stream-1"] = relay_server.TunnelStream(  # type: ignore[arg-type]
            reader=EmptyReader(),
            writer=writer,
        )

        with patch("backend.app.relay_server.storage.verify_probe_runner_relay_token", return_value=None):
            keep_running = await relay_server._handle_data_message(
                session,
                {"type": "data", "stream_id": "stream-1", "data": "c2hvdWxkLW5vdC13cml0ZQ=="},
            )

        self.assertFalse(keep_running)
        self.assertEqual(websocket.close_kwargs, {"code": 4403, "reason": "relay token rotated"})
        self.assertEqual(writer.writes, [])

    async def test_data_frame_drain_timeout_removes_closed_stream(self) -> None:
        writer = SlowDrainWriter()
        session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=FakeWebSocket(),  # type: ignore[arg-type]
            server=FakeServer(),  # type: ignore[arg-type]
        )
        session.streams["stream-1"] = relay_server.TunnelStream(  # type: ignore[arg-type]
            reader=EmptyReader(),
            writer=writer,
        )

        with patch("backend.app.relay_server.RELAY_STREAM_IDLE_TIMEOUT_SECONDS", 0.01), patch(
            "backend.app.relay_server.storage.verify_probe_runner_relay_token",
            return_value={"ok": True},
        ):
            keep_running = await relay_server._handle_data_message(
                session,
                {"type": "data", "stream_id": "stream-1", "data": "cGF5bG9hZA=="},
            )

        self.assertTrue(keep_running)
        self.assertEqual(writer.writes, [b"payload"])
        self.assertTrue(writer.closed)
        self.assertNotIn("stream-1", session.streams)

    async def test_internal_server_binds_configured_internal_host(self) -> None:
        async def handler(_reader: object, _writer: object) -> None:
            return None

        server = object()
        with patch("backend.app.relay_server.RELAY_INTERNAL_LISTEN_HOST", "pulseguard-relay-internal"), patch(
            "backend.app.relay_server.asyncio.start_server",
            new=AsyncMock(return_value=server),
        ) as start_server:
            result = await relay_server._start_internal_server(handler, 18001)

        self.assertIs(result, server)
        start_server.assert_awaited_once_with(handler, host="pulseguard-relay-internal", port=18001)

    async def test_tcp_client_connection_rejects_extra_streams(self) -> None:
        websocket = FakeWebSocket()
        session = relay_server.RelaySession(
            runner_id="edge-1",
            token="relay-token",
            token_version=1,
            websocket=websocket,  # type: ignore[arg-type]
            server=FakeServer(),  # type: ignore[arg-type]
        )
        first_reader = BlockingReader()
        first_writer = FakeWriter()
        second_writer = FakeWriter()

        with patch("backend.app.relay_server.storage.verify_probe_runner_relay_token", return_value={"ok": True}):
            first = asyncio.create_task(
                relay_server._tcp_client_connected(  # type: ignore[arg-type]
                    session,
                    first_reader,
                    first_writer,
                )
            )
            for _ in range(50):
                if session.streams:
                    break
                await asyncio.sleep(0.01)

            await relay_server._tcp_client_connected(  # type: ignore[arg-type]
                session,
                EmptyReader(),
                second_writer,
            )
            first_reader.done.set()
            await first

        self.assertTrue(second_writer.closed)
        self.assertEqual(sum('"type":"open"' in message for message in websocket.messages), 1)
