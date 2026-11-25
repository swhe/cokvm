import asyncio
from types import SimpleNamespace

import pytest

from cokvm_linux import app
from cokvm_linux.app import Config, Controller, DryRunTransport


async def test_dry_run_transport_is_authenticated(capsys):
    transport = DryRunTransport()
    assert transport.authenticated is True
    await transport.send(b"\x00" * 22)
    captured = capsys.readouterr()
    assert "frame" in captured.err


async def test_hotplug_continues_after_open_source_failure(monkeypatch):
    infos = [SimpleNamespace(path="/dev/input/event1")]
    monkeypatch.setattr(app.devices, "enumerate_devices", lambda: infos)
    monkeypatch.setattr(
        app.devices, "select", lambda devices, include, exclude: devices)

    ticks = []

    async def fake_sleep(seconds, stop):
        if ticks:
            stop.set()
        else:
            ticks.append(1)

    monkeypatch.setattr(app, "_sleep_or_stop", fake_sleep)

    class FakeController:
        state = "MONITOR"
        paths = ["/dev/input/event0"]

        def __init__(self):
            self.open_attempts = 0

        def open_source(self, paths):
            self.open_attempts += 1
            raise OSError("device vanished")

    controller = FakeController()
    stop = asyncio.Event()
    task = asyncio.create_task(app._hotplug_loop(controller, app.Config(), stop))
    await asyncio.wait_for(task, 1.0)

    assert task.exception() is None
    assert controller.open_attempts == 1


async def test_connection_loop_sends_neutral_and_releases_on_disconnect():
    from cokvm_linux import app

    class FakeTransport:
        def __init__(self):
            self.authenticated = False

        async def connect(self):
            self.authenticated = True

    class FakeSender:
        def __init__(self):
            self.drains = 0

        async def drain(self, timeout=0.2):
            self.drains += 1

    class FakeController:
        def __init__(self):
            self.neutral = 0
            self.released = []
            self.sender = FakeSender()

        def send_neutral(self):
            self.neutral += 1

        def force_release(self, reason):
            self.released.append(reason)

    transport = FakeTransport()
    controller = FakeController()
    disconnected = asyncio.Event()
    stop = asyncio.Event()
    task = asyncio.create_task(
        app._connection_loop(controller, transport, disconnected, stop))
    await asyncio.sleep(0.01)
    assert controller.neutral == 1
    assert controller.sender.drains == 1
    disconnected.set()
    await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 1.0)
    assert controller.released == ["ble disconnect"]


def test_open_source_failure_keeps_paths_empty_for_retry():
    class _Transport:
        authenticated = True

    def factory(paths, callback):
        raise OSError("device vanished")

    controller = Controller(Config(), None, _Transport(), factory)
    with pytest.raises(OSError):
        controller.open_source(["/dev/input/event0"])
    assert controller.paths == []
