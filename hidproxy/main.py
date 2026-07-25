"""Entry point: bring up the Bluetooth pairing agent, then bridge every
connected/connecting Bluetooth keyboard and mouse to the USB HID gadget."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from .bluetooth_agent import BluetoothManager
from .device_manager import DeviceManager
from .gadget_writer import GadgetWriter

logger = logging.getLogger("hidproxy")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keyboard-device", default="/dev/hidg0", help="USB HID gadget node for the keyboard"
    )
    parser.add_argument(
        "--mouse-device", default="/dev/hidg1", help="USB HID gadget node for the mouse"
    )
    parser.add_argument(
        "--pair-timeout",
        type=int,
        default=120,
        help="seconds the adapter stays discoverable/pairable at startup (0 = forever)",
    )
    parser.add_argument(
        "--alias", default="HID Proxy", help="Bluetooth device name shown to devices scanning for it"
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    writer = GadgetWriter(args.keyboard_device, args.mouse_device)
    bt = BluetoothManager(alias=args.alias, discoverable_timeout=args.pair_timeout)
    devices = DeviceManager(writer)

    await bt.start()
    await devices.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("hidproxy running - waiting for Bluetooth keyboard/mouse")
    await stop_event.wait()

    logger.info("shutting down")
    devices.stop()
    writer.close()


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
