"""BlueZ pairing agent + adapter setup.

Registers a NoInputNoOutput agent so classic Bluetooth HID keyboards/mice can
pair without a screen attached to the Pi:
  - Just Works (SSP) pairing is accepted automatically.
  - Legacy PIN-code pairing (older keyboards) falls back to a fixed PIN that
    the user types on the keyboard itself (see README).
Every device that completes pairing is marked Trusted so it reconnects on its
own afterwards without repeating the pairing dance.
"""

from __future__ import annotations

import logging

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method
from dbus_next.constants import PropertyAccess

logger = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
AGENT_PATH = "/hidproxy/agent"
AGENT_CAPABILITY = "NoInputNoOutput"
LEGACY_PIN = "0000"


class Agent(ServiceInterface):
    def __init__(self, bus: MessageBus):
        super().__init__("org.bluez.Agent1")
        self._bus = bus

    async def _trust(self, device_path: str) -> None:
        try:
            introspection = await self._bus.introspect(BLUEZ_SERVICE, device_path)
            proxy = self._bus.get_proxy_object(BLUEZ_SERVICE, device_path, introspection)
            props = proxy.get_interface("org.freedesktop.DBus.Properties")
            await props.call_set("org.bluez.Device1", "Trusted", Variant("b", True))
            logger.info("trusted %s", device_path)
        except Exception:
            logger.exception("failed to set Trusted on %s", device_path)

    @method()
    def Release(self):
        logger.debug("agent released")

    @method()
    async def RequestPinCode(self, device: "o") -> "s":  # noqa: F821
        logger.info("legacy PIN requested for %s, sending default %s", device, LEGACY_PIN)
        await self._trust(device)
        return LEGACY_PIN

    @method()
    async def RequestPasskey(self, device: "o") -> "u":  # noqa: F821
        logger.info("passkey requested for %s, sending 000000", device)
        await self._trust(device)
        return 0

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821
        logger.info("PIN code for %s: %s", device, pincode)

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: F821
        logger.info("passkey for %s: %06d", device, passkey)

    @method()
    async def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821
        logger.info("auto-confirming pairing for %s (passkey %06d)", device, passkey)
        await self._trust(device)

    @method()
    async def RequestAuthorization(self, device: "o"):  # noqa: F821
        logger.info("auto-authorizing pairing for %s", device)
        await self._trust(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821
        logger.info("auto-authorizing service %s for %s", uuid, device)

    @method()
    def Cancel(self):
        logger.info("agent request cancelled")


async def _find_adapter_path(bus: MessageBus) -> str:
    introspection = await bus.introspect(BLUEZ_SERVICE, "/")
    proxy = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
    om = proxy.get_interface("org.freedesktop.DBus.ObjectManager")
    objects = await om.call_get_managed_objects()
    for path, interfaces in objects.items():
        if "org.bluez.Adapter1" in interfaces:
            return path
    raise RuntimeError("no Bluetooth adapter found (is a BT controller present and up?)")


class BluetoothManager:
    """Owns the D-Bus connection, the pairing agent, and adapter state."""

    def __init__(self, alias: str = "HID Proxy", discoverable_timeout: int = 0):
        self._alias = alias
        self._discoverable_timeout = discoverable_timeout
        self.bus: MessageBus | None = None
        self._adapter_path: str | None = None
        self._adapter_props = None

    async def start(self) -> None:
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._adapter_path = await _find_adapter_path(self.bus)

        introspection = await self.bus.introspect(BLUEZ_SERVICE, self._adapter_path)
        adapter_obj = self.bus.get_proxy_object(BLUEZ_SERVICE, self._adapter_path, introspection)
        self._adapter_props = adapter_obj.get_interface("org.freedesktop.DBus.Properties")

        agent = Agent(self.bus)
        self.bus.export(AGENT_PATH, agent)

        root_introspection = await self.bus.introspect(BLUEZ_SERVICE, "/org/bluez")
        root_obj = self.bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez", root_introspection)
        agent_manager = root_obj.get_interface("org.bluez.AgentManager1")
        await agent_manager.call_register_agent(AGENT_PATH, AGENT_CAPABILITY)
        await agent_manager.call_request_default_agent(AGENT_PATH)
        logger.info("registered pairing agent (%s) on adapter %s", AGENT_CAPABILITY, self._adapter_path)

        await self._adapter_props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))
        await self._adapter_props.call_set("org.bluez.Adapter1", "Alias", Variant("s", self._alias))
        await self.set_pairable(True)

    async def set_pairable(self, enabled: bool) -> None:
        await self._adapter_props.call_set("org.bluez.Adapter1", "Pairable", Variant("b", enabled))
        await self._adapter_props.call_set("org.bluez.Adapter1", "Discoverable", Variant("b", enabled))
        await self._adapter_props.call_set(
            "org.bluez.Adapter1", "DiscoverableTimeout", Variant("u", self._discoverable_timeout)
        )
        logger.info("adapter pairable/discoverable = %s", enabled)
