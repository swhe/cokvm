import asyncio

import pytest

from cokvm_linux.ble import BleError, BleTransport, backoff_delays


class FakeClient:
    def __init__(self, reads, write_error=None):
        self._reads = list(reads)
        self._write_error = write_error
        self.paired = False
        self.disconnected = False

    async def connect(self, timeout=None):
        return None

    async def read_gatt_char(self, uuid):
        item = self._reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def pair(self):
        self.paired = True

    async def disconnect(self):
        self.disconnected = True

    async def write_gatt_char(self, uuid, frame, response=True):
        if self._write_error is not None:
            raise self._write_error


def make_transport(client):
    async def find():
        return object()

    return BleTransport(
        "CoKVM-Dongle",
        find_device=find,
        client_factory=lambda device: client,
    )


def test_backoff_sequence_is_capped():
    gen = backoff_delays(max_delay=30.0)
    values = [next(gen) for _ in range(8)]
    assert values == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


async def test_connect_authenticates_with_ok():
    client = FakeClient([b"OK"])
    transport = make_transport(client)
    await transport.connect()
    assert transport.authenticated is True


async def test_connect_pairs_after_security_error():
    client = FakeClient([RuntimeError("encrypt"), b"OK"])
    transport = make_transport(client)
    await transport.connect()
    assert client.paired is True
    assert transport.authenticated is True


async def test_connect_rejects_bad_handshake():
    client = FakeClient([b"NO"])
    transport = make_transport(client)
    with pytest.raises(BleError):
        await transport.connect()
    assert transport.authenticated is False
    assert client.disconnected is True


async def test_three_write_failures_trigger_disconnect_callback():
    client = FakeClient([b"OK"], write_error=RuntimeError("link lost"))
    disconnected = asyncio.Event()
    transport = BleTransport(
        "CoKVM-Dongle",
        on_disconnect=disconnected.set,
        find_device=None,
        client_factory=lambda device: client,
    )

    async def find():
        return object()

    transport._find_device = find
    await transport.connect()
    for _ in range(3):
        await transport.send(b"\x00" * 22)
    await asyncio.sleep(0)
    assert transport.authenticated is False
    assert disconnected.is_set()
