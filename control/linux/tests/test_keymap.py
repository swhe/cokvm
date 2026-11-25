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
