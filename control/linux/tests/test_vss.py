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
