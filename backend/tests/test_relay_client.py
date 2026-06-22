from __future__ import annotations

import asyncio
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


class RelayClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_pump_uses_idle_timeout_and_removes_closed_stream(self) -> None:
        streams: dict[str, TunnelStream] = {
            "stream-1": TunnelStream(reader=FakeReader(), writer=FakeWriter())  # type: ignore[arg-type]
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
