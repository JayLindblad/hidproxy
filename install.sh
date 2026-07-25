#!/bin/bash
# Installs hidproxy on a Raspberry Pi (tested target: Pi Zero W, Raspberry Pi OS Lite).
# Run as root: sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root: sudo ./install.sh" >&2
    exit 1
fi

INSTALL_DIR=/opt/hidproxy
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing OS packages"
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev python3-pip \
    build-essential \
    bluez bluetooth dbus

echo "==> Enabling the dwc2 USB gadget driver"
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG=/boot/firmware/config.txt
else
    BOOT_CONFIG=/boot/config.txt
fi
# config.txt supports bracketed conditional sections ([cm4], [pi5], [all],
# ...) - a bare dtoverlay=dwc2 line found by a naive grep/sed might actually
# live under a section for different hardware (observed in the wild: a
# stock image shipping "dtoverlay=dwc2,dr_mode=host" *inside a [cm5]
# section*, which silently never applies on a Pi Zero W and left the
# board on the legacy non-gadget-capable dwc_otg driver). Rewriting a line
# in place without knowing what section it's under is unsafe, and even a
# plain "does this line exist anywhere" check is unsafe too (that same
# board-scoped line would false-positive a match). So: only lines that
# appear *after* the file's last "[all]" marker count as unconditionally
# applied; anything else gets appended there (adding one final "[all]" if
# the file doesn't already end with one).
python3 - "$BOOT_CONFIG" <<'PYEOF'
import sys

path = sys.argv[1]
wanted = [
    "dtoverlay=dwc2,dr_mode=peripheral",  # forces USB device/gadget mode
    "disable_splash=1",  # skip the rainbow splash render
    "boot_delay=0",  # no artificial power-on delay
]

with open(path) as f:
    lines = f.read().splitlines()

all_indices = [i for i, line in enumerate(lines) if line.strip() == "[all]"]
tail_start = all_indices[-1] + 1 if all_indices else len(lines)
tail = [line.strip() for line in lines[tail_start:]]

missing = [line for line in wanted if line not in tail]
if not missing:
    print("    config.txt already has all fast-boot / gadget-mode settings")
else:
    if not all_indices:
        # Appending straight to EOF always lands under whatever the last
        # [all] section already is - a fresh header is only needed if the
        # file has no [all] section at all yet.
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append("[all]")
    lines.extend(missing)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    for line in missing:
        print(f"    appended under an unconditional [all] section: {line}")
PYEOF

if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE=/boot/firmware/cmdline.txt
else
    CMDLINE=/boot/cmdline.txt
fi
# Rewrite (or add) the modules-load= token on the kernel command line so it
# loads dwc2 and nothing else conflicting. In particular strip out g_hid if
# present: it's the older single-function USB gadget driver, it claims the
# Pi's one and only UDC for itself at boot (with no module parameters, so it
# doesn't even configure a usable HID function), and that's a hard conflict
# with the libcomposite/configfs gadget hidproxy sets up - the symptom is
# /sys/class/udc staying completely empty.
python3 - "$CMDLINE" <<'PYEOF'
import re
import sys

path = sys.argv[1]
with open(path) as f:
    content = f.read()


def fix_modules_load(match):
    mods = [m for m in match.group(1).split(",") if m and m != "g_hid"]
    if "dwc2" not in mods:
        mods.insert(0, "dwc2")
    return "modules-load=" + ",".join(mods)


if "modules-load=" in content:
    new_content = re.sub(r"modules-load=(\S*)", fix_modules_load, content)
else:
    new_content = re.sub(r"\brootwait\b", "rootwait modules-load=dwc2", content, count=1)

if new_content != content:
    with open(path, "w") as f:
        f.write(new_content)
    print(f"    updated modules-load= in {path}")
else:
    print(f"    {path} already correct")
PYEOF

# Older Raspberry Pi OS setups sometimes load gadget modules via /etc/modules
# instead of the kernel command line - same conflict, so check there too.
if [ -f /etc/modules ] && grep -q '^g_hid' /etc/modules; then
    sed -i 's/^g_hid/#g_hid  # disabled by hidproxy install.sh - conflicts with its USB gadget/' /etc/modules
    echo "    disabled g_hid in /etc/modules (conflicts with hidproxy's USB gadget)"
fi

echo "==> Copying hidproxy to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude venv \
    --exclude .git \
    "$SCRIPT_DIR"/ "$INSTALL_DIR"/
chmod +x "$INSTALL_DIR"/gadget/hid_gadget.sh "$INSTALL_DIR"/bin/hidproxy-pair

echo "==> Creating Python virtualenv"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR"

echo "==> Installing systemd units"
# Disable first in case an older install enabled these under a different
# [Install] target (systemctl enable adds a symlink for the current target
# but won't clean up one left over from a stale target on a prior install).
systemctl disable hidproxy-gadget.service hidproxy.service 2>/dev/null || true
cp "$INSTALL_DIR"/systemd/hidproxy-gadget.service /etc/systemd/system/
cp "$INSTALL_DIR"/systemd/hidproxy.service /etc/systemd/system/
ln -sf "$INSTALL_DIR/bin/hidproxy-pair" /usr/local/bin/hidproxy-pair

systemctl daemon-reload
systemctl enable bluetooth.service
systemctl enable hidproxy-gadget.service
systemctl enable hidproxy.service

echo
echo "==> Install complete."
echo "A reboot is required for dtoverlay=dwc2 to take effect (needed for the USB gadget)."
echo "After reboot, plug the Pi's USB *data* port (not PWR IN) into the target computer,"
echo "then run: hidproxy-pair   to open a Bluetooth pairing window."
echo
read -r -p "Reboot now? [y/N] " REPLY
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    reboot
fi
