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
