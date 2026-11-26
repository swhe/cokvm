"""Controller state machine and application orchestration."""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from evdev import ecodes

from . import devices, keymap, mouse, vss
from .agent import read_passkey_from_tty, register_agent
from .ble import BleTransport, backoff_delays
from .hotkey import CHORD_KEY_CODES, HotkeyDetector
from .input_source import EvdevEventSource
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
        new_paths = list(paths)
        source = self._source_factory(new_paths, self._dispatch)
        self._paths = new_paths
        self.hotkey.reset()
        self.source = source

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
        log.debug("event type=%d code=%d value=%d", type_, code, value)
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

    def send_neutral(self) -> None:
        self._mods = 0
        self._mod_codes.clear()
        self._keys.clear()
        self.mouse.buttons = 0
        self.sender.submit_keyboard(vss.keyboard_frame(0, []))
        self.sender.submit_discrete(self._mouse_frame())

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
        self.sender.clear()
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
            self.sender.clear()
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


class DryRunTransport:
    authenticated = True

    async def connect(self) -> None:
        return None

    async def send(self, frame: bytes) -> None:
        print(f"frame {frame.hex(' ')}", file=sys.stderr)

    async def close(self) -> None:
        return None


async def _sleep_or_stop(seconds: float, stop: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _wait_or_stop(event: asyncio.Event, stop: asyncio.Event) -> bool:
    while not stop.is_set():
        try:
            await asyncio.wait_for(event.wait(), timeout=0.5)
            return True
        except asyncio.TimeoutError:
            continue
    return False


async def _connection_loop(controller: Controller, transport, disconnected: asyncio.Event,
                           stop: asyncio.Event) -> None:
    delays = backoff_delays()
    while not stop.is_set():
        if not transport.authenticated:
            try:
                await transport.connect()
                controller.send_neutral()
                await controller.sender.drain(0.2)
                log.info("BLE connected and authenticated")
            except Exception as exc:
                log.warning("BLE connect failed: %s", exc)
                await _sleep_or_stop(next(delays), stop)
                continue
            delays = backoff_delays()
        disconnected.clear()
        if not transport.authenticated:
            log.warning("BLE disconnected; releasing local input")
            controller.force_release("ble disconnect")
            await _sleep_or_stop(next(delays), stop)
            continue
        await _wait_or_stop(disconnected, stop)
        if stop.is_set():
            return
        log.warning("BLE disconnected; releasing local input")
        controller.force_release("ble disconnect")
        await _sleep_or_stop(next(delays), stop)


async def _hotplug_loop(controller: Controller, config: Config, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await _sleep_or_stop(2.0, stop)
        if stop.is_set():
            continue
        try:
            # Enumerating evdev devices opens and closes every /dev/input/event*,
            # which can block for hundreds of milliseconds (USB/i2c close paths).
            # Keep it off the loop so input forwarding never stalls behind a scan.
            infos = await asyncio.to_thread(
                lambda: devices.select(
                    devices.enumerate_devices(), config.include, config.exclude))
            paths = [info.path for info in infos]
            if (controller.state == "MONITOR"
                    and set(paths) != set(controller.paths)):
                controller.open_source(paths)
                log.info("input devices changed: %d device(s)", len(paths))
        except Exception as exc:
            log.warning("device refresh failed: %s", exc)
            continue
        if controller.state != "MONITOR":
            if not set(controller.paths).issubset(set(paths)):
                log.warning("input device removed while capturing; releasing")
                await controller.graceful_release("device removed")


async def run_app(config: Config) -> int:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    disconnected = asyncio.Event()
    if config.dry_run:
        transport = DryRunTransport()
    else:
        transport = BleTransport(config.device_name, on_disconnect=disconnected.set)

    sender = FrameSender(transport, config.motion_interval)
    source_factory = lambda paths, callback: EvdevEventSource(loop, paths, callback)
    controller = Controller(config, sender, transport, source_factory)
    release_on_exit = controller.force_release
    atexit.register(release_on_exit, "atexit")

    try:
        infos = devices.select(devices.enumerate_devices(), config.include, config.exclude)
        controller.open_source([info.path for info in infos])
    except Exception as exc:
        log.error("cannot open input devices: %s", exc)
        atexit.unregister(release_on_exit)
        await transport.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        return 1
    if not infos:
        log.warning("no readable input devices; is your user in the 'input' group?")
    log.info("input devices: %d", len(infos))
    sender.start()

    hotplug_task = asyncio.create_task(_hotplug_loop(controller, config, stop))
    connection_task = None
    if not config.dry_run:
        try:
            await asyncio.wait_for(register_agent(read_passkey_from_tty), timeout=10.0)
            log.info("pairing agent registered")
        except Exception as exc:
            log.warning("pairing agent unavailable: %s", exc)
        connection_task = asyncio.create_task(
            _connection_loop(controller, transport, disconnected, stop))

    try:
        await stop.wait()
    finally:
        atexit.unregister(release_on_exit)
        await controller.graceful_release("shutdown")
        await sender.stop()
        controller.close_source()
        hotplug_task.cancel()
        if connection_task is not None:
            connection_task.cancel()
        tasks = [hotplug_task] + ([connection_task] if connection_task else [])
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.warning("background task ended with an error", exc_info=True)
        await transport.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0
