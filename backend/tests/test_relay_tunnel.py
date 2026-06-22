from __future__ import annotations

import asyncio
import base64
import unittest

from backend.app.relay_tunnel import TunnelStream, pump_reader_to_sender


class FakeReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        await asyncio.sleep(0)
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class SlowReader:
    async def read(self, _size: int) -> bytes:
        await asyncio.sleep(1)
        return b"late"


class FakeWriter:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class RelayTunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_pump_reader_to_sender_caps_cumulative_bytes(self) -> None:
        sent: list[dict[str, object]] = []

        async def send_json(message: dict[str, object]) -> None:
            sent.append(message)

        await pump_reader_to_sender("stream-1", FakeReader([b"abc", b"def"]), send_json, max_bytes=5)

        self.assertEqual([message["type"] for message in sent], ["data", "close"])
        self.assertEqual(base64.b64decode(str(sent[0]["data"])), b"abc")

    async def test_pump_reader_to_sender_closes_idle_stream(self) -> None:
        sent: list[dict[str, object]] = []

        async def send_json(message: dict[str, object]) -> None:
            sent.append(message)

        await pump_reader_to_sender("stream-1", SlowReader(), send_json, idle_timeout_seconds=0.01)  # type: ignore[arg-type]

        self.assertEqual(sent, [{"type": "close", "stream_id": "stream-1"}])

    async def test_tunnel_stream_caps_cumulative_received_bytes(self) -> None:
        stream = TunnelStream(reader=FakeReader([]), writer=FakeWriter())  # type: ignore[arg-type]

        self.assertTrue(stream.record_received(3, max_bytes=5))
        self.assertFalse(stream.record_received(3, max_bytes=5))

    async def test_tunnel_stream_close_waits_for_cancelled_tasks(self) -> None:
        task_cancelled = asyncio.Event()

        async def wait_forever() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                task_cancelled.set()

        task = asyncio.create_task(wait_forever())
        stream = TunnelStream(reader=FakeReader([]), writer=FakeWriter())  # type: ignore[arg-type]
        stream.tasks.add(task)
        await asyncio.sleep(0)

        await stream.close()

        self.assertTrue(task.done())
        self.assertTrue(task_cancelled.is_set())
        self.assertNotIn(task, stream.tasks)
