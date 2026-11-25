"""Read evdev events through the asyncio selector."""

from __future__ import annotations

import asyncio
import errno
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
        self._grabbed = False
        try:
            for path in paths:
                try:
                    device = open_device(path)
                except OSError as exc:
                    log.warning("cannot open %s: %s", path, exc)
                    continue
                self._devices[device.fd] = device
                try:
                    os.set_blocking(device.fd, False)
                except OSError as exc:
                    log.warning("set_blocking %s failed: %s",
                                getattr(device, "path", "?"), exc)
                self._loop.add_reader(device.fd, self._on_readable, device)
        except Exception:
            self.close()
            raise

    def _on_readable(self, device) -> None:
        try:
            for event in device.read():
                self._on_event(event.type, event.code, event.value)
        except BlockingIOError:
            pass
        except OSError as exc:
            if exc.errno == errno.EINTR:
                return
            log.warning("read %s failed, dropping device: %s",
                        getattr(device, "path", "?"), exc)
            self._remove(device)

    def _remove(self, device) -> None:
        fd = device.fd
        try:
            self._loop.remove_reader(fd)
        except Exception:
            pass
        try:
            device.close()
        except Exception:
            pass
        self._devices.pop(fd, None)

    def set_grab(self, enabled: bool) -> None:
        if enabled == self._grabbed:
            return
        for device in self._devices.values():
            try:
                if enabled:
                    device.grab()
                else:
                    device.ungrab()
            except OSError as exc:
                log.warning("grab %s failed: %s", getattr(device, "path", "?"), exc)
        self._grabbed = enabled

    def close(self) -> None:
        for device in list(self._devices.values()):
            self._remove(device)
        self._grabbed = False
