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
