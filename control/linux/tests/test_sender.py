import asyncio

import pytest

from cokvm_linux.sender import FrameSender


class RecordingTransport:
    def __init__(self):
        self.frames = []

    async def send(self, frame: bytes):
        self.frames.append(frame)


async def test_keyboard_has_priority_and_motion_is_coalesced():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_motion(b"m1")
    sender.submit_motion(b"m2")
    sender.submit_discrete(b"d1")
    sender.submit_keyboard(b"k1")
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == [b"k1", b"d1", b"m2"]


async def test_keyboard_frames_preserve_order():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_keyboard(b"k1")
    sender.submit_keyboard(b"k2")
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == [b"k1", b"k2"]


async def test_clear_drops_pending_frames():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_keyboard(b"k1")
    sender.submit_motion(b"m1")
    sender.clear()
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == []


async def test_second_start_raises_runtime_error():
    sender = FrameSender(RecordingTransport(), interval=0)
    sender.start()
    try:
        with pytest.raises(RuntimeError):
            sender.start()
    finally:
        await sender.stop()


async def test_clear_does_not_mark_idle_while_send_is_in_flight():
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowTransport:
        async def send(self, frame):
            started.set()
            await release.wait()

    sender = FrameSender(SlowTransport(), interval=0)
    sender.submit_keyboard(b"k1")
    sender.start()
    await started.wait()
    sender.clear()
    drain_task = asyncio.create_task(sender.drain(timeout=1.0))
    await asyncio.sleep(0.01)
    assert not drain_task.done()
    release.set()
    await drain_task
    assert sender._idle.is_set()
    await sender.stop()
