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

## Fast boot (using it as a BIOS-screen keyboard/mouse)

If you want the keyboard/mouse usable before the target computer even
finishes POST (e.g. to hit a BIOS/boot-menu key), there are three separate
time budgets stacked on top of each other, and only the first is really
ours to shrink:

1. **The Pi's own boot time**, up to the point `hidproxy.service` starts.
2. **Bluetooth radio bring-up** — the BT firmware upload over UART to the
   chip and `bluetoothd` init. This is a largely fixed cost (roughly 1-3s)
   independent of anything hidproxy does.
3. **The keyboard's own reconnect behavior.** For classic Bluetooth HID,
   *the keyboard* is what initiates reconnection to a previously-trusted
   host, usually on a keypress — its scan/retry timing is entirely up to
   the keyboard's own firmware, not something the Pi can speed up. In
   practice this means pressing a key on the keyboard right as the target
   machine powers on works better than expecting it to "already be
   listening" the instant Pi boot finishes.

What `install.sh` already does to help with (1):
- Adds `disable_splash=1` and `boot_delay=0` to `config.txt` to skip the
  rainbow splash render and any artificial power-on delay.
- `hidproxy.service` is bound to `bluetooth.target` (not the broader
  `multi-user.target`) so it starts the moment Bluetooth itself is up,
  rather than waiting on unrelated default services.
- `hidproxy.service` runs with `Nice=-10` and a realtime IO scheduling
  class — on a single-core Pi Zero W, contention from other boot-time
  services for the one CPU core is a real (if modest) source of delay.

Beyond that, the biggest remaining lever is general Pi boot-time tuning,
which is workload-specific enough that guessing isn't useful — profile it:

```
systemd-analyze blame        # which units take the longest
systemd-analyze critical-path # what's actually on the critical path to boot
```

Common wins if they show up as culprits: a faster/higher-endurance SD card
(SD I/O is very often the dominant boot bottleneck on a Pi), disabling
`dphys-swapfile` (swap) if enabled, disabling unused services pulled in by
your particular OS image (`avahi-daemon`, `triggerhappy`, etc. — check
`systemctl list-unit-files --state=enabled`), and skipping first-boot-only
work (filesystem resize, SSH host key generation) which shouldn't recur
past the very first boot anyway. Be careful about disabling networking
services for this, though — you'll usually still want SSH access to manage
the Pi.

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
- `ls /sys/class/udc` — empty means the `dwc2` controller never registered
  as a gadget-mode USB Device Controller, so `/dev/hidg*` can never appear.
  The most common cause: some stock Raspberry Pi OS images already ship
  `dtoverlay=dwc2,dr_mode=host` in `config.txt` (`/boot/firmware/config.txt`
  on Bookworm), which forces **host** mode and is incompatible with
  gadget mode. `install.sh` rewrites that line to
  `dtoverlay=dwc2,dr_mode=peripheral` — if you edited `config.txt` by hand,
  make sure it says `dr_mode=peripheral`, not `dr_mode=host`, and reboot
  afterwards (the overlay only applies at boot). Also make sure that line
  isn't sitting inside one of `config.txt`'s bracketed conditional sections
  (`[cm4]`, `[cm5]`, `[pi5]`, ...) meant for different hardware - those
  only apply on the matching board. `install.sh` avoids this by always
  appending its own copy under an unconditional trailing `[all]` section
  rather than editing whatever it finds.
- If `dmesg | grep -i usb` shows `dwc_otg` attaching to the controller
  instead of `dwc2`, the overlay isn't being applied at all (see above) -
  the original Pi's vendor `dwc_otg` driver doesn't support gadget/device
  mode, only `dwc2` does.
- Also check `cat /boot/firmware/cmdline.txt` (or `/boot/cmdline.txt`) for
  `g_hid` in a `modules-load=` token. `g_hid` is the older single-function
  USB gadget driver; if it's loaded at boot it claims the Pi's one UDC for
  itself (misconfigured, since it needs module parameters hidproxy doesn't
  set), which is why `/sys/class/udc` stays empty for everyone else,
  including hidproxy's own configfs gadget. `install.sh` strips `g_hid` out
  automatically - if you edited `cmdline.txt` by hand, remove it and reboot.

## Repo layout

```
hidproxy/            Python package (the daemon)
gadget/hid_gadget.sh  configfs USB HID gadget setup, run at boot
systemd/              unit files installed by install.sh
bin/hidproxy-pair     reopen the Bluetooth pairing window
install.sh            installer
```
