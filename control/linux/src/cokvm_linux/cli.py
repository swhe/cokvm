"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from evdev import ecodes

from . import devices
from .app import Config, run_app


def parse_resolution(text: str) -> tuple[int, int]:
    width, separator, height = text.lower().partition("x")
    if (not separator
            or not width.isascii() or not width.isdigit()
            or not height.isascii() or not height.isdigit()):
        raise argparse.ArgumentTypeError("分辨率格式应为 WxH，例如 1920x1080")
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("分辨率必须为正数")
    return w, h


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是数字") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("必须为正数")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cokvm-linux")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="forward local keyboard/mouse over BLE")
    run.add_argument("--target-resolution", type=parse_resolution,
                     default=(1920, 1080), metavar="WxH",
                     help="target screen resolution for mouse mapping, e.g. 1920x1080")
    run.add_argument("--sensitivity", type=positive_float, default=1.0,
                     help="mouse sensitivity multiplier")
    run.add_argument("--include", action="append", default=[], metavar="PATTERN",
                     help="only include devices matching this fnmatch pattern "
                          "(name, event path, or full by-id path)")
    run.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                     help="exclude devices matching this pattern")
    run.add_argument("--device-name", default="CoKVM-Dongle",
                     help="BLE device name")
    run.add_argument("--dry-run", action="store_true",
                     help="print frames instead of sending")
    run.add_argument("--no-grab", action="store_true",
                     help="read input without grabbing it")
    run.add_argument("--verbose", action="store_true",
                     help="debug logging")

    subparsers.add_parser("list-devices", help="list candidate input devices")

    scan = subparsers.add_parser("scan", help="scan BLE devices")
    scan.add_argument("--timeout", type=positive_float, default=10.0,
                      help="scan timeout in seconds")
    return parser


def print_devices() -> int:
    count = 0
    for info in devices.enumerate_devices():
        role = devices.classify(info) or "ignored"
        if role == "touchpad":
            role = "touchpad (unsupported)"
        caps = []
        if ecodes.KEY_A in info.key_caps:
            caps.append("kbd")
        if ecodes.REL_X in info.rel_caps and ecodes.REL_Y in info.rel_caps:
            caps.append("rel")
        if ecodes.ABS_MT_POSITION_X in info.abs_caps:
            caps.append("mt")
        elif info.abs_caps:
            caps.append("abs")
        print(f"{info.path}\t{info.bustype:#04x}\t{role}\t{','.join(caps) or '-'}\t{info.name}")
        count += 1
    return count


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
        count = print_devices()
        if count == 0:
            print("no readable input devices; is your user in the 'input' group?",
                  file=sys.stderr)
        return 0
    if args.command == "scan":
        try:
            asyncio.run(scan_ble(args.timeout))
        except Exception as exc:
            print(f"BLE scan failed: {exc}", file=sys.stderr)
            return 1
        return 0
    parser.error("unknown command")
    return 2
