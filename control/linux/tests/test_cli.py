import argparse

import pytest

from cokvm_linux.cli import build_parser, main, parse_resolution, positive_float


def test_parse_resolution():
    assert parse_resolution("1920x1080") == (1920, 1080)
    assert parse_resolution("2560X1440") == (2560, 1440)


@pytest.mark.parametrize("value", ["1920", "x1080", "0x1080", "1920x-1", "abc", "²x1080"])
def test_parse_resolution_rejects_bad_input(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_resolution(value)


def test_positive_float():
    assert positive_float("2") == 2.0
    for value in ("0", "abc"):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_float(value)


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


def test_main_run_builds_config(monkeypatch):
    seen = {}

    async def fake_run_app(config):
        seen["config"] = config
        return 0

    monkeypatch.setattr("cokvm_linux.cli.run_app", fake_run_app)
    assert main(["run", "--target-resolution", "800x600", "--sensitivity", "2", "--dry-run"]) == 0
    config = seen["config"]
    assert (config.target_width, config.target_height) == (800, 600)
    assert config.sensitivity == 2
    assert config.dry_run is True
