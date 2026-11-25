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


def test_open_source_failure_keeps_paths_empty_for_retry():
    class _Transport:
        authenticated = True

    def factory(paths, callback):
        raise OSError("device vanished")

    controller = Controller(Config(), None, _Transport(), factory)
    with pytest.raises(OSError):
        controller.open_source(["/dev/input/event0"])
    assert controller.paths == []
