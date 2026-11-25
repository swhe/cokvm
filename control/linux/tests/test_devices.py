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
