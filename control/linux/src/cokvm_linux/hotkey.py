"""Detect the Ctrl+Alt+Esc switch chord from evdev events."""

from __future__ import annotations

from evdev import ecodes

_CTRL = frozenset({ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL})
_ALT = frozenset({ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT})
_ESC = frozenset({ecodes.KEY_ESC})

CHORD_KEY_CODES = frozenset(_CTRL | _ALT | _ESC)


class HotkeyDetector:
    def __init__(self, cooldown: float = 0.15):
        self._cooldown = cooldown
        self._down: set[int] = set()
        self._armed = True
        self._cooldown_until = 0.0

    @property
    def chord_down(self) -> bool:
        return bool(self._down & _CTRL and self._down & _ALT and _ESC & self._down)

    def reset(self) -> None:
        self._down.clear()
        self._armed = True
        self._cooldown_until = 0.0

    def feed(self, code: int, value: int, now: float) -> bool:
        if code not in CHORD_KEY_CODES or value == 2:
            return False
        if value == 1:
            self._down.add(code)
            if self._armed and now >= self._cooldown_until and self.chord_down:
                self._armed = False
                self._cooldown_until = now + self._cooldown
                return True
            return False
        if value == 0:
            self._down.discard(code)
            if code == ecodes.KEY_ESC:
                self._armed = True
        return False
