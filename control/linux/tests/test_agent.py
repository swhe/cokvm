import io

import pytest
from dbus_fast import DBusError

from cokvm_linux.agent import AgentError, PairingAgent, parse_passkey, read_passkey


def test_parse_passkey_accepts_six_digits():
    assert parse_passkey("123456\n") == 123456


@pytest.mark.parametrize("value", ["12345", "1234567", "abcdef", "", "12 456"])
def test_parse_passkey_rejects_bad_input(value):
    with pytest.raises(AgentError):
        parse_passkey(value)


def test_read_passkey_prompts_and_reads():
    out = io.StringIO()
    assert read_passkey(io.StringIO("654321\n"), out) == 654321
    assert out.getvalue() == "配对码: "


def test_agent_returns_provider_value():
    agent = PairingAgent(lambda: 112233)
    assert agent.RequestPasskey("/org/bluez/hci0/dev") == 112233


def test_agent_rejects_provider_failure():
    agent = PairingAgent(lambda: (_ for _ in ()).throw(AgentError("no tty")))
    with pytest.raises(DBusError):
        agent.RequestPasskey("/org/bluez/hci0/dev")
