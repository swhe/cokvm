import asyncio

import pytest

from cokvm_linux.ble import BleError, BleTransport, backoff_delays


class FakeClient:
    def __init__(self, reads, write_error=None, write_outcomes=None):
        self._reads = list(reads)
        self._write_error = write_error
        self._write_outcomes = list(write_outcomes) if write_outcomes is not None else None
        self.paired = False
        self.disconnected = False
        self.write_calls = 0

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
        self.write_calls += 1
        if self._write_outcomes is not None:
            outcome = self._write_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return
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


async def test_connect_raises_when_device_not_found():
    async def find():
        return None

    transport = BleTransport(
        "CoKVM-Dongle",
        find_device=find,
        client_factory=lambda device: FakeClient([b"OK"]),
    )
    with pytest.raises(BleError):
        await transport.connect()
    assert transport.authenticated is False


async def test_send_while_unauthenticated_does_not_write():
    client = FakeClient([b"OK"])
    transport = make_transport(client)
    await transport.send(b"\x00" * 22)
    assert client.write_calls == 0


async def test_close_detaches_and_disconnects_client():
    client = FakeClient([b"OK"])
    transport = make_transport(client)
    await transport.connect()
    await transport.close()
    assert transport._client is None
    assert transport.authenticated is False
    assert client.disconnected is True


async def test_reconnect_closes_previous_client():
    client1 = FakeClient([b"OK"])
    client2 = FakeClient([b"OK"])
    clients = [client1, client2]
    transport = BleTransport(
        "CoKVM-Dongle",
        find_device=None,
        client_factory=lambda device: clients.pop(0),
    )

    async def find():
        return object()

    transport._find_device = find
    await transport.connect()
    await transport.connect()
    assert client1.disconnected is True
    assert transport.authenticated is True
    assert transport._client is client2


async def test_successful_write_resets_failure_count():
    client = FakeClient(
        [b"OK"],
        write_outcomes=[RuntimeError("a"), RuntimeError("b"), None, None],
    )
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
    for _ in range(4):
        await transport.send(b"\x00" * 22)
    await asyncio.sleep(0)
    assert transport.authenticated is True
    assert not disconnected.is_set()
