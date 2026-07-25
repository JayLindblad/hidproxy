"""Writes HID reports to the /dev/hidgN character devices created by hid_gadget.sh."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class GadgetEndpoint:
    """A single /dev/hidgN node. Reopens transparently if the USB cable is
    unplugged and replugged (the host side detaching invalidates the fd)."""

    def __init__(self, path: str):
        self.path = path
        self._fd: int | None = None

    def _ensure_open(self) -> bool:
        if self._fd is not None:
            return True
        try:
            self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
            logger.info("opened %s", self.path)
            return True
        except OSError as exc:
            logger.debug("waiting for %s: %s", self.path, exc)
            return False

    def write(self, report: bytes) -> None:
        if not self._ensure_open():
            return
        try:
            os.write(self._fd, report)
        except OSError as exc:
            logger.warning("write to %s failed (%s), will reopen", self.path, exc)
            self.close()

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


class GadgetWriter:
    """Owns the keyboard and mouse gadget endpoints."""

    def __init__(self, keyboard_path: str = "/dev/hidg0", mouse_path: str = "/dev/hidg1"):
        self.keyboard = GadgetEndpoint(keyboard_path)
        self.mouse = GadgetEndpoint(mouse_path)

    def write_keyboard(self, report: bytes) -> None:
        self.keyboard.write(report)

    def write_mouse(self, report: bytes) -> None:
        self.mouse.write(report)

    def close(self) -> None:
        self.keyboard.close()
        self.mouse.close()
