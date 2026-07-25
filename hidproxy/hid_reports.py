"""Builds boot-protocol HID report bytes matching gadget/hid_gadget.sh's descriptors."""

from __future__ import annotations

from typing import Optional

from .keymap import BUTTON_BITS, KEY_TO_HID, MODIFIER_BITS

MAX_ROLLOVER_KEYS = 6


def _clamp8(value: int) -> int:
    return max(-127, min(127, value)) & 0xFF


class KeyboardReport:
    """Tracks currently-held keys and renders an 8-byte boot keyboard report.

    Report layout: [modifier_bitmask, reserved(0), key1..key6]
    """

    def __init__(self):
        self._modifiers = 0
        self._keys = []  # ordered list of currently-held HID usage IDs

    def key_event(self, code: int, pressed: bool) -> Optional[bytes]:
        if code in MODIFIER_BITS:
            bit = MODIFIER_BITS[code]
            self._modifiers = (self._modifiers | bit) if pressed else (self._modifiers & ~bit)
            return self.render()

        hid_code = KEY_TO_HID.get(code)
        if hid_code is None:
            return None  # unmapped key, e.g. a media/power key we don't support

        if pressed:
            if hid_code not in self._keys:
                self._keys.append(hid_code)
                if len(self._keys) > MAX_ROLLOVER_KEYS:
                    self._keys.pop(0)
        else:
            if hid_code in self._keys:
                self._keys.remove(hid_code)

        return self.render()

    def render(self) -> bytes:
        keys = list(self._keys[:MAX_ROLLOVER_KEYS])
        keys += [0] * (MAX_ROLLOVER_KEYS - len(keys))
        return bytes([self._modifiers, 0, *keys])

    def release_all(self) -> bytes:
        self._modifiers = 0
        self._keys = []
        return self.render()


class MouseReport:
    """Tracks button state and renders a 4-byte boot mouse report.

    Report layout: [buttons, x(int8), y(int8), wheel(int8)]
    """

    def __init__(self):
        self._buttons = 0

    def button_event(self, code: int, pressed: bool) -> Optional[bytes]:
        bit = BUTTON_BITS.get(code)
        if bit is None:
            return None
        self._buttons = (self._buttons | bit) if pressed else (self._buttons & ~bit)
        return self.render(0, 0, 0)

    def render(self, dx: int = 0, dy: int = 0, wheel: int = 0) -> bytes:
        return bytes([self._buttons, _clamp8(dx), _clamp8(dy), _clamp8(wheel)])

    def release_all(self) -> bytes:
        self._buttons = 0
        return self.render()
