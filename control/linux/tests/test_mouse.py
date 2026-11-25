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
