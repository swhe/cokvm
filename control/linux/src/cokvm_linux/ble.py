"""BLE transport for the CoKVM VSS service."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient, BleakScanner

log = logging.getLogger(__name__)

SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
DATA_UUID = "0000ff1d-0000-1000-8000-00805f9b34fb"
INFO_UUID = "0000ff2c-0000-1000-8000-00805f9b34fb"
OK = b"OK"
MAX_WRITE_FAILURES = 3


class BleError(Exception):
    pass


def backoff_delays(max_delay: float = 30.0):
    delay = 1.0
    while True:
        yield min(delay, max_delay)
        delay *= 2


class BleTransport:
    def __init__(self, device_name: str, on_disconnect=None,
                 scanner_timeout: float = 10.0, connect_timeout: float = 15.0,
                 write_timeout: float = 1.0, find_device=None, client_factory=None):
        self._device_name = device_name
        self._on_disconnect_cb = on_disconnect
        self._scanner_timeout = scanner_timeout
        self._connect_timeout = connect_timeout
        self._write_timeout = write_timeout
        self._find_device = find_device or self._bleak_find
        self._client_factory = client_factory or self._bleak_client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._write_failures = 0
        self.authenticated = False

    async def _bleak_find(self):
        return await BleakScanner.find_device_by_filter(
            lambda device, adv: (device.name or adv.local_name) == self._device_name,
            timeout=self._scanner_timeout,
        )

    def _bleak_client(self, device):
        return BleakClient(device, disconnected_callback=self._on_disconnect)

    def _on_disconnect(self, client) -> None:
        self.authenticated = False
        if self._loop is not None and self._on_disconnect_cb is not None:
            self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        device = await self._find_device()
        if device is None:
            raise BleError(f"device {self._device_name!r} not found")
        client = self._client_factory(device)
        self._client = client
        try:
            await client.connect(timeout=self._connect_timeout)
            try:
                data = await client.read_gatt_char(INFO_UUID)
            except Exception:
                await client.pair()
                data = await client.read_gatt_char(INFO_UUID)
        except Exception as exc:
            self._client = None
            try:
                await client.disconnect()
            except Exception:
                pass
            raise BleError(f"connect failed: {exc}") from exc
        if data != OK:
            self._client = None
            try:
                await client.disconnect()
            except Exception:
                pass
            raise BleError(f"authentication failed: {data!r}")
        self.authenticated = True
        self._write_failures = 0
        log.info("connected to %s", self._device_name)

    async def send(self, frame: bytes) -> None:
        client = self._client
        if not self.authenticated or client is None:
            log.debug("dropping frame: not connected")
            return
        try:
            await asyncio.wait_for(
                client.write_gatt_char(DATA_UUID, frame, response=False),
                timeout=self._write_timeout,
            )
            self._write_failures = 0
        except Exception as exc:
            self._write_failures += 1
            log.warning("write failed (%d/%d): %s",
                        self._write_failures, MAX_WRITE_FAILURES, exc)
            if self._write_failures >= MAX_WRITE_FAILURES:
                self.authenticated = False
                if self._loop is not None and self._on_disconnect_cb is not None:
                    self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    async def close(self) -> None:
        self.authenticated = False
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
