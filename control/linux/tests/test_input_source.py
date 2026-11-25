from types import SimpleNamespace

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

    def read(self):
        events, self._events = self._events, []
        return events

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.grabbed = False

    def close(self):
        self.closed = True


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
    source.set_grab(False)
    assert device.grabbed is False


def test_close_removes_reader_and_closes_device():
    loop = FakeLoop()
    device = FakeDevice(900003, [])
    source = EvdevEventSource(loop, ["/dev/input/event900003"], lambda *_: None,
                              open_device=lambda path: device)
    source.close()
    assert 900003 not in loop.readers
    assert device.closed is True
