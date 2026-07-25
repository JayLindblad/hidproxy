"""Per-input-device event loop: reads evdev events from a Bluetooth HID device
node and turns them into USB HID gadget reports."""

from __future__ import annotations

import logging

from evdev import InputDevice, ecodes

from .gadget_writer import GadgetWriter
from .hid_reports import KeyboardReport, MouseReport
from .keymap import BUTTON_BITS

logger = logging.getLogger(__name__)

# Autorepeat (value == 2) is dropped: the host OS applies its own key-repeat
# once it sees the key held down, same as a real USB keyboard.
KEY_UP, KEY_DOWN, KEY_REPEAT = 0, 1, 2


async def bridge_device(
    path: str,
    writer: GadgetWriter,
    keyboard_report: KeyboardReport,
    mouse_report: MouseReport,
) -> None:
    dev = InputDevice(path)
    name = dev.name
    logger.info("bridging %s (%s)", path, name)

    pending_dx = pending_dy = pending_wheel = 0
    try:
        async for event in dev.async_read_loop():
            if event.type == ecodes.EV_KEY:
                if event.value == KEY_REPEAT:
                    continue
                pressed = event.value == KEY_DOWN
                if event.code in BUTTON_BITS:
                    report = mouse_report.button_event(event.code, pressed)
                    if report is not None:
                        writer.write_mouse(report)
                else:
                    report = keyboard_report.key_event(event.code, pressed)
                    if report is not None:
                        writer.write_keyboard(report)

            elif event.type == ecodes.EV_REL:
                if event.code == ecodes.REL_X:
                    pending_dx += event.value
                elif event.code == ecodes.REL_Y:
                    pending_dy += event.value
                elif event.code == ecodes.REL_WHEEL:
                    pending_wheel += event.value

            elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                if pending_dx or pending_dy or pending_wheel:
                    writer.write_mouse(mouse_report.render(pending_dx, pending_dy, pending_wheel))
                    pending_dx = pending_dy = pending_wheel = 0
    except OSError:
        logger.info("device gone: %s (%s)", path, name)
    finally:
        writer.write_keyboard(keyboard_report.release_all())
        writer.write_mouse(mouse_report.release_all())
        try:
            dev.close()
        except OSError:
            pass
