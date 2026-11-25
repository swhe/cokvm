"""Absolute mouse state mapped onto the protocol's 17280 x 17280 grid."""

from __future__ import annotations

from evdev import ecodes

from . import vss

BUTTON_MAP = {
    ecodes.BTN_LEFT: 0x01,
    ecodes.BTN_RIGHT: 0x02,
    ecodes.BTN_MIDDLE: 0x04,
    ecodes.BTN_SIDE: 0x08,
    ecodes.BTN_EXTRA: 0x10,
}


class MouseState:
    def __init__(self, target_width: int = 1920, target_height: int = 1080,
                 sensitivity: float = 1.0):
        if target_width <= 0 or target_height <= 0:
            raise ValueError("target resolution must be positive")
        if sensitivity <= 0:
            raise ValueError("sensitivity must be positive")
        self._scale_x = vss.GRID_MAX / target_width * sensitivity
        self._scale_y = vss.GRID_MAX / target_height * sensitivity
        self.x = 0.0
        self.y = 0.0
        self.buttons = 0
        self.reset_center()

    def reset_center(self) -> None:
        self.x = vss.GRID_MAX / 2
        self.y = vss.GRID_MAX / 2
        self.buttons = 0

    @property
    def pos(self) -> tuple[int, int]:
        return int(round(self.x)), int(round(self.y))

    def move(self, dx: int, dy: int) -> tuple[int, int]:
        self.x = min(vss.GRID_MAX, max(0.0, self.x + dx * self._scale_x))
        self.y = min(vss.GRID_MAX, max(0.0, self.y + dy * self._scale_y))
        return self.pos

    def set_button(self, code: int, pressed: bool) -> bool:
        bit = BUTTON_MAP.get(code)
        if bit is None:
            return False
        if pressed:
            self.buttons |= bit
        else:
            self.buttons &= ~bit
        return True

    def wheel(self, notches: int) -> int:
        return max(-vss.WHEEL_MAX, min(vss.WHEEL_MAX, int(notches) * vss.WHEEL_NOTCH))
