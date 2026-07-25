#!/bin/bash
# Creates a USB composite gadget exposing a boot-protocol keyboard (/dev/hidg0)
# and a boot-protocol mouse (/dev/hidg1) via configfs.
#
# Run once at boot, before hidproxy.service starts (see systemd/hidproxy-gadget.service).
set -e

GADGET_DIR=/sys/kernel/config/usb_gadget/hidproxy
UDC_NAME=$(ls /sys/class/udc | head -n1)

modprobe libcomposite || true

if [ -d "$GADGET_DIR" ]; then
    # Already created (e.g. service restarted) - nothing to do.
    exit 0
fi

mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

echo 0x1d6b > idVendor   # Linux Foundation
echo 0x0104 > idProduct  # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "000000000001" > strings/0x409/serialnumber
echo "hidproxy" > strings/0x409/manufacturer
echo "Bluetooth HID Proxy" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "Config 1" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

# --- Keyboard function (/dev/hidg0) ---
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol
echo 1 > functions/hid.usb0/subclass
echo 8 > functions/hid.usb0/report_length
KEYBOARD_DESC_HEX="05010906a101050719e029e71500250175019508810295017508810195057501050819012905910295017503910195067508150025650507190029658100c0"
echo -n "$KEYBOARD_DESC_HEX" | xxd -r -p > functions/hid.usb0/report_desc

# --- Mouse function (/dev/hidg1) ---
mkdir -p functions/hid.usb1
echo 2 > functions/hid.usb1/protocol
echo 1 > functions/hid.usb1/subclass
echo 4 > functions/hid.usb1/report_length
MOUSE_DESC_HEX="05010902a1010901a1000509190129051500250195057501810295017503810105010930093109381581257f750895038106c0c0"
echo -n "$MOUSE_DESC_HEX" | xxd -r -p > functions/hid.usb1/report_desc

ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

udevadm settle -t 5 || true

if [ -z "$UDC_NAME" ]; then
    echo "hid_gadget.sh: no UDC found (is dtoverlay=dwc2 enabled?)" >&2
    exit 1
fi

echo "$UDC_NAME" > UDC
