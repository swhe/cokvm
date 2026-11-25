"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging

from . import devices
from .app import Config, run_app


def parse_resolution(text: str) -> tuple[int, int]:
    width, separator, height = text.lower().partition("x")
    if not separator or not width.isdigit() or not height.isdigit():
        raise argparse.ArgumentTypeError("分辨率格式应为 WxH，例如 1920x1080")
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("分辨率必须为正数")
    return w, h


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cokvm-linux")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="forward local keyboard/mouse over BLE")
    run.add_argument("--target-resolution", type=parse_resolution,
                     default=(1920, 1080), metavar="WxH")
    run.add_argument("--sensitivity", type=float, default=1.0)
    run.add_argument("--include", action="append", default=[], metavar="PATTERN")
    run.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    run.add_argument("--device-name", default="CoKVM-Dongle")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-grab", action="store_true")
    run.add_argument("--verbose", action="store_true")

    subparsers.add_parser("list-devices", help="list candidate input devices")

    scan = subparsers.add_parser("scan", help="scan BLE devices")
    scan.add_argument("--timeout", type=float, default=10.0)
    return parser


def print_devices() -> None:
    for info in devices.enumerate_devices():
        role = devices.classify(info) or "ignored"
        if role == "touchpad":
            role = "touchpad (unsupported)"
        print(f"{info.path}\t{role}\t{info.name}")


async def scan_ble(timeout: float) -> None:
    from bleak import BleakScanner

    for device in await BleakScanner.discover(timeout=timeout):
        print(f"{device.address}\t{device.name or ''}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        width, height = args.target_resolution
        config = Config(
            device_name=args.device_name,
            target_width=width,
            target_height=height,
            sensitivity=args.sensitivity,
            include=tuple(args.include),
            exclude=tuple(args.exclude),
            dry_run=args.dry_run,
            no_grab=args.no_grab,
            verbose=args.verbose,
        )
        return asyncio.run(run_app(config))
    if args.command == "list-devices":
        print_devices()
        return 0
    if args.command == "scan":
        asyncio.run(scan_ble(args.timeout))
        return 0
    parser.error("unknown command")
    return 2
