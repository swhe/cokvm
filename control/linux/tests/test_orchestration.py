from cokvm_linux.app import DryRunTransport


async def test_dry_run_transport_is_authenticated(capsys):
    transport = DryRunTransport()
    assert transport.authenticated is True
    await transport.send(b"\x00" * 22)
    captured = capsys.readouterr()
    assert "frame" in captured.err
