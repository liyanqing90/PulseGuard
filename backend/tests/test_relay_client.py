from __future__ import annotations

import asyncio
import hashlib
import unittest
from unittest.mock import AsyncMock, patch

from backend.app import relay_client
from backend.app.relay_tunnel import TunnelStream


class FakeReader:
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


class FakeSslObject:
    def __init__(self, cert: bytes | None) -> None:
        self.cert = cert

    def getpeercert(self, *, binary_form: bool = False) -> bytes | None:
        return self.cert if binary_form else None


class FakeTransport:
    def __init__(self, cert: bytes | None) -> None:
        self.ssl_object = FakeSslObject(cert) if cert is not None else None

    def get_extra_info(self, name: str) -> object | None:
        return self.ssl_object if name == "ssl_object" else None


class FakeWebsocket:
    def __init__(self, cert: bytes | None) -> None:
        self.transport = FakeTransport(cert)


class RelayClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fingerprint_requires_peer_certificate(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "TLS certificate is unavailable"):
            relay_client._assert_fingerprint(FakeWebsocket(None), "00")  # type: ignore[arg-type]

    async def test_fingerprint_accepts_matching_certificate(self) -> None:
        cert = b"relay-cert"
        relay_client._assert_fingerprint(  # type: ignore[arg-type]
            FakeWebsocket(cert),
            hashlib.sha256(cert).hexdigest(),
        )

    async def test_relay_url_must_use_wss_before_sending_token(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PULSEGUARD_RELAY_URL": "ws://127.0.0.1:9443/relay/connect",
                "PULSEGUARD_RUNNER_ID": "edge-1",
                "PULSEGUARD_RELAY_TOKEN": "pgrl_secret",
                "PULSEGUARD_RELAY_FINGERPRINT": "00",
            },
            clear=False,
        ), patch("backend.app.relay_client.websockets.connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "must use wss://"):
                await relay_client.run_once()

        connect.assert_not_called()

    async def test_worker_pump_uses_idle_timeout_and_removes_closed_stream(self) -> None:
        writer = FakeWriter()
        streams: dict[str, TunnelStream] = {
            "stream-1": TunnelStream(reader=FakeReader(), writer=writer)  # type: ignore[arg-type]
        }

        with patch("backend.app.relay_client.RELAY_STREAM_IDLE_TIMEOUT_SECONDS", 12), patch(
            "backend.app.relay_client.pump_reader_to_sender",
            new_callable=AsyncMock,
        ) as pump_reader_to_sender:
            await relay_client._pump_worker_to_relay(  # type: ignore[arg-type]
                "stream-1",
                FakeReader(),
                object(),
                asyncio.Lock(),
                streams,
            )

        pump_reader_to_sender.assert_awaited_once()
        self.assertEqual(pump_reader_to_sender.call_args.kwargs["idle_timeout_seconds"], 12)
        self.assertTrue(writer.closed)
        self.assertNotIn("stream-1", streams)

    async def test_relay_data_closes_worker_stream_when_drain_times_out(self) -> None:
        writer = SlowDrainWriter()
        streams: dict[str, TunnelStream] = {
            "stream-1": TunnelStream(reader=FakeReader(), writer=writer)  # type: ignore[arg-type]
        }

        with patch("backend.app.relay_client.RELAY_STREAM_IDLE_TIMEOUT_SECONDS", 0.01):
            await relay_client._handle_relay_data_message(
                "stream-1",
                {"type": "data", "stream_id": "stream-1", "data": "cGF5bG9hZA=="},
                streams,
            )

        self.assertEqual(writer.writes, [b"payload"])
        self.assertTrue(writer.closed)
        self.assertNotIn("stream-1", streams)

    async def test_relay_data_rejects_invalid_payload_even_for_unknown_stream(self) -> None:
        with self.assertRaisesRegex(ValueError, "not valid base64"):
            await relay_client._handle_relay_data_message(
                "missing-stream",
                {"type": "data", "stream_id": "missing-stream", "data": "not-base64!"},
                {},
            )

    async def test_heartbeat_ack_is_valid_noop(self) -> None:
        await relay_client._handle_relay_message({"type": "heartbeat_ack"}, object(), asyncio.Lock(), {})

    async def test_unknown_relay_message_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid relay message"):
            await relay_client._handle_relay_message({"type": "bogus"}, object(), asyncio.Lock(), {})
