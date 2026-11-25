"""Encode CoKVM VSS frames (see docs/protocols.cn.md)."""

from __future__ import annotations

import struct
from collections.abc import Sequence

MAGIC_K = 0x4B
MAGIC_M = 0x4D
VERSION = 0x00
FRAME_SIZE = 22

TYPE_KEYBOARD = 0x01
TYPE_MOUSE = 0x02
TYPE_LED = 0x03

MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08

GRID_MAX = 17280
MAX_USAGE = 0x65
MAX_KEYS = 6
WHEEL_NOTCH = 120
WHEEL_MAX = 127


def _frame(frame_type: int, data: bytes) -> bytes:
    if len(data) > 8:
        raise ValueError("payload must be at most 8 bytes")
    return struct.pack("<BBBB8s10x", MAGIC_K, MAGIC_M, VERSION, frame_type, data)


def keyboard_frame(modifiers: int, keycodes: Sequence[int]) -> bytes:
    if not 0 <= modifiers <= 0x0F:
        raise ValueError("modifiers out of range")
    if len(keycodes) > MAX_KEYS:
        raise ValueError("at most 6 keycodes")
    slots = list(keycodes) + [0] * (MAX_KEYS - len(keycodes))
    if any(not 0 <= code <= MAX_USAGE for code in slots):
        raise ValueError("keycode out of range")
    return _frame(TYPE_KEYBOARD, bytes([modifiers, 0, *slots]))


def mouse_frame(buttons: int, x: int, y: int, wheel: int = 0) -> bytes:
    if not 0 <= buttons <= 0x1F:
        raise ValueError("buttons out of range")
    if not 0 <= x <= GRID_MAX or not 0 <= y <= GRID_MAX:
        raise ValueError("coordinates out of range")
    if not -WHEEL_MAX <= wheel <= WHEEL_MAX:
        raise ValueError("wheel out of range")
    return _frame(TYPE_MOUSE, struct.pack("<Bhhb2x", buttons, x, y, wheel))


def led_frame(*, num_lock: bool = False, caps_lock: bool = False) -> bytes:
    status = (0x01 if num_lock else 0) | (0x02 if caps_lock else 0)
    return _frame(TYPE_LED, bytes([status]))
