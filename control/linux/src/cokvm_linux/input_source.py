"""Read evdev events through the asyncio selector."""

from __future__ import annotations

import asyncio
import logging
import os

import evdev

log = logging.getLogger(__name__)


class EvdevEventSource:
    def __init__(self, loop: asyncio.AbstractEventLoop, paths: list[str], on_event,
                 open_device=evdev.InputDevice):
        self._loop = loop
        self._on_event = on_event
        self._devices: dict[int, object] = {}
        try:
            for path in paths:
                device = open_device(path)
                try:
                    os.set_blocking(device.fd, False)
                except OSError:
                    pass
                self._loop.add_reader(device.fd, self._on_readable, device)
                self._devices[device.fd] = device
        except Exception:
            self.close()
            raise

    def _on_readable(self, device) -> None:
        try:
            for event in device.read():
                self._on_event(event.type, event.code, event.value)
        except (BlockingIOError, OSError):
            pass

    def set_grab(self, enabled: bool) -> None:
        for device in self._devices.values():
            try:
                if enabled:
                    device.grab()
                else:
                    device.ungrab()
            except OSError as exc:
                log.warning("grab %s failed: %s", getattr(device, "path", "?"), exc)

    def close(self) -> None:
        for fd, device in list(self._devices.items()):
            try:
                self._loop.remove_reader(fd)
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass
        self._devices.clear()
