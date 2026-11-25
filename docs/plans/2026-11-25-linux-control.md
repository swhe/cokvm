# CoKVM Linux 控制端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `control/linux/` 新增纯键鼠的 Linux 控制端，通过 BLE VSS 转发键盘/鼠标，用 `Ctrl+Alt+Esc` 双向切换，断线立即释放本机输入。

**Architecture:** 单进程 asyncio。evdev 设备 fd 用 `loop.add_reader()` 读取事件；`Controller` 维护 `MONITOR`/`CAPTURING` 状态并生成 22 字节 VSS 帧；`FrameSender` 按键盘优先、运动合并、离散事件不丢的规则发送；`BleTransport` 负责扫描/配对/认证/写入/断线回调。

**Tech Stack:** Python 3.10+，`bleak`、`python-evdev`、`dbus-fast`，pytest + pytest-asyncio。

参考规格：`docs/specs/2026-11-25-linux-control-design.md`；协议：`docs/protocols.cn.md`。

所有命令默认在仓库根目录 `/home/wz/source/cokvm` 执行；测试命令使用 `control/linux/.venv/bin/` 下的解释器。

---

### Task 1: 项目脚手架

**Files:**
- Create: `control/linux/pyproject.toml`
- Create: `control/linux/.gitignore`
- Create: `control/linux/src/cokvm_linux/__init__.py`
- Create: `control/linux/README.md`
- Create: `control/linux/tests/test_package.py`
- Copy: `control/macos/LICENSE` → `control/linux/LICENSE`

- [ ] **Step 1: 创建目录与 LICENSE**

```bash
mkdir -p control/linux/src/cokvm_linux control/linux/tests
cp control/macos/LICENSE control/linux/LICENSE
```

Expected: 命令无输出，`control/linux/LICENSE` 存在。

- [ ] **Step 2: 写 `pyproject.toml`**

`control/linux/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "cokvm-linux"
version = "0.1.0"
description = "Linux control client for CoKVM (BLE keyboard/mouse forwarding)"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "GPL-2.0-only" }
dependencies = [
    "bleak>=0.22",
    "evdev>=1.6",
    "dbus-fast>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
]

[project.scripts]
cokvm-linux = "cokvm_linux.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: 写 `.gitignore` 与包入口**

`control/linux/.gitignore`:

```text
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

`control/linux/src/cokvm_linux/__init__.py`:

```python
"""Linux control client for CoKVM."""

__version__ = "0.1.0"
```

- [ ] **Step 4: 写 README 占位与首个测试**

`control/linux/README.md`:

```markdown
# CoKVM Linux client

Pure keyboard/mouse control client for CoKVM. See the repository README and
`docs/specs/2026-11-25-linux-control-design.md`.
```

`control/linux/tests/test_package.py`:

```python
def test_package_imports():
    import cokvm_linux

    assert cokvm_linux.__version__ == "0.1.0"
```

- [ ] **Step 5: 建虚拟环境并安装**

```bash
cd control/linux
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pytest pytest-asyncio
```

Expected: 安装成功；如果 `evdev` 编译失败，先 `sudo apt install python3-dev build-essential linux-headers-$(uname -r)` 再重试。

- [ ] **Step 6: 运行测试**

```bash
cd control/linux
.venv/bin/pytest -q
```

Expected: `1 passed`。

- [ ] **Step 7: 提交**

```bash
git add control/linux
git commit -m "feat(linux): scaffold control client"
```

---

### Task 2: VSS 帧编码

**Files:**
- Create: `control/linux/src/cokvm_linux/vss.py`
- Create: `control/linux/tests/test_vss.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_vss.py`:

```python
import struct

import pytest

from cokvm_linux import vss


def test_keyboard_shift_a_matches_protocol_example():
    frame = vss.keyboard_frame(vss.MOD_LSHIFT, [0x04])
    expected = bytes.fromhex("4B4D0001" "0200040000000000") + b"\x00" * 10
    assert frame == expected
    assert len(frame) == vss.FRAME_SIZE


def test_keyboard_pads_empty_slots():
    frame = vss.keyboard_frame(0, [])
    assert frame[4:12] == b"\x00" * 8


def test_keyboard_rejects_more_than_six_keys():
    with pytest.raises(ValueError):
        vss.keyboard_frame(0, [0x04] * 7)


def test_keyboard_rejects_usage_above_protocol_range():
    with pytest.raises(ValueError):
        vss.keyboard_frame(0, [0x66])


def test_mouse_frame_layout():
    frame = vss.mouse_frame(0x01, 100, 200, -120)
    expected = (
        bytes.fromhex("4B4D0002")
        + struct.pack("<Bhhb2x", 0x01, 100, 200, -120)
        + b"\x00" * 10
    )
    assert frame == expected
    assert len(frame) == vss.FRAME_SIZE


def test_mouse_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        vss.mouse_frame(0, -1, 0)
    with pytest.raises(ValueError):
        vss.mouse_frame(0, 0, 17281)
    with pytest.raises(ValueError):
        vss.mouse_frame(0, 0, 0, 128)


def test_led_frame():
    frame = vss.led_frame(caps_lock=True)
    assert frame == bytes.fromhex("4B4D0003") + b"\x02" + b"\x00" * 17
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_vss.py -q
```

Expected: FAIL，`ModuleNotFoundError` 或 `ImportError: cannot import name 'vss'`。

- [ ] **Step 3: 实现 `vss.py`**

`control/linux/src/cokvm_linux/vss.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_vss.py -q
```

Expected: `7 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/vss.py control/linux/tests/test_vss.py
git commit -m "feat(linux): add VSS frame encoder"
```

---

### Task 3: evdev 键码到 HID usage 映射

**Files:**
- Create: `control/linux/src/cokvm_linux/keymap.py`
- Create: `control/linux/tests/test_keymap.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_keymap.py`:

```python
from evdev import ecodes

from cokvm_linux import keymap


def test_letter_mapping_is_not_a_fixed_offset():
    assert keymap.key_to_usage(ecodes.KEY_A) == 0x04
    assert keymap.key_to_usage(ecodes.KEY_B) == 0x05
    assert keymap.key_to_usage(ecodes.KEY_E) == 0x08
    assert keymap.key_to_usage(ecodes.KEY_Z) == 0x1D


def test_digits_and_punctuation():
    assert keymap.key_to_usage(ecodes.KEY_1) == 0x1E
    assert keymap.key_to_usage(ecodes.KEY_0) == 0x27
    assert keymap.key_to_usage(ecodes.KEY_ESC) == 0x29
    assert keymap.key_to_usage(ecodes.KEY_SLASH) == 0x38


def test_navigation_and_function_keys():
    assert keymap.key_to_usage(ecodes.KEY_F1) == 0x3A
    assert keymap.key_to_usage(ecodes.KEY_F12) == 0x45
    assert keymap.key_to_usage(ecodes.KEY_SCROLLLOCK) == 0x47
    assert keymap.key_to_usage(ecodes.KEY_UP) == 0x52
    assert keymap.key_to_usage(ecodes.KEY_KP0) == 0x62
    assert keymap.key_to_usage(ecodes.KEY_COMPOSE) == 0x65


def test_unsupported_keys_return_none():
    assert keymap.key_to_usage(ecodes.KEY_MUTE) is None
    assert keymap.key_to_usage(ecodes.KEY_PLAYPAUSE) is None


def test_modifiers_map_both_sides_to_same_bit():
    assert keymap.modifier_bit(ecodes.KEY_LEFTCTRL) == 0x01
    assert keymap.modifier_bit(ecodes.KEY_RIGHTCTRL) == 0x01
    assert keymap.modifier_bit(ecodes.KEY_LEFTSHIFT) == 0x02
    assert keymap.modifier_bit(ecodes.KEY_RIGHTALT) == 0x04
    assert keymap.modifier_bit(ecodes.KEY_RIGHTMETA) == 0x08
    assert keymap.modifier_bit(ecodes.KEY_CAPSLOCK) is None


def test_capslock_is_a_normal_usage():
    assert keymap.key_to_usage(ecodes.KEY_CAPSLOCK) == 0x39
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_keymap.py -q
```

Expected: FAIL，`ImportError: cannot import name 'keymap'`。

- [ ] **Step 3: 实现 `keymap.py`**

`control/linux/src/cokvm_linux/keymap.py`:

```python
"""Map Linux evdev key codes to USB HID usages supported by the protocol."""

from __future__ import annotations

from evdev import ecodes

MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08

MODIFIER_BITS = {
    ecodes.KEY_LEFTCTRL: MOD_LCTRL,
    ecodes.KEY_RIGHTCTRL: MOD_LCTRL,
    ecodes.KEY_LEFTSHIFT: MOD_LSHIFT,
    ecodes.KEY_RIGHTSHIFT: MOD_LSHIFT,
    ecodes.KEY_LEFTALT: MOD_LALT,
    ecodes.KEY_RIGHTALT: MOD_LALT,
    ecodes.KEY_LEFTMETA: MOD_LGUI,
    ecodes.KEY_RIGHTMETA: MOD_LGUI,
}

KEY_TO_USAGE = {
    # letters
    ecodes.KEY_A: 0x04,
    ecodes.KEY_B: 0x05,
    ecodes.KEY_C: 0x06,
    ecodes.KEY_D: 0x07,
    ecodes.KEY_E: 0x08,
    ecodes.KEY_F: 0x09,
    ecodes.KEY_G: 0x0A,
    ecodes.KEY_H: 0x0B,
    ecodes.KEY_I: 0x0C,
    ecodes.KEY_J: 0x0D,
    ecodes.KEY_K: 0x0E,
    ecodes.KEY_L: 0x0F,
    ecodes.KEY_M: 0x10,
    ecodes.KEY_N: 0x11,
    ecodes.KEY_O: 0x12,
    ecodes.KEY_P: 0x13,
    ecodes.KEY_Q: 0x14,
    ecodes.KEY_R: 0x15,
    ecodes.KEY_S: 0x16,
    ecodes.KEY_T: 0x17,
    ecodes.KEY_U: 0x18,
    ecodes.KEY_V: 0x19,
    ecodes.KEY_W: 0x1A,
    ecodes.KEY_X: 0x1B,
    ecodes.KEY_Y: 0x1C,
    ecodes.KEY_Z: 0x1D,
    # digits
    ecodes.KEY_1: 0x1E,
    ecodes.KEY_2: 0x1F,
    ecodes.KEY_3: 0x20,
    ecodes.KEY_4: 0x21,
    ecodes.KEY_5: 0x22,
    ecodes.KEY_6: 0x23,
    ecodes.KEY_7: 0x24,
    ecodes.KEY_8: 0x25,
    ecodes.KEY_9: 0x26,
    ecodes.KEY_0: 0x27,
    # punctuation and control
    ecodes.KEY_ENTER: 0x28,
    ecodes.KEY_ESC: 0x29,
    ecodes.KEY_BACKSPACE: 0x2A,
    ecodes.KEY_TAB: 0x2B,
    ecodes.KEY_SPACE: 0x2C,
    ecodes.KEY_MINUS: 0x2D,
    ecodes.KEY_EQUAL: 0x2E,
    ecodes.KEY_LEFTBRACE: 0x2F,
    ecodes.KEY_RIGHTBRACE: 0x30,
    ecodes.KEY_BACKSLASH: 0x31,
    ecodes.KEY_SEMICOLON: 0x33,
    ecodes.KEY_APOSTROPHE: 0x34,
    ecodes.KEY_GRAVE: 0x35,
    ecodes.KEY_COMMA: 0x36,
    ecodes.KEY_DOT: 0x37,
    ecodes.KEY_SLASH: 0x38,
    ecodes.KEY_CAPSLOCK: 0x39,
    ecodes.KEY_102ND: 0x64,
    # function keys
    ecodes.KEY_F1: 0x3A,
    ecodes.KEY_F2: 0x3B,
    ecodes.KEY_F3: 0x3C,
    ecodes.KEY_F4: 0x3D,
    ecodes.KEY_F5: 0x3E,
    ecodes.KEY_F6: 0x3F,
    ecodes.KEY_F7: 0x40,
    ecodes.KEY_F8: 0x41,
    ecodes.KEY_F9: 0x42,
    ecodes.KEY_F10: 0x43,
    ecodes.KEY_F11: 0x44,
    ecodes.KEY_F12: 0x45,
    # system and navigation
    ecodes.KEY_SYSRQ: 0x46,
    ecodes.KEY_SCROLLLOCK: 0x47,
    ecodes.KEY_PAUSE: 0x48,
    ecodes.KEY_INSERT: 0x49,
    ecodes.KEY_HOME: 0x4A,
    ecodes.KEY_PAGEUP: 0x4B,
    ecodes.KEY_DELETE: 0x4C,
    ecodes.KEY_END: 0x4D,
    ecodes.KEY_PAGEDOWN: 0x4E,
    ecodes.KEY_RIGHT: 0x4F,
    ecodes.KEY_LEFT: 0x50,
    ecodes.KEY_DOWN: 0x51,
    ecodes.KEY_UP: 0x52,
    # keypad
    ecodes.KEY_NUMLOCK: 0x53,
    ecodes.KEY_KPSLASH: 0x54,
    ecodes.KEY_KPASTERISK: 0x55,
    ecodes.KEY_KPMINUS: 0x56,
    ecodes.KEY_KPPLUS: 0x57,
    ecodes.KEY_KPENTER: 0x58,
    ecodes.KEY_KP1: 0x59,
    ecodes.KEY_KP2: 0x5A,
    ecodes.KEY_KP3: 0x5B,
    ecodes.KEY_KP4: 0x5C,
    ecodes.KEY_KP5: 0x5D,
    ecodes.KEY_KP6: 0x5E,
    ecodes.KEY_KP7: 0x5F,
    ecodes.KEY_KP8: 0x60,
    ecodes.KEY_KP9: 0x61,
    ecodes.KEY_KP0: 0x62,
    ecodes.KEY_KPDOT: 0x63,
    # menu / application
    ecodes.KEY_COMPOSE: 0x65,
}


def modifier_bit(code: int) -> int | None:
    return MODIFIER_BITS.get(code)


def key_to_usage(code: int) -> int | None:
    return KEY_TO_USAGE.get(code)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_keymap.py -q
```

Expected: `6 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/keymap.py control/linux/tests/test_keymap.py
git commit -m "feat(linux): map evdev keys to HID usages"
```

---

### Task 4: 鼠标绝对坐标状态

**Files:**
- Create: `control/linux/src/cokvm_linux/mouse.py`
- Create: `control/linux/tests/test_mouse.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_mouse.py`:

```python
import pytest
from evdev import ecodes

from cokvm_linux import vss
from cokvm_linux.mouse import MouseState


def test_starts_at_center():
    state = MouseState(1920, 1080)
    assert state.pos == (vss.GRID_MAX // 2, vss.GRID_MAX // 2)


def test_move_scales_by_target_resolution():
    state = MouseState(1920, 1080)
    state.move(960, 540)
    assert state.pos == (vss.GRID_MAX, vss.GRID_MAX)
    assert state.x == pytest.approx(vss.GRID_MAX)
    assert state.y == pytest.approx(vss.GRID_MAX)


def test_move_clamps_to_grid():
    state = MouseState(1920, 1080)
    state.move(100000, -100000)
    assert state.pos == (vss.GRID_MAX, 0)


def test_sensitivity_multiplies_movement():
    state = MouseState(1920, 1080, sensitivity=0.5)
    state.move(960, 0)
    assert state.x == pytest.approx(12960)


def test_buttons_map_to_protocol_bits():
    state = MouseState()
    assert state.set_button(ecodes.BTN_LEFT, True) is True
    assert state.buttons == 0x01
    assert state.set_button(ecodes.BTN_RIGHT, True) is True
    assert state.buttons == 0x03
    assert state.set_button(ecodes.BTN_MIDDLE, True) is True
    assert state.buttons == 0x07
    assert state.set_button(ecodes.BTN_LEFT, False) is True
    assert state.buttons == 0x06
    assert state.set_button(ecodes.BTN_TOOL_DOUBLETAP, True) is False


def test_wheel_converts_notches_and_clamps():
    state = MouseState()
    assert state.wheel(1) == 120
    assert state.wheel(-1) == -120
    assert state.wheel(3) == 127
    assert state.wheel(-2) == -127
    assert state.wheel(0) == 0


def test_reset_center_clears_buttons():
    state = MouseState()
    state.move(100, 100)
    state.set_button(ecodes.BTN_LEFT, True)
    state.reset_center()
    assert state.pos == (vss.GRID_MAX // 2, vss.GRID_MAX // 2)
    assert state.buttons == 0


def test_rejects_invalid_resolution():
    with pytest.raises(ValueError):
        MouseState(0, 1080)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_mouse.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.mouse'`。

- [ ] **Step 3: 实现 `mouse.py`**

`control/linux/src/cokvm_linux/mouse.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_mouse.py -q
```

Expected: `8 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/mouse.py control/linux/tests/test_mouse.py
git commit -m "feat(linux): add absolute mouse state"
```

---

### Task 5: Ctrl+Alt+Esc 热键检测

**Files:**
- Create: `control/linux/src/cokvm_linux/hotkey.py`
- Create: `control/linux/tests/test_hotkey.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_hotkey.py`:

```python
from evdev import ecodes

from cokvm_linux.hotkey import HotkeyDetector


def test_triggers_when_three_keys_are_down():
    detector = HotkeyDetector()
    assert detector.feed(ecodes.KEY_LEFTCTRL, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_LEFTALT, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_ESC, 1, 1.0) is True


def test_order_does_not_matter():
    detector = HotkeyDetector()
    assert detector.feed(ecodes.KEY_ESC, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_LEFTALT, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_RIGHTCTRL, 1, 1.0) is True


def test_requires_esc_release_before_retrigger():
    detector = HotkeyDetector(cooldown=0.15)
    assert detector.feed(ecodes.KEY_LEFTCTRL, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_LEFTALT, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_ESC, 1, 1.0) is True
    assert detector.feed(ecodes.KEY_ESC, 2, 1.0) is False
    assert detector.feed(ecodes.KEY_ESC, 0, 1.05) is False
    assert detector.feed(ecodes.KEY_ESC, 1, 1.10) is False
    assert detector.feed(ecodes.KEY_ESC, 0, 1.12) is False
    assert detector.feed(ecodes.KEY_ESC, 1, 1.30) is True


def test_ignores_unrelated_keys_and_repeats():
    detector = HotkeyDetector()
    assert detector.feed(ecodes.KEY_A, 1, 1.0) is False
    assert detector.feed(ecodes.KEY_LEFTCTRL, 2, 1.0) is False


def test_chord_down_tracks_all_three():
    detector = HotkeyDetector()
    detector.feed(ecodes.KEY_LEFTCTRL, 1, 1.0)
    detector.feed(ecodes.KEY_LEFTALT, 1, 1.0)
    assert detector.chord_down is False
    detector.feed(ecodes.KEY_ESC, 1, 1.0)
    assert detector.chord_down is True
    detector.feed(ecodes.KEY_ESC, 0, 1.0)
    assert detector.chord_down is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_hotkey.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.hotkey'`。

- [ ] **Step 3: 实现 `hotkey.py`**

`control/linux/src/cokvm_linux/hotkey.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_hotkey.py -q
```

Expected: `5 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/hotkey.py control/linux/tests/test_hotkey.py
git commit -m "feat(linux): detect Ctrl+Alt+Esc hotkey"
```

---

### Task 6: 设备枚举与过滤

**Files:**
- Create: `control/linux/src/cokvm_linux/devices.py`
- Create: `control/linux/tests/test_devices.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_devices.py`:

```python
from evdev import ecodes

from cokvm_linux.devices import DeviceInfo, classify, select


def make_info(name="device", path="/dev/input/event0", bustype=ecodes.BUS_USB,
              key=(), rel=(), abs_=(), sw=()):
    return DeviceInfo(
        path=path,
        name=name,
        bustype=bustype,
        key_caps=frozenset(key),
        rel_caps=frozenset(rel),
        abs_caps=frozenset(abs_),
        sw_caps=frozenset(sw),
    )


def test_classifies_keyboard():
    info = make_info(key=(ecodes.KEY_A, ecodes.KEY_LEFTSHIFT))
    assert classify(info) == "keyboard"


def test_classifies_mouse_by_relative_axes():
    info = make_info(key=(ecodes.BTN_LEFT,), rel=(ecodes.REL_X, ecodes.REL_Y))
    assert classify(info) == "mouse"


def test_classifies_absolute_mouse():
    info = make_info(
        key=(ecodes.BTN_LEFT,),
        abs_=(ecodes.ABS_X, ecodes.ABS_Y),
    )
    assert classify(info) == "mouse"


def test_skips_touchpad():
    info = make_info(
        key=(ecodes.BTN_TOUCH,),
        abs_=(ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y),
    )
    assert classify(info) == "touchpad"


def test_skips_virtual_and_power_only_devices():
    virtual = make_info(bustype=ecodes.BUS_VIRTUAL, key=(ecodes.KEY_A,))
    power = make_info(key=(ecodes.KEY_POWER,))
    assert classify(virtual) is None
    assert classify(power) is None


def test_select_honours_include_and_exclude():
    keyboard = make_info("AT Keyboard", "/dev/input/event1", key=(ecodes.KEY_A,))
    mouse = make_info("Logitech Mouse", "/dev/input/event2",
                      key=(ecodes.BTN_LEFT,), rel=(ecodes.REL_X, ecodes.REL_Y))
    touchpad = make_info("SynPS/2 Touchpad", "/dev/input/event3",
                         abs_=(ecodes.ABS_MT_POSITION_X,))
    infos = [keyboard, mouse, touchpad]
    assert select(infos) == [keyboard, mouse]
    assert select(infos, include=("Logitech*",)) == [mouse]
    assert select(infos, exclude=("AT*",)) == [mouse]
    assert select(infos, include=("*event2",)) == [mouse]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_devices.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.devices'`。

- [ ] **Step 3: 实现 `devices.py`**

`control/linux/src/cokvm_linux/devices.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_devices.py -q
```

Expected: `6 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/devices.py control/linux/tests/test_devices.py
git commit -m "feat(linux): enumerate and filter input devices"
```

---

### Task 7: 发送队列与节流

**Files:**
- Create: `control/linux/src/cokvm_linux/sender.py`
- Create: `control/linux/tests/test_sender.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_sender.py`:

```python
import asyncio

from cokvm_linux.sender import FrameSender


class RecordingTransport:
    def __init__(self):
        self.frames = []

    async def send(self, frame: bytes):
        self.frames.append(frame)


async def test_keyboard_has_priority_and_motion_is_coalesced():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_motion(b"m1")
    sender.submit_motion(b"m2")
    sender.submit_discrete(b"d1")
    sender.submit_keyboard(b"k1")
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == [b"k1", b"d1", b"m2"]


async def test_keyboard_frames_preserve_order():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_keyboard(b"k1")
    sender.submit_keyboard(b"k2")
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == [b"k1", b"k2"]


async def test_clear_drops_pending_frames():
    transport = RecordingTransport()
    sender = FrameSender(transport, interval=0)
    sender.submit_keyboard(b"k1")
    sender.submit_motion(b"m1")
    sender.clear()
    sender.start()
    await sender.drain()
    await sender.stop()
    assert transport.frames == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_sender.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.sender'`。

- [ ] **Step 3: 实现 `sender.py`**

`control/linux/src/cokvm_linux/sender.py`:

```python
"""Send VSS frames with keyboard priority and motion coalescing."""

from __future__ import annotations

import asyncio
import logging
from collections import deque

log = logging.getLogger(__name__)


class FrameSender:
    def __init__(self, transport, interval: float = 0.008):
        self._transport = transport
        self._interval = interval
        self._keyboard: deque[bytes] = deque()
        self._discrete: deque[bytes] = deque()
        self._motion: bytes | None = None
        self._event = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def submit_keyboard(self, frame: bytes) -> None:
        self._keyboard.append(frame)
        self._wake()

    def submit_discrete(self, frame: bytes) -> None:
        self._discrete.append(frame)
        self._wake()

    def submit_motion(self, frame: bytes) -> None:
        self._motion = frame
        self._wake()

    def clear(self) -> None:
        self._keyboard.clear()
        self._discrete.clear()
        self._motion = None
        self._idle.set()

    async def drain(self, timeout: float = 0.2) -> None:
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def _wake(self) -> None:
        self._idle.clear()
        self._event.set()

    async def _run(self) -> None:
        while True:
            await self._event.wait()
            while self._keyboard or self._discrete or self._motion is not None:
                if self._keyboard:
                    frame = self._keyboard.popleft()
                elif self._discrete:
                    frame = self._discrete.popleft()
                else:
                    frame = self._motion
                    self._motion = None
                    if self._interval:
                        await asyncio.sleep(self._interval)
                try:
                    await self._transport.send(frame)
                except Exception:
                    log.exception("frame send failed")
            self._event.clear()
            self._idle.set()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_sender.py -q
```

Expected: `3 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/sender.py control/linux/tests/test_sender.py
git commit -m "feat(linux): add prioritized frame sender"
```

---

### Task 8: evdev 事件源

**Files:**
- Create: `control/linux/src/cokvm_linux/input_source.py`
- Create: `control/linux/tests/test_input_source.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_input_source.py`:

```python
from types import SimpleNamespace

from cokvm_linux.input_source import EvdevEventSource


class FakeLoop:
    def __init__(self):
        self.readers = {}

    def add_reader(self, fd, callback, *args):
        self.readers[fd] = (callback, args)

    def remove_reader(self, fd):
        self.readers.pop(fd, None)


class FakeDevice:
    def __init__(self, fd, events):
        self.fd = fd
        self.path = f"/dev/input/event{fd}"
        self._events = list(events)
        self.grabbed = False
        self.closed = False

    def read(self):
        events, self._events = self._events, []
        return events

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.grabbed = False

    def close(self):
        self.closed = True


def test_registers_readers_and_forwards_events():
    loop = FakeLoop()
    received = []
    device = FakeDevice(900001, [
        SimpleNamespace(type=1, code=30, value=1),
        SimpleNamespace(type=0, code=0, value=0),
    ])
    source = EvdevEventSource(loop, ["/dev/input/event900001"],
                              lambda *event: received.append(event),
                              open_device=lambda path: device)
    assert 900001 in loop.readers
    callback, args = loop.readers[900001]
    callback(*args)
    assert received == [(1, 30, 1), (0, 0, 0)]


def test_grab_and_release():
    loop = FakeLoop()
    device = FakeDevice(900002, [])
    source = EvdevEventSource(loop, ["/dev/input/event900002"], lambda *_: None,
                              open_device=lambda path: device)
    source.set_grab(True)
    assert device.grabbed is True
    source.set_grab(False)
    assert device.grabbed is False


def test_close_removes_reader_and_closes_device():
    loop = FakeLoop()
    device = FakeDevice(900003, [])
    source = EvdevEventSource(loop, ["/dev/input/event900003"], lambda *_: None,
                              open_device=lambda path: device)
    source.close()
    assert 900003 not in loop.readers
    assert device.closed is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_input_source.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.input_source'`。

- [ ] **Step 3: 实现 `input_source.py`**

`control/linux/src/cokvm_linux/input_source.py`:

```python
"""Read evdev events through the asyncio selector."""

from __future__ import annotations

import asyncio
import logging
import os

import evdev

log = logging.getLogger(__name__)


class EvdevEventSource:
    def __init__(self, loop: asyncio.AbstractEventLoop, paths: list[str], on_event,
                 open_device=evdev.InputDevice):
        self._loop = loop
        self._on_event = on_event
        self._devices: dict[int, object] = {}
        for path in paths:
            device = open_device(path)
            try:
                os.set_blocking(device.fd, False)
            except OSError:
                pass
            self._loop.add_reader(device.fd, self._on_readable, device)
            self._devices[device.fd] = device

    def _on_readable(self, device) -> None:
        try:
            for event in device.read():
                self._on_event(event.type, event.code, event.value)
        except (BlockingIOError, OSError):
            pass

    def set_grab(self, enabled: bool) -> None:
        for device in self._devices.values():
            try:
                if enabled:
                    device.grab()
                else:
                    device.ungrab()
            except OSError as exc:
                log.warning("grab %s failed: %s", getattr(device, "path", "?"), exc)

    def close(self) -> None:
        for fd, device in list(self._devices.items()):
            try:
                self._loop.remove_reader(fd)
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass
        self._devices.clear()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_input_source.py -q
```

Expected: `3 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/input_source.py control/linux/tests/test_input_source.py
git commit -m "feat(linux): add evdev event source"
```

---

### Task 9: BLE 传输

**Files:**
- Create: `control/linux/src/cokvm_linux/ble.py`
- Create: `control/linux/tests/test_ble.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_ble.py`:

```python
import asyncio

import pytest

from cokvm_linux.ble import BleError, BleTransport, backoff_delays


class FakeClient:
    def __init__(self, reads, write_error=None):
        self._reads = list(reads)
        self._write_error = write_error
        self.paired = False
        self.disconnected = False

    async def connect(self, timeout=None):
        return None

    async def read_gatt_char(self, uuid):
        item = self._reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def pair(self):
        self.paired = True

    async def disconnect(self):
        self.disconnected = True

    async def write_gatt_char(self, uuid, frame, response=True):
        if self._write_error is not None:
            raise self._write_error


def make_transport(client):
    async def find():
        return object()

    return BleTransport(
        "CoKVM-Dongle",
        find_device=find,
        client_factory=lambda device: client,
    )


def test_backoff_sequence_is_capped():
    gen = backoff_delays(max_delay=30.0)
    values = [next(gen) for _ in range(8)]
    assert values == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


async def test_connect_authenticates_with_ok():
    client = FakeClient([b"OK"])
    transport = make_transport(client)
    await transport.connect()
    assert transport.authenticated is True


async def test_connect_pairs_after_security_error():
    client = FakeClient([RuntimeError("encrypt"), b"OK"])
    transport = make_transport(client)
    await transport.connect()
    assert client.paired is True
    assert transport.authenticated is True


async def test_connect_rejects_bad_handshake():
    client = FakeClient([b"NO"])
    transport = make_transport(client)
    with pytest.raises(BleError):
        await transport.connect()
    assert transport.authenticated is False
    assert client.disconnected is True


async def test_three_write_failures_trigger_disconnect_callback():
    client = FakeClient([b"OK"], write_error=RuntimeError("link lost"))
    disconnected = asyncio.Event()
    transport = BleTransport(
        "CoKVM-Dongle",
        on_disconnect=disconnected.set,
        find_device=None,
        client_factory=lambda device: client,
    )

    async def find():
        return object()

    transport._find_device = find
    await transport.connect()
    for _ in range(3):
        await transport.send(b"\x00" * 22)
    await asyncio.sleep(0)
    assert transport.authenticated is False
    assert disconnected.is_set()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_ble.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.ble'`。

- [ ] **Step 3: 实现 `ble.py`**

`control/linux/src/cokvm_linux/ble.py`:

```python
"""BLE transport for the CoKVM VSS service."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient, BleakScanner

log = logging.getLogger(__name__)

SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
DATA_UUID = "0000ff1d-0000-1000-8000-00805f9b34fb"
INFO_UUID = "0000ff2c-0000-1000-8000-00805f9b34fb"
OK = b"OK"
MAX_WRITE_FAILURES = 3


class BleError(Exception):
    pass


def backoff_delays(max_delay: float = 30.0):
    delay = 1.0
    while True:
        yield min(delay, max_delay)
        delay *= 2


class BleTransport:
    def __init__(self, device_name: str, on_disconnect=None,
                 scanner_timeout: float = 10.0, connect_timeout: float = 15.0,
                 write_timeout: float = 1.0, find_device=None, client_factory=None):
        self._device_name = device_name
        self._on_disconnect_cb = on_disconnect
        self._scanner_timeout = scanner_timeout
        self._connect_timeout = connect_timeout
        self._write_timeout = write_timeout
        self._find_device = find_device or self._bleak_find
        self._client_factory = client_factory or self._bleak_client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._write_failures = 0
        self.authenticated = False

    async def _bleak_find(self):
        return await BleakScanner.find_device_by_filter(
            lambda device, adv: (device.name or adv.local_name) == self._device_name,
            timeout=self._scanner_timeout,
        )

    def _bleak_client(self, device):
        return BleakClient(device, disconnected_callback=self._on_disconnect)

    def _on_disconnect(self, client) -> None:
        self.authenticated = False
        if self._loop is not None and self._on_disconnect_cb is not None:
            self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        device = await self._find_device()
        if device is None:
            raise BleError(f"device {self._device_name!r} not found")
        client = self._client_factory(device)
        self._client = client
        try:
            await client.connect(timeout=self._connect_timeout)
            try:
                data = await client.read_gatt_char(INFO_UUID)
            except Exception:
                await client.pair()
                data = await client.read_gatt_char(INFO_UUID)
        except Exception as exc:
            self._client = None
            try:
                await client.disconnect()
            except Exception:
                pass
            raise BleError(f"connect failed: {exc}") from exc
        if data != OK:
            self._client = None
            try:
                await client.disconnect()
            except Exception:
                pass
            raise BleError(f"authentication failed: {data!r}")
        self.authenticated = True
        self._write_failures = 0
        log.info("connected to %s", self._device_name)

    async def send(self, frame: bytes) -> None:
        client = self._client
        if not self.authenticated or client is None:
            log.debug("dropping frame: not connected")
            return
        try:
            await asyncio.wait_for(
                client.write_gatt_char(DATA_UUID, frame, response=False),
                timeout=self._write_timeout,
            )
            self._write_failures = 0
        except Exception as exc:
            self._write_failures += 1
            log.warning("write failed (%d/%d): %s",
                        self._write_failures, MAX_WRITE_FAILURES, exc)
            if self._write_failures >= MAX_WRITE_FAILURES:
                self.authenticated = False
                if self._loop is not None and self._on_disconnect_cb is not None:
                    self._loop.call_soon_threadsafe(self._on_disconnect_cb)

    async def close(self) -> None:
        self.authenticated = False
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_ble.py -q
```

Expected: `5 passed`。若 `test_three_write_failures_trigger_disconnect_callback` 因 `find_device=None` 报错，确认测试里已覆盖 `transport._find_device = find`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/ble.py control/linux/tests/test_ble.py
git commit -m "feat(linux): add BLE transport"
```

---

### Task 10: BlueZ 配对 Agent

**Files:**
- Create: `control/linux/src/cokvm_linux/agent.py`
- Create: `control/linux/tests/test_agent.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_agent.py`:

```python
import io

import pytest
from dbus_fast import DBusError

from cokvm_linux.agent import AgentError, PairingAgent, parse_passkey, read_passkey


def test_parse_passkey_accepts_six_digits():
    assert parse_passkey("123456\n") == 123456


@pytest.mark.parametrize("value", ["12345", "1234567", "abcdef", "", "12 456"])
def test_parse_passkey_rejects_bad_input(value):
    with pytest.raises(AgentError):
        parse_passkey(value)


def test_read_passkey_prompts_and_reads():
    out = io.StringIO()
    assert read_passkey(io.StringIO("654321\n"), out) == 654321
    assert out.getvalue() == "配对码: "


def test_agent_returns_provider_value():
    agent = PairingAgent(lambda: 112233)
    assert agent.RequestPasskey("/org/bluez/hci0/dev") == 112233


def test_agent_rejects_provider_failure():
    agent = PairingAgent(lambda: (_ for _ in ()).throw(AgentError("no tty")))
    with pytest.raises(DBusError):
        agent.RequestPasskey("/org/bluez/hci0/dev")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_agent.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.agent'`。

- [ ] **Step 3: 实现 `agent.py`**

`control/linux/src/cokvm_linux/agent.py`:

```python
"""BlueZ Agent1 implementation for passkey pairing."""

from __future__ import annotations

from dbus_fast import DBusError
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType
from dbus_fast.service import ServiceInterface, method

AGENT_PATH = "/org/bluez/cokvm_agent"
AGENT_CAPABILITY = "KeyboardOnly"


class AgentError(Exception):
    pass


def parse_passkey(text: str) -> int:
    value = text.strip()
    if len(value) != 6 or not value.isdigit():
        raise AgentError("配对码必须是 6 位数字")
    return int(value)


def read_passkey(stream_in, stream_out, prompt: str = "配对码: ") -> int:
    stream_out.write(prompt)
    stream_out.flush()
    line = stream_in.readline()
    if not line:
        raise AgentError("没有读到配对码")
    return parse_passkey(line)


def read_passkey_from_tty(prompt: str = "配对码: ") -> int:
    try:
        tty = open("/dev/tty", "r+", encoding="utf-8")
    except OSError as exc:
        raise AgentError("没有可用的终端（/dev/tty），请先用 bluetoothctl 配对") from exc
    with tty:
        return read_passkey(tty, tty, prompt)


class PairingAgent(ServiceInterface):
    def __init__(self, passkey_provider):
        super().__init__("org.bluez.Agent1")
        self._passkey_provider = passkey_provider

    def _passkey(self) -> int:
        try:
            value = int(self._passkey_provider())
        except Exception as exc:
            raise DBusError("org.bluez.Error.Rejected", str(exc)) from exc
        if not 0 <= value <= 999999:
            raise DBusError("org.bluez.Error.Rejected", "invalid passkey")
        return value

    @method()
    def Release(self):
        return None

    @method()
    def RequestPinCode(self, device: "o") -> "s":
        raise DBusError("org.bluez.Error.Rejected", "PIN code not supported")

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        return None

    @method()
    def RequestPasskey(self, device: "o") -> "u":
        return self._passkey()

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        return None

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        return None

    @method()
    def RequestAuthorization(self, device: "o"):
        return None

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        return None

    @method()
    def Cancel(self):
        return None


async def register_agent(passkey_provider, bus=None):
    if bus is None:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    agent = PairingAgent(passkey_provider)
    bus.export(AGENT_PATH, agent)
    introspection = await bus.introspect("org.bluez", "/org/bluez")
    proxy = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
    interface = proxy.get_interface("org.bluez.AgentManager1")
    await interface.call_register_agent(AGENT_PATH, AGENT_CAPABILITY)
    await interface.call_request_default_agent(AGENT_PATH)
    return bus, agent
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_agent.py -q
```

Expected: `9 passed`（参数化 5 个 + 4 个普通用例）。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/agent.py control/linux/tests/test_agent.py
git commit -m "feat(linux): add BlueZ pairing agent"
```

---

### Task 11: 控制器状态机

**Files:**
- Create: `control/linux/src/cokvm_linux/app.py`
- Create: `control/linux/tests/test_controller.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_controller.py`:

```python
import asyncio

import pytest
from evdev import ecodes

from cokvm_linux import vss
from cokvm_linux.app import Config, Controller, FrameSender


class FakeTransport:
    def __init__(self, authenticated=True):
        self.authenticated = authenticated
        self.frames = []

    async def connect(self):
        return None

    async def send(self, frame):
        self.frames.append(frame)

    async def close(self):
        return None


class FakeSource:
    def __init__(self):
        self.grabbed = False
        self.closed = False

    def set_grab(self, enabled):
        self.grabbed = enabled

    def close(self):
        self.closed = True


@pytest.fixture
async def env():
    transport = FakeTransport()
    sender = FrameSender(transport, interval=0)
    source = FakeSource()
    controller = Controller(
        Config(),
        sender,
        transport,
        source_factory=lambda paths, callback: source,
    )
    controller.open_source([])
    sender.start()
    yield controller, sender, transport, source
    await sender.stop()


async def test_enter_and_exit_via_hotkey(env):
    controller, sender, transport, source = env
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1) is None
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1) is None
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    assert coro is not None
    await coro
    assert controller.state == "CAPTURING"
    assert source.grabbed is True

    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 0)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 0)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)

    await asyncio.sleep(0.16)  # let the hotkey cooldown expire

    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1) is None
    assert controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1) is None
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    assert coro is not None
    await coro
    assert controller.state == "MONITOR"
    assert source.grabbed is False


async def test_keyboard_frames(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_A, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [0x04])
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_A, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [])


async def test_modifier_frame(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(vss.MOD_LSHIFT, [])


async def test_six_key_rollover(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    for code in (ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_C,
                 ecodes.KEY_D, ecodes.KEY_E, ecodes.KEY_F):
        controller.handle_event(ecodes.EV_KEY, code, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_G, 1)
    await sender.drain()
    assert transport.frames[-1] == vss.keyboard_frame(0, [0x04, 0x05, 0x06, 0x07, 0x08, 0x09])


async def test_mouse_motion_uses_resolution_scale(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_REL, ecodes.REL_X, 10)
    controller.handle_event(ecodes.EV_REL, ecodes.REL_Y, 5)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0, 8730, 8720, 0)


async def test_mouse_buttons_and_wheel(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0x01, 8640, 8640, 0)

    controller.handle_event(ecodes.EV_REL, ecodes.REL_WHEEL, 1)
    controller.handle_event(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
    await sender.drain()
    assert transport.frames[-1] == vss.mouse_frame(0x01, 8640, 8640, 120)


async def test_hotkey_escape_is_not_forwarded(env):
    controller, sender, transport, source = env
    await controller.enter_capture()
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
    controller.handle_event(ecodes.EV_KEY, ecodes.KEY_LEFTALT, 1)
    coro = controller.handle_event(ecodes.EV_KEY, ecodes.KEY_ESC, 1)
    await coro
    await sender.drain()
    assert vss.keyboard_frame(0, [0x29]) not in transport.frames
    assert transport.frames[-1] == vss.keyboard_frame(0, [])


async def test_force_release_restores_local_input(env):
    controller, sender, transport, source = env
    controller.state = "CAPTURING"
    source.grabbed = True
    controller.force_release("disconnect")
    assert controller.state == "MONITOR"
    assert source.grabbed is False


async def test_cannot_enter_without_authenticated_link(env):
    controller, sender, transport, source = env
    transport.authenticated = False
    await controller.enter_capture()
    assert controller.state == "MONITOR"
    assert source.grabbed is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_controller.py -q
```

Expected: FAIL，`ImportError: cannot import name 'Controller'`。

- [ ] **Step 3: 实现 `app.py` 的 `Config`、`FrameSender` 与 `Controller`**

`control/linux/src/cokvm_linux/app.py`（本步先写状态机部分，运行编排在 Task 12 追加）：

```python
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
        self._mods = 0
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
        elif type_ == ecodes.EV_SYN and code == ecodes.SYN_REPORT:
            self._flush_mouse()
        return None

    def _handle_key(self, code: int, value: int) -> None:
        if value == 2:
            return
        modifier = keymap.modifier_bit(code)
        usage = keymap.key_to_usage(code)
        if modifier is not None:
            if value == 1:
                self._mods |= modifier
            else:
                self._mods &= ~modifier
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
        if self._pending_dx or self._pending_dy:
            self.mouse.move(self._pending_dx, self._pending_dy)
            self._pending_dx = 0
            self._pending_dy = 0
            self.sender.submit_motion(self._mouse_frame())
        if self._pending_buttons:
            self._pending_buttons = False
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
        self.state = "CAPTURING"
        self._set_grab(True)
        self._mods = 0
        self._keys.clear()
        self._swallow_chord = False
        self.mouse.reset_center()
        self.sender.submit_keyboard(vss.keyboard_frame(0, []))
        self.sender.submit_discrete(self._mouse_frame())
        log.info("MONITOR -> CAPTURING")

    async def exit_capture(self, reason: str) -> None:
        if self.state != "CAPTURING":
            return
        self.state = "RELEASING"
        self.sender.submit_keyboard(vss.keyboard_frame(0, []))
        await self.sender.drain(0.2)
        self._set_grab(False)
        self._mods = 0
        self._keys.clear()
        self.state = "MONITOR"
        log.info("CAPTURING -> MONITOR (%s)", reason)

    def force_release(self, reason: str) -> None:
        self._set_grab(False)
        self.sender.clear()
        self._mods = 0
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_controller.py -q
```

Expected: `9 passed`。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/app.py control/linux/tests/test_controller.py
git commit -m "feat(linux): add controller state machine"
```

---

### Task 12: 运行编排、断线重连与热插拔

**Files:**
- Modify: `control/linux/src/cokvm_linux/app.py`
- Create: `control/linux/tests/test_orchestration.py`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_orchestration.py`:

```python
import asyncio

from cokvm_linux.app import DryRunTransport


async def test_dry_run_transport_is_authenticated(capsys):
    transport = DryRunTransport()
    assert transport.authenticated is True
    await transport.send(b"\x00" * 22)
    captured = capsys.readouterr()
    assert "frame" in captured.err
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_orchestration.py -q
```

Expected: FAIL，`ImportError: cannot import name 'DryRunTransport'`。

- [ ] **Step 3: 在 `app.py` 末尾追加编排代码**

在 `control/linux/src/cokvm_linux/app.py` 的 import 区补充：

```python
import atexit
import signal
import sys

from . import devices
from .agent import read_passkey_from_tty, register_agent
from .ble import BleTransport, backoff_delays
from .input_source import EvdevEventSource
```

在文件末尾追加：

```python
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
                log.info("BLE connected and authenticated")
            except Exception as exc:
                log.warning("BLE connect failed: %s", exc)
                await _sleep_or_stop(next(delays), stop)
                continue
        disconnected.clear()
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
            infos = devices.select(
                devices.enumerate_devices(), config.include, config.exclude)
            paths = [info.path for info in infos]
        except Exception as exc:
            log.warning("device refresh failed: %s", exc)
            continue
        if controller.state != "MONITOR":
            if not set(controller.paths).issubset(set(paths)):
                log.warning("input device removed while capturing; releasing")
                controller.force_release("device removed")
            continue
        if set(paths) != set(controller.paths):
            controller.open_source(paths)
            log.info("input devices changed: %d device(s)", len(paths))


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
    log.info("input devices: %d", len(infos))
    sender.start()

    hotplug_task = asyncio.create_task(_hotplug_loop(controller, config, stop))
    connection_task = None
    if not config.dry_run:
        try:
            await register_agent(read_passkey_from_tty)
            log.info("pairing agent registered")
        except Exception as exc:
            log.warning("pairing agent unavailable: %s", exc)
        connection_task = asyncio.create_task(
            _connection_loop(controller, transport, disconnected, stop))

    try:
        await stop.wait()
    finally:
        atexit.unregister(release_on_exit)
        controller.force_release("shutdown")
        await sender.stop()
        controller.close_source()
        await transport.close()
        hotplug_task.cancel()
        if connection_task is not None:
            connection_task.cancel()
        tasks = [hotplug_task] + ([connection_task] if connection_task else [])
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0
```

- [ ] **Step 4: 运行全部测试**

```bash
cd control/linux
.venv/bin/pytest -q
```

Expected: 全部通过（`test_orchestration.py` 1 个 + 之前所有用例）。

- [ ] **Step 5: 提交**

```bash
git add control/linux/src/cokvm_linux/app.py control/linux/tests/test_orchestration.py
git commit -m "feat(linux): wire reconnection, hotplug and signals"
```

---

### Task 13: CLI 与 README

**Files:**
- Create: `control/linux/src/cokvm_linux/cli.py`
- Create: `control/linux/tests/test_cli.py`
- Modify: `control/linux/README.md`

- [ ] **Step 1: 写失败测试**

`control/linux/tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd control/linux
.venv/bin/pytest tests/test_cli.py -q
```

Expected: FAIL，`ModuleNotFoundError: No module named 'cokvm_linux.cli'`。

- [ ] **Step 3: 实现 `cli.py`**

`control/linux/src/cokvm_linux/cli.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd control/linux
.venv/bin/pytest tests/test_cli.py -q
```

Expected: `7 passed`（参数化 5 个 + 2 个普通用例）。

- [ ] **Step 5: 写完整 README**

`control/linux/README.md`:

````markdown
# CoKVM Linux client

Keyboard/mouse-only control client for CoKVM. It grabs your local keyboard and
mouse, forwards them to a CoKVM Dongle over BLE, and gives them back with a
hotkey. No video capture is involved: keep the controlled machine's own monitor
in view.

Protocol: `docs/protocols.cn.md`. Design: `docs/specs/2026-11-25-linux-control-design.md`.

## Requirements

- Linux with BlueZ.
- Python 3.10+.
- Build tools for `python-evdev` if no wheel is available:
  `sudo apt install python3-dev build-essential`.
- Your user in the `input` group: `sudo usermod -aG input "$USER"` then log out
  and back in.

## Install

```bash
cd control/linux
python3 -m venv .venv
.venv/bin/pip install -e .
```

Verify input access:

```bash
.venv/bin/cokvm-linux list-devices
```

## Pairing

1. Plug the Dongle into a machine where you can open its USB serial console.
2. Run `cokvm pair` on the Dongle console (60-second pairing window).
3. Run `cokvm-linux run` on the control machine.
4. When prompted, type the 6-digit code printed on the Dongle console.
5. Move the Dongle to the controlled machine. Later reconnects are automatic.

If the pairing agent cannot register (for example under a restrictive D-Bus
policy), pair once with `bluetoothctl`:

```bash
bluetoothctl --agent KeyboardOnly
> pair <dongle-address>
> trust <dongle-address>
```

## Usage

```bash
cokvm-linux run
cokvm-linux run --target-resolution 2560x1440
cokvm-linux run --exclude 'SynPS/2*' --include 'AT Translated Set 2*'
cokvm-linux run --dry-run --verbose   # print frames, no BLE
```

- `Ctrl+Alt+Esc` grabs local input and starts controlling the controlled host.
- `Ctrl+Alt+Esc` again releases local input immediately.
- Unplugging the Dongle, losing BLE, or `kill`/`SIGTERM` also releases local
  input. A hard crash releases the grab when the process fd closes.
- While released, the hotkey is still visible to local applications (it cannot
  be swallowed without grabbing). The chord is unbound in common desktops.

## Limitations

- No video capture.
- No touchpad support (raw `ABS_MT_*` events are not pointer motion).
- 6KRO keyboard, no media keys, no right-modifier distinction, no LED sync.
- One Dongle supports one BLE connection.
- Mouse motion is sent without BLE retransmission; weak links may drop motion
  frames (keyboard frames are full-state and self-healing).

## Optional systemd user unit

`~/.config/systemd/user/cokvm-linux.service`:

```ini
[Unit]
Description=CoKVM Linux client
After=graphical-session.target

[Service]
ExecStart=%h/source/cokvm/control/linux/.venv/bin/cokvm-linux run
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now cokvm-linux.service
```

The passkey prompt needs a terminal; for an already-paired device no prompt is
needed.
````

- [ ] **Step 6: 运行全部测试**

```bash
cd control/linux
.venv/bin/pytest -q
```

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add control/linux/src/cokvm_linux/cli.py control/linux/tests/test_cli.py control/linux/README.md
git commit -m "feat(linux): add CLI and documentation"
```

---

### Task 14: 手工验收

**Files:**
- Modify: `control/linux/README.md`（仅在验收发现需要补充说明时）

前置条件：已按 Task 1-13 完成；手上有 CoKVM Dongle、受控机、普通 USB 鼠标与键盘；控制机已加入 `input` 组。

- [ ] **Step 1: 无 BLE 的本地验证**

```bash
cd control/linux
.venv/bin/cokvm-linux list-devices
.venv/bin/cokvm-linux run --dry-run --no-grab --verbose
```

在另一个终端按 `Ctrl+Alt+Esc`，再输入几个键、移动鼠标。Expected：stderr 出现 `MONITOR -> CAPTURING`，随后打印 22 字节十六进制帧；再按 `Ctrl+Alt+Esc` 出现 `CAPTURING -> MONITOR`。`Ctrl+Alt+Esc` 本身不应产生键盘帧。

- [ ] **Step 2: 真实配对**

1. Dongle 插到控制机，打开其 CDC ACM 控制台（`/dev/ttyACM*`，115200 8N1），执行 `cokvm pair`。
2. 运行 `.venv/bin/cokvm-linux run`，输入终端提示的 6 位码。
3. Expected：日志出现 `connected`，Dongle 绿色常亮；`cokvm-linux run` 不报认证错误。

- [ ] **Step 3: 基本输入**

把 Dongle 与受控机显示器就位，按 `Ctrl+Alt+Esc` 进入控制。

Expected：受控机可打字、可移动鼠标、左右中键与滚轮正常；鼠标能到达屏幕四角；滚轮不会把指针带到左上角。

- [ ] **Step 4: 切换与释放**

再次按 `Ctrl+Alt+Esc`。

Expected：本机立即恢复键鼠；终端出现 `CAPTURING -> MONITOR`。

- [ ] **Step 5: 断线释放**

进入控制后直接拔掉 Dongle。

Expected：本机键鼠在 1 秒内恢复；日志出现 `BLE disconnected; releasing local input`。

- [ ] **Step 6: 崩溃释放**

进入控制后执行 `kill -9 <pid>`。

Expected：本机键鼠立即恢复（内核释放 grab）。

- [ ] **Step 7: 触摸板与热插拔**

1. 启动时不插鼠标，`list-devices` 应把触摸板标为 `touchpad (unsupported)`。
2. 控制中拔掉鼠标。

Expected：触摸板不被抓取、不报错；拔掉鼠标后程序不崩溃，键盘仍可用。

- [ ] **Step 8: 记录结果并提交**

若验收发现需要补充 README 的说明，修改后：

```bash
git add control/linux/README.md
git commit -m "docs(linux): clarify manual acceptance notes"
```

若无需修改，跳过提交。

---

## 计划自查

- 规格覆盖：设备枚举（Task 6/12）、键盘（Task 11）、鼠标（Task 4/11）、热键与状态机（Task 5/11）、BLE 配对与断线（Task 9/10/12）、安全兜底（Task 11/12）、CLI（Task 13）、测试与验收（各 Task/14）。
- 未实现项均来自规格的非目标：视频、触摸板、LED 同步、多控制端。
- 类型与命名一致性：`Config`、`FrameSender`、`Controller.enter_capture/exit_capture/force_release`、`MouseState.pos/buttons/move/set_button/wheel`、`hotkey.CHORD_KEY_CODES/HotkeyDetector.feed/chord_down` 在测试与实现中保持一致。
