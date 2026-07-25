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
# dr_mode=peripheral is required: it forces the dwc2 controller into USB
# device/gadget mode. Some stock Raspberry Pi OS images already ship a
# "dtoverlay=dwc2,dr_mode=host" line (for using the OTG port as a normal
# host port) - that setting is incompatible with gadget mode, so if we find
# an existing dtoverlay=dwc2 line we rewrite it rather than trusting it.
DWC2_LINE="dtoverlay=dwc2,dr_mode=peripheral"
if grep -q '^dtoverlay=dwc2' "$BOOT_CONFIG"; then
    if grep -qx "$DWC2_LINE" "$BOOT_CONFIG"; then
        echo "    $BOOT_CONFIG already configured for USB peripheral (gadget) mode"
    else
        sed -i "s/^dtoverlay=dwc2.*/$DWC2_LINE/" "$BOOT_CONFIG"
        echo "    rewrote existing dtoverlay=dwc2 line in $BOOT_CONFIG to force dr_mode=peripheral"
    fi
else
    echo "$DWC2_LINE" >> "$BOOT_CONFIG"
    echo "    added $DWC2_LINE to $BOOT_CONFIG"
fi

if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE=/boot/firmware/cmdline.txt
else
    CMDLINE=/boot/cmdline.txt
fi
if ! grep -q 'modules-load=dwc2' "$CMDLINE"; then
    sed -i 's/rootwait/rootwait modules-load=dwc2/' "$CMDLINE"
    echo "    added modules-load=dwc2 to $CMDLINE"
else
    echo "    modules-load=dwc2 already present in $CMDLINE"
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
