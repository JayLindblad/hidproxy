# hidproxy

Turns a Raspberry Pi Zero W into a Bluetooth-to-USB HID adapter: pair a
Bluetooth keyboard and/or mouse to the Pi, plug the Pi into a computer's USB
port, and the computer sees a plain USB keyboard/mouse. Useful for adding
Bluetooth input support to a machine (or a BIOS/KVM/console) that doesn't
have it, without any drivers on the host side.

```
[BT keyboard/mouse] --Bluetooth--> [Pi Zero W] --USB--> [target computer]
```

## How it works

- **USB side**: the Pi's USB OTG port is configured as a composite USB HID
  gadget (via configfs + the `dwc2` driver) exposing a boot-protocol
  keyboard and a boot-protocol mouse. This is the same mechanism used by
  USB Rubber Ducky-style devices, just driven by real input instead of a
  script. The target computer needs no special drivers — it's a standard
  USB HID device.
- **Bluetooth side**: BlueZ's normal HID-host support pairs with the
  keyboard/mouse and exposes them as regular `/dev/input/eventN` devices,
  same as if you'd paired a Bluetooth keyboard with a desktop Linux box.
- **The proxy** (`hidproxy` Python package) watches for those Bluetooth
  input devices appearing/disappearing, reads their evdev events, and
  writes the equivalent HID reports to `/dev/hidg0` (keyboard) and
  `/dev/hidg1` (mouse).

## Requirements

- Raspberry Pi Zero W (or Zero 2 W, or any Pi with USB OTG / `dwc2`
  support — the Pi 3/4's main USB-A ports do **not** support gadget mode).
- Raspberry Pi OS Lite (Bullseye or Bookworm), headless is fine.
- A micro-USB (or USB-C, on Zero 2 W) cable into the **USB** port, not the
  **PWR IN** port — only the USB data port supports gadget mode. If the Pi
  needs to be powered separately, use a USB hub in between with its own
  power, or a Y-cable.
- A classic Bluetooth (BR/EDR) HID keyboard/mouse. Bluetooth Low Energy
  keyboards that only speak HOGP (HID-over-GATT) are not supported — see
  Limitations below.

## Install

```
git clone <this repo> hidproxy
cd hidproxy
sudo ./install.sh
```

The installer:
1. Installs `bluez`, Python, and build dependencies.
2. Adds `dtoverlay=dwc2` to `config.txt` and `modules-load=dwc2` to
   `cmdline.txt` (idempotent — safe to re-run).
3. Copies the project to `/opt/hidproxy` and creates a venv there.
4. Installs and enables two systemd services:
   - `hidproxy-gadget.service` — creates the USB gadget at boot.
   - `hidproxy.service` — runs the proxy daemon.
5. Offers to reboot (required once, for the `dwc2` overlay to take effect).

## Pairing a keyboard/mouse

The daemon registers a Bluetooth pairing agent and opens a 120-second
pairing window each time it starts. To reopen that window later (e.g. to
pair a second device), SSH into the Pi and run:

```
hidproxy-pair            # 120s window
hidproxy-pair 300         # custom timeout in seconds
```

Then put your keyboard/mouse into pairing mode as usual. Most modern
Bluetooth keyboards/mice pair with no PIN prompt (Just Works). Older
keyboards that require a PIN will expect `0000` typed on the keyboard
itself, followed by Enter — the Pi supplies `0000` automatically on its
side. Once paired, devices are marked trusted and reconnect automatically
on their own after being turned back on, without needing to be re-paired.

Watch progress with:

```
journalctl -u hidproxy -f
```

## Limitations / notes

- **Classic Bluetooth HID only.** BLE-only keyboards/mice (HOGP) aren't
  handled — that would require a separate BLE GATT client and is a
  reasonable future extension, but most standalone Bluetooth
  keyboards/mice (as opposed to ones that ship paired to a specific BLE
  dongle) use classic Bluetooth HID.
- **One keyboard state, one mouse state.** If you pair more than one
  keyboard, their key state is merged into a single USB keyboard report
  (fine for normal use, but a key held on one device and released on
  "the keyboard" conceptually releases the combined state).
- **No multimedia/consumer keys.** Volume, brightness, etc. keys are not
  forwarded — only the standard keyboard page (letters, numbers, function
  keys, navigation, numpad) and 5-button mouse with wheel.
- **Security**: while pairable, anything can pair with the Pi. The
  pairing window auto-closes after the configured timeout
  (`--pair-timeout`, default 120s, set to `0` for always-on — not
  recommended). Once a legitimate device is paired and trusted, leave the
  window closed.

## Manual run / debugging

```
sudo /opt/hidproxy/venv/bin/hidproxy --log-level DEBUG
```

(`hidproxy` is installed as a console script into the venv by `install.sh`,
so this works from any directory. If you're hacking on the source without
re-running `install.sh`, `cd /opt/hidproxy && sudo venv/bin/python -m
hidproxy.main --log-level DEBUG` also works, since `-m` adds the current
directory to `sys.path`.)

Useful checks:
- `ls /dev/hidg*` — should show `hidg0` and `hidg1` once
  `hidproxy-gadget.service` has run and the Pi is plugged into a host.
- `bluetoothctl devices` / `bluetoothctl paired-devices` — confirm pairing.
- `evtest` (install via `apt`) — inspect raw evdev events from a paired
  device for troubleshooting the keymap.

## Repo layout

```
hidproxy/            Python package (the daemon)
gadget/hid_gadget.sh  configfs USB HID gadget setup, run at boot
systemd/              unit files installed by install.sh
bin/hidproxy-pair     reopen the Bluetooth pairing window
install.sh            installer
```
