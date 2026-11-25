import argparse

import pytest

from cokvm_linux.cli import build_parser, parse_resolution


def test_parse_resolution():
    assert parse_resolution("1920x1080") == (1920, 1080)
    assert parse_resolution("2560X1440") == (2560, 1440)


@pytest.mark.parametrize("value", ["1920", "x1080", "0x1080", "1920x-1", "abc"])
def test_parse_resolution_rejects_bad_input(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_resolution(value)


def test_run_defaults():
    args = build_parser().parse_args(["run"])
    assert args.command == "run"
    assert args.target_resolution == (1920, 1080)
    assert args.sensitivity == 1.0
    assert args.include == []
    assert args.exclude == []
    assert args.device_name == "CoKVM-Dongle"
    assert args.dry_run is False
    assert args.no_grab is False
