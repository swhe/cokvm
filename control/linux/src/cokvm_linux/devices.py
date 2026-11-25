"""Enumerate and filter evdev input devices."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import evdev
from evdev import ecodes


@dataclass(frozen=True)
class DeviceInfo:
    path: str
    name: str
    bustype: int
    key_caps: frozenset[int]
    rel_caps: frozenset[int]
    abs_caps: frozenset[int]
    sw_caps: frozenset[int]


def classify(info: DeviceInfo) -> str | None:
    if info.bustype == ecodes.BUS_VIRTUAL:
        return None
    if (ecodes.ABS_MT_POSITION_X in info.abs_caps
            or ecodes.ABS_MT_POSITION_Y in info.abs_caps):
        return "touchpad"
    if ecodes.KEY_A in info.key_caps:
        return "keyboard"
    if ecodes.REL_X in info.rel_caps and ecodes.REL_Y in info.rel_caps:
        return "mouse"
    if (ecodes.ABS_X in info.abs_caps and ecodes.ABS_Y in info.abs_caps
            and ecodes.BTN_LEFT in info.key_caps):
        return "mouse"
    return None


def _matches_any(patterns: tuple[str, ...], values: tuple[str, str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern)
               for pattern in patterns for value in values)


def select(infos: list[DeviceInfo], include: tuple[str, ...] = (),
           exclude: tuple[str, ...] = ()) -> list[DeviceInfo]:
    selected = []
    for info in infos:
        if classify(info) not in ("keyboard", "mouse"):
            continue
        values = (info.name, info.path)
        if include and not _matches_any(include, values):
            continue
        if exclude and _matches_any(exclude, values):
            continue
        selected.append(info)
    return selected


def enumerate_devices() -> list[DeviceInfo]:
    infos: list[DeviceInfo] = []
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError:
            continue
        try:
            caps = device.capabilities(absinfo=False)
            infos.append(DeviceInfo(
                path=path,
                name=device.name,
                bustype=device.info.bustype,
                key_caps=frozenset(caps.get(ecodes.EV_KEY, ())),
                rel_caps=frozenset(caps.get(ecodes.EV_REL, ())),
                abs_caps=frozenset(caps.get(ecodes.EV_ABS, ())),
                sw_caps=frozenset(caps.get(ecodes.EV_SW, ())),
            ))
        finally:
            device.close()
    return infos
