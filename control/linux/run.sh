#!/usr/bin/env bash
# One-shot launcher for the CoKVM Linux control client.
#
# Usage:
#   ./run.sh                      # start with defaults
#   ./run.sh --target-resolution 2560x1440
#   ./run.sh --dry-run --verbose  # print frames, no BLE
#
# Any argument is passed through to `cokvm-linux run`.
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
client="$here/.venv/bin/cokvm-linux"

if [[ ! -x "$client" ]]; then
    cat >&2 <<EOF
error: $client not found.

Install the client first:
  cd "$here"
  python3 -m venv .venv
  .venv/bin/pip install -e .
EOF
    exit 1
fi

# The client needs to read /dev/input/event*. Logind does not grant this when
# the session is not local (or under some remote/container setups), so make
# sure the devices are readable and grant a per-user ACL when they are not.
shopt -s nullglob
events=(/dev/input/event*)
shopt -u nullglob

if (( ${#events[@]} == 0 )); then
    echo "error: no /dev/input/event* devices found" >&2
    exit 1
fi

unreadable=0
for dev in "${events[@]}"; do
    if [[ ! -r "$dev" ]]; then
        unreadable=1
        break
    fi
done

if (( unreadable )); then
    echo "input devices are not readable by $USER; granting access via ACL ..." >&2
    if ! sudo -v; then
        echo "error: sudo failed; either add yourself to the 'input' group:" >&2
        echo "  sudo usermod -aG input $USER   # then log out and back in" >&2
        echo "or grant a one-off ACL:" >&2
        echo "  sudo setfacl -m u:$USER:rw /dev/input/event*" >&2
        exit 1
    fi
    sudo setfacl -m "u:$USER:rw" "${events[@]}"
fi

exec "$client" run "$@"
