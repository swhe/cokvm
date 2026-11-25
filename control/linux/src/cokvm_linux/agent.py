"""BlueZ Agent1 implementation for passkey pairing."""

from __future__ import annotations

from dbus_fast import DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType
from dbus_fast.service import ServiceInterface, method

AGENT_PATH = "/org/bluez/cokvm_agent"
AGENT_CAPABILITY = "KeyboardOnly"


def _method(*args, **kwargs):
    """Register a method like ``dbus_fast.service.method`` but keep return values.

    dbus-fast 5.2.0's ``@method`` wrapper calls the decorated function yet drops
    its return value, so a direct call such as ``agent.RequestPasskey(device)``
    always yields ``None``. D-Bus dispatch uses the original callable stored on
    ``_Method.fn``, so exposing that callable on the class keeps both paths
    working and makes the method bodies directly callable (and testable).
    """
    register = method(*args, **kwargs)

    def decorator(fn):
        fn.__dict__["__DBUS_METHOD"] = register(fn).__dict__["__DBUS_METHOD"]
        return fn

    return decorator


class AgentError(Exception):
    pass


def parse_passkey(text: str) -> int:
    value = text.strip()
    if len(value) != 6 or not value.isascii() or not value.isdigit():
        raise AgentError("配对码必须是 6 位数字")
    return int(value)


def read_passkey(stream_in, stream_out, prompt: str = "配对码: ") -> int:
    stream_out.write(prompt)
    stream_out.flush()
    line = stream_in.readline()
    if not line:
        raise AgentError("没有读到配对码")
    return parse_passkey(line)


def read_passkey_from_tty(prompt: str = "配对码: ", tty_path: str = "/dev/tty") -> int:
    try:
        tty = open(tty_path, "r+", encoding="utf-8")
    except OSError as exc:
        raise AgentError("没有可用的终端（/dev/tty），请先用 bluetoothctl 配对") from exc
    with tty:
        return read_passkey(tty, tty, prompt)


class PairingAgent(ServiceInterface):
    def __init__(self, passkey_provider):
        super().__init__("org.bluez.Agent1")
        self._passkey_provider = passkey_provider

    def _passkey(self) -> int:
        try:
            value = int(self._passkey_provider())
        except Exception as exc:
            raise DBusError("org.bluez.Error.Rejected", str(exc)) from exc
        if not 0 <= value <= 999999:
            raise DBusError("org.bluez.Error.Rejected", "invalid passkey")
        return value

    @_method()
    def Release(self):
        return None

    @_method()
    def RequestPinCode(self, device: "o") -> "s":
        raise DBusError("org.bluez.Error.Rejected", "PIN code not supported")

    @_method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        return None

    @_method()
    def RequestPasskey(self, device: "o") -> "u":
        return self._passkey()

    @_method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        return None

    @_method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        return None

    @_method()
    def RequestAuthorization(self, device: "o"):
        return None

    @_method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        return None

    @_method()
    def Cancel(self):
        return None


async def register_agent(passkey_provider, bus=None):
    owned = bus is None
    if owned:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    agent = PairingAgent(passkey_provider)
    try:
        bus.export(AGENT_PATH, agent)
        introspection = await bus.introspect("org.bluez", "/org/bluez")
        proxy = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
        interface = proxy.get_interface("org.bluez.AgentManager1")
        await interface.call_register_agent(AGENT_PATH, AGENT_CAPABILITY)
        await interface.call_request_default_agent(AGENT_PATH)
    except BaseException:
        if owned:
            try:
                bus.unexport(AGENT_PATH)
            except Exception:
                pass
            try:
                await bus.disconnect()
            except Exception:
                pass
        raise
    return bus, agent
