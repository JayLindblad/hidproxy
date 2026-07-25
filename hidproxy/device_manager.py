"""Discovers Bluetooth HID input devices (keyboards/mice) as they connect and
disconnect, and runs one bridge_device() task per device node."""

from __future__ import annotations

import asyncio
import logging

import pyudev
from evdev import InputDevice, ecodes

from .gadget_writer import GadgetWriter
from .hid_reports import KeyboardReport, MouseReport
from .proxy import bridge_device

logger = logging.getLogger(__name__)


def _is_bluetooth_event_node(device_node: str) -> bool:
    try:
        dev = InputDevice(device_node)
    except OSError:
        return False
    try:
        return dev.info.bustype == ecodes.BUS_BLUETOOTH
    finally:
        dev.close()


class DeviceManager:
    """Watches udev for input device add/remove and manages bridge tasks."""

    def __init__(self, writer: GadgetWriter):
        self.writer = writer
        self.keyboard_report = KeyboardReport()
        self.mouse_report = MouseReport()
        self._tasks: dict[str, asyncio.Task] = {}
        self._context = pyudev.Context()
        self._observer: pyudev.MonitorObserver | None = None

    def _start_bridge(self, device_node: str) -> None:
        if device_node in self._tasks:
            return
        if not _is_bluetooth_event_node(device_node):
            return
        logger.info("new Bluetooth input device: %s", device_node)
        task = asyncio.ensure_future(
            bridge_device(device_node, self.writer, self.keyboard_report, self.mouse_report)
        )
        self._tasks[device_node] = task
        task.add_done_callback(lambda _t, node=device_node: self._tasks.pop(node, None))

    def _stop_bridge(self, device_node: str) -> None:
        task = self._tasks.pop(device_node, None)
        if task is not None:
            task.cancel()

    def _on_udev_event(self, action: str, device: pyudev.Device) -> None:
        node = device.device_node
        if not node or not node.startswith("/dev/input/event"):
            return
        if action == "add":
            self._start_bridge(node)
        elif action == "remove":
            self._stop_bridge(node)

    async def start(self) -> None:
        for device in self._context.list_devices(subsystem="input"):
            node = device.device_node
            if node and node.startswith("/dev/input/event"):
                self._start_bridge(node)

        loop = asyncio.get_running_loop()
        monitor = pyudev.Monitor.from_netlink(self._context)
        monitor.filter_by(subsystem="input")

        def _callback(device: pyudev.Device) -> None:
            loop.call_soon_threadsafe(self._on_udev_event, device.action, device)

        self._observer = pyudev.MonitorObserver(monitor, callback=_callback, name="hidproxy-udev")
        self._observer.start()
        logger.info("watching for Bluetooth keyboard/mouse hotplug")

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
        for task in list(self._tasks.values()):
            task.cancel()
