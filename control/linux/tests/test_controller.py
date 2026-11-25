import asyncio

import pytest
from evdev import ecodes

from cokvm_linux import vss
from cokvm_linux.app import Config, Controller, FrameSender


class FakeTransport:
    def __init__(self, authenticated=True):
        self.authenticated = authenticated
        self.frames = []

    async def connect(self):
        return None

    async def send(self, frame):
        self.frames.append(frame)

    async def close(self):
        return None


class FakeSource:
    def __init__(self):
        self.grabbed = False
        self.closed = False

    def set_grab(self, enabled):
        self.grabbed = enabled

    def close(self):
        self.closed = True


@pytest.fixture
async def env():
    transport = FakeTransport()
    sender = FrameSender(transport, interval=0)
    source = FakeSource()
    controller = Controller(
        Config(),
        sender,
        transport,
        source_factory=lambda paths, callback: source,
    )
    controller.open_source([])
    sender.start()
    yield controller, sender, transport, source
    await sender.stop()


async def test_enter_and_exit_via_hotkey(env):
    controller, sender, transport, source = env
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1) is None
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1) is None
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    assert coro is not None
    await coro
    assert controller.state == "CAPTURING"
    assert source.grabbed is True

    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 0)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)

    await asyncio.sleep(0.16)  # let the hotkey cooldown expire

    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1) is None
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1) is None
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    assert coro is not None
    await coro
    assert controller.state == "MONITOR"
    assert source.grabbed is False


async def test_keyboard_frames(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_A, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [0x04])
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_A, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [])


async def test_modifier_frame(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(vss.MOD_LSHIFT, [])


async def test_six_key_rollover(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    for code in (ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_C,
                 ecodes.KEY_D, ecodes.KEY_E, ecodes.KEY_F):
        controller.handle_event(ecodes.EV_KEY, code, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_G, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [0x04, 0x05, 0x06, 0x07, 0x08, 0x09])


async def test_mouse_motion_uses_resolution_scale(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_REL, ecodes.REL_X, 10)
    controller.handle_event(ecodes.EV_REL, ecodes.REL_Y, 5)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0, 8730, 8720, 0)


async def test_mouse_buttons_and_wheel(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0x01, 8640, 8640, 0)

    controller.handle_event(ecodes.EV_REL, ecodes.REL_WHEEL, 1)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0x01, 8640, 8640, 120)


async def test_hotkey_escape_is_not_forwarded(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1)
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    await coro
    await sender.drain()
    assert vss.keyboard_frame(0, [0x29]) not in transport.frames
    assert vss.keyboard_frame(0, []) in transport.frames


async def test_force_release_restores_local_input(env):
    controller, sender, transport, source = env
    controller.state = "CAPTURING"
    source.grabbed = True
    controller.force_release("disconnect")
    assert controller.state == "MONITOR"
    assert source.grabbed is False


async def test_cannot_enter_without_authenticated_link(env):
    controller, sender, transport, source = env
    transport.authenticated = False
    await controller.enter_capture()
    assert controller.state == "MONITOR"
    assert source.grabbed is False


async def test_both_ctrl_sides_keep_modifier_bit(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_RIGHTCTRL, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(vss.MOD_LCTRL, [])
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(vss.MOD_LCTRL, [])


async def test_graceful_release_sends_all_up_and_clears_buttons(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_A, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert source.grabbed is True

    transport.frames.clear()
    await controller.graceful_release("shutdown")

    assert controller.state == "MONITOR"
    assert source.grabbed is False
    assert vss.keyboard_frame(0, []) in transport.frames
    assert vss.mouse_frame(0, 8640, 8640, 0) in transport.frames


async def test_pending_motion_does_not_leak_between_captures(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_REL, ecodes.REL_X, 100)
    # no SYN: the delta must not survive the next capture
    await controller.exit_capture("test")
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0, 8640, 8640, 0)
