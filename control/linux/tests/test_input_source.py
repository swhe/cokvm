from types import SimpleNamespace

import pytest

from cokvm_linux.input_source import EvdevEventSource


class FakeLoop:
    def __init__(self):
        self.readers = {}

    def add_reader(self, fd, callback, *args):
        self.readers[fd] = (callback, args)

    def remove_reader(self, fd):
        self.readers.pop(fd, None)


class FakeDevice:
    def __init__(self, fd, events):
        self.fd = fd
        self.path = f"/dev/input/event{fd}"
        self._events = list(events)
        self.grabbed = False
        self.closed = False
        self.grab_calls = 0
        self.ungrab_calls = 0
        self.close_calls = 0

    def read(self):
        events, self._events = self._events, []
        return events

    def grab(self):
        self.grabbed = True
        self.grab_calls += 1

    def ungrab(self):
        self.grabbed = False
        self.ungrab_calls += 1

    def close(self):
        self.closed = True
        self.close_calls += 1


class FailingDevice(FakeDevice):
    def read(self):
        raise OSError("gone")


def test_registers_readers_and_forwards_events():
    loop = FakeLoop()
    received = []
    device = FakeDevice(900001, [
        SimpleNamespace(type=1, code=30, value=1),
        SimpleNamespace(type=0, code=0, value=0),
    ])
    source = EvdevEventSource(loop, ["/dev/input/event900001"],
                              lambda *event: received.append(event),
                              open_device=lambda path: device)
    assert 900001 in loop.readers
    callback, args = loop.readers[900001]
    callback(*args)
    assert received == [(1, 30, 1), (0, 0, 0)]


def test_grab_and_release():
    loop = FakeLoop()
    device = FakeDevice(900002, [])
    source = EvdevEventSource(loop, ["/dev/input/event900002"], lambda *_: None,
                              open_device=lambda path: device)
    source.set_grab(True)
    assert device.grabbed is True
    assert device.grab_calls == 1
    source.set_grab(False)
    assert device.grabbed is False
    assert device.ungrab_calls == 1


def test_close_removes_reader_and_closes_device():
    loop = FakeLoop()
    device = FakeDevice(900003, [])
    source = EvdevEventSource(loop, ["/dev/input/event900003"], lambda *_: None,
                              open_device=lambda path: device)
    source.close()
    assert 900003 not in loop.readers
    assert device.closed is True


def test_unopenable_device_is_skipped():
    loop = FakeLoop()
    first = FakeDevice(900004, [])

    def open_device(path):
        if path == "/dev/input/event900004":
            return first
        raise OSError("gone")

    source = EvdevEventSource(loop, ["/dev/input/event900004", "/dev/input/event900005"],
                              lambda *_: None, open_device=open_device)
    assert 900004 in loop.readers
    assert len(source._devices) == 1
    assert next(iter(source._devices.values())) is first


def test_double_close_is_a_noop():
    loop = FakeLoop()
    device = FakeDevice(900006, [])
    source = EvdevEventSource(loop, ["/dev/input/event900006"], lambda *_: None,
                              open_device=lambda path: device)
    source.close()
    source.close()
    assert 900006 not in loop.readers
    assert device.closed is True
    assert device.close_calls == 1


def test_read_error_drops_device():
    loop = FakeLoop()
    device = FailingDevice(900007, [])
    EvdevEventSource(loop, ["/dev/input/event900007"], lambda *_: None,
                     open_device=lambda path: device)
    assert 900007 in loop.readers
    callback, args = loop.readers[900007]
    callback(*args)
    assert 900007 not in loop.readers
    assert device.closed is True


def test_release_when_not_grabbed_is_noop():
    loop = FakeLoop()
    device = FakeDevice(900008, [])
    source = EvdevEventSource(loop, ["/dev/input/event900008"], lambda *_: None,
                              open_device=lambda path: device)
    source.set_grab(False)
    assert device.ungrab_calls == 0
