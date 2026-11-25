# CoKVM Linux client

Keyboard/mouse-only control client for CoKVM. It grabs your local keyboard and
mouse, forwards them to a CoKVM Dongle over BLE, and gives them back with a
hotkey. No video capture is involved: keep the controlled machine's own monitor
in view.

Protocol: `../../docs/protocols.cn.md`. Design: `../../docs/specs/2026-11-25-linux-control-design.md`
(paths are relative to the repository root).

## Requirements

- Linux with BlueZ.
- Python 3.10+.
- Build tools for `python-evdev` if no wheel is available:
  `sudo apt install python3-dev build-essential`.
- Your user in the `input` group: `sudo usermod -aG input "$USER"` then log out
  and back in. Without this, `list-devices` prints nothing.

## Install

```bash
cd control/linux
python3 -m venv .venv
.venv/bin/pip install -e .
```

If building `evdev` from source fails (for example no `python3-dev` and no
sudo), install the distro package and recreate the venv so it can see it:

```bash
sudo apt install python3-evdev
python3 -m venv --system-site-packages .venv
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

- The hotkey only works after the log shows `BLE connected and authenticated`;
  before that it does nothing.
- `Ctrl+Alt+Esc` grabs local input and starts controlling the controlled host.
- `Ctrl+Alt+Esc` again releases local input immediately.
- Unplugging the Dongle, losing BLE, or `kill`/`SIGTERM` also releases local
  input. A hard crash releases the grab when the process fd closes.
- While released, the hotkey is still visible to local applications (it cannot
  be swallowed without grabbing). Some desktops bind `Ctrl+Alt+Esc` to something
  else (KDE uses it for Kill Window). If so, unbind or remap it before using
  this client.
- `--include`/`--exclude` patterns are matched against the device name, its
  `/dev/input/eventN` path, and its `/dev/input/by-id/...` symlink. By-id
  patterns must be full paths, e.g. `'/dev/input/by-id/usb-Logitech*'`.

## Limitations

- No video capture.
- No touchpad support (raw `ABS_MT_*` events are not pointer motion).
- No absolute pointing devices (graphics tablets); use a relative mouse.
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
# adjust this path to your checkout
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
