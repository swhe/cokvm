"""Controller state machine and application orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from evdev import ecodes

from . import keymap, mouse, vss
from .hotkey import CHORD_KEY_CODES, HotkeyDetector
from .sender import FrameSender

log = logging.getLogger(__name__)


@dataclass
class Config:
    device_name: str = "CoKVM-Dongle"
    target_width: int = 1920
    target_height: int = 1080
    sensitivity: float = 1.0
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    dry_run: bool = False
    no_grab: bool = False
    verbose: bool = False
    motion_interval: float = 0.008
    hotkey_cooldown: float = 0.15


class EventSource(Protocol):
    def set_grab(self, enabled: bool) -> None: ...
    def close(self) -> None: ...


class Transport(Protocol):
    authenticated: bool

    async def connect(self) -> None: ...
    async def send(self, frame: bytes) -> None: ...
    async def close(self) -> None: ...


class Controller:
    def __init__(self, config: Config, sender: FrameSender, transport: Transport,
                 source_factory: Callable[[list[str], Callable], EventSource],
                 now: Callable[[], float] = time.monotonic):
        self.config = config
        self.sender = sender
        self.transport = transport
        self._source_factory = source_factory
        self._now = now
        self.state = "MONITOR"
        self.hotkey = HotkeyDetector(config.hotkey_cooldown)
        self.mouse = mouse.MouseState(
            config.target_width, config.target_height, config.sensitivity)
        self.source: EventSource | None = None
        self._paths: list[str] = []
        self._generation = 0
        self._mods = 0
        self._mod_codes: set[int] = set()
        self._keys: list[int] = []
        self._pending_dx = 0
        self._pending_dy = 0
        self._pending_wheel = 0
        self._pending_buttons = False
        self._swallow_chord = False

    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    def open_source(self, paths: list[str]) -> None:
        self.close_source()
        self._paths = list(paths)
        self.hotkey.reset()
        self.source = self._source_factory(self._paths, self._dispatch)

    def close_source(self) -> None:
        if self.source is not None:
            self.source.set_grab(False)
            self.source.close()
            self.source = None
        self._paths = []

    def _dispatch(self, type_: int, code: int, value: int) -> None:
        result = self.handle_event(type_, code, value)
        if result is not None:
            asyncio.create_task(result)

    def handle_event(self, type_: int, code: int, value: int):
        if type_ == ecodes.EV_KEY:
            if code in CHORD_KEY_CODES:
                if self.hotkey.feed(code, value, self._now()):
                    if self.state == "MONITOR":
                        return self.enter_capture()
                    if self.state == "CAPTURING":
                        self._swallow_chord = True
                        return self.exit_capture("hotkey")
                if self._swallow_chord:
                    if not self.hotkey.chord_down:
                        self._swallow_chord = False
                    return None
            if self.state != "CAPTURING":
                return None
            if code in mouse.BUTTON_MAP:
                if value != 2:
                    self.mouse.set_button(code, value == 1)
                    self._pending_buttons = True
                return None
            self._handle_key(code, value)
            return None
        if self.state != "CAPTURING":
            return None
        if type_ == ecodes.EV_REL:
            if code == ecodes.REL_X:
                self._pending_dx += value
            elif code == ecodes.REL_Y:
                self._pending_dy += value
            elif code == ecodes.REL_WHEEL:
                self._pending_wheel += value
        elif type_ == ecodes.EV_SYN:
            if code == ecodes.SYN_REPORT:
                self._flush_mouse()
            elif code == ecodes.SYN_DROPPED:
                self._pending_dx = self._pending_dy = self._pending_wheel = 0
                self._pending_buttons = False
        return None

    def _handle_key(self, code: int, value: int) -> None:
        if value == 2:
            return
        modifier = keymap.modifier_bit(code)
        usage = keymap.key_to_usage(code)
        if modifier is not None:
            if value == 1:
                self._mod_codes.add(code)
            else:
                self._mod_codes.discard(code)
            self._mods = 0
            for held in self._mod_codes:
                bit = keymap.modifier_bit(held)
                if bit is not None:
                    self._mods |= bit
        elif usage is not None:
            if value == 1:
                if usage in self._keys:
                    return
                if len(self._keys) >= vss.MAX_KEYS:
                    log.warning("6KRO limit reached; dropping usage 0x%02X", usage)
                    return
                self._keys.append(usage)
            else:
                if usage not in self._keys:
                    return
                self._keys.remove(usage)
        else:
            return
        self.sender.submit_keyboard(vss.keyboard_frame(self._mods, self._keys))

    def _flush_mouse(self) -> None:
        moved = self._pending_dx != 0 or self._pending_dy != 0
        if moved:
            self.mouse.move(self._pending_dx, self._pending_dy)
            self._pending_dx = 0
            self._pending_dy = 0
            self.sender.submit_motion(self._mouse_frame())
        if self._pending_buttons:
            self._pending_buttons = False
            if not moved:
                self.sender.submit_discrete(self._mouse_frame())
        if self._pending_wheel:
            if abs(self._pending_wheel) > 1:
                log.warning("wheel delta %d clamped to one frame", self._pending_wheel)
            wheel = self.mouse.wheel(self._pending_wheel)
            self._pending_wheel = 0
            self.sender.submit_discrete(self._mouse_frame(wheel=wheel))

    def _mouse_frame(self, wheel: int = 0) -> bytes:
        x, y = self.mouse.pos
        return vss.mouse_frame(self.mouse.buttons, x, y, wheel)

    async def enter_capture(self) -> None:
        if self.state != "MONITOR" or not self.transport.authenticated:
            return
        self._generation += 1
        gen = self._generation
        self.state = "CAPTURING"
        self._set_grab(True)
        self._mods = 0
        self._mod_codes.clear()
        self._keys.clear()
        self._pending_dx = 0
        self._pending_dy = 0
        self._pending_wheel = 0
        self._pending_buttons = False
        self._swallow_chord = False
        self.mouse.reset_center()
        self.sender.submit_keyboard(vss.keyboard_frame(0, []))
        self.sender.submit_discrete(self._mouse_frame())
        await self.sender.drain(0.2)
        if gen != self._generation:
            return
        log.info("MONITOR -> CAPTURING")

    async def exit_capture(self, reason: str) -> None:
        if self.state != "CAPTURING":
            return
        self._generation += 1
        gen = self._generation
        self.state = "RELEASING"
        self.mouse.buttons = 0
        self.sender.submit_keyboard(vss.keyboard_frame(0, []))
        self.sender.submit_discrete(self._mouse_frame())
        await self.sender.drain(0.2)
        if gen != self._generation:
            return
        self._set_grab(False)
        self._mods = 0
        self._mod_codes.clear()
        self._keys.clear()
        self.state = "MONITOR"
        log.info("CAPTURING -> MONITOR (%s)", reason)

    async def graceful_release(self, reason: str) -> None:
        if self.state == "CAPTURING" and self.transport.authenticated:
            self._mods = 0
            self._mod_codes.clear()
            self._keys.clear()
            self.mouse.buttons = 0
            self.sender.submit_keyboard(vss.keyboard_frame(0, []))
            self.sender.submit_discrete(self._mouse_frame())
            await self.sender.drain(0.2)
        self.force_release(reason)

    def force_release(self, reason: str) -> None:
        self._generation += 1
        self._set_grab(False)
        self.sender.clear()
        self.hotkey.reset()
        self._mods = 0
        self._mod_codes.clear()
        self._keys.clear()
        self._pending_dx = 0
        self._pending_dy = 0
        self._pending_wheel = 0
        self._pending_buttons = False
        self._swallow_chord = False
        if self.state != "MONITOR":
            log.info("%s -> MONITOR (%s)", self.state, reason)
        self.state = "MONITOR"

    def _set_grab(self, enabled: bool) -> None:
        if self.config.no_grab or self.source is None:
            return
        self.source.set_grab(enabled)

    def close(self) -> None:
        self.force_release("shutdown")
        self.close_source()
