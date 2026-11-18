"""Home Assistant automatic routing across reviewed ESPHome and Linux BlueZ paths."""
from functools import partial
from importlib.metadata import PackageNotFoundError, version
import re
import sys
import time

from habluetooth import HaBleakClientWrapper, HaScanner
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntryState

from .const import CONF_ADDRESS, CONF_EXPECTED_NAME
from .protocol import READ_UUID, SERVICE_UUID

PACKAGES = ("homeassistant", "habluetooth", "bleak", "bleak-esphome", "aioesphomeapi")


class RouteUnavailable(Exception):
    """No safe, reviewed route is currently available for the bound target."""


def runtime_versions():
    result = {}
    for package in PACKAGES:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not_installed"
    return result


def _runtime_supported(kind, versions):
    if versions["homeassistant"] != "2026.11.0" or versions["habluetooth"] != "7.1.2":
        return False
    if kind == "linux_bluez":
        # Bleak3.1 changes bus-loss cleanup semantics; do not infer the same
        # acknowledgement from its normal disconnect return.
        return sys.platform == "linux" and versions["bleak"] == "3.0.2"
    return (versions["bleak"] in ("3.0.2", "3.1.0")
            and versions["bleak-esphome"] == "4.0.0"
            and versions["aioesphomeapi"] == "46.25.0")


def _esphome_backend(client):
    while isinstance(client, partial):
        client = client.func
    return getattr(client, "__module__", "").startswith("bleak_esphome.")


def _kind(path, sources):
    scanner = path.scanner
    details = path.ble_device.details
    if not isinstance(details, dict):
        raise RouteUnavailable()
    remote_source = details.get("source")
    if remote_source:
        if (str(remote_source).upper() != scanner.source.upper()
                or scanner.source.upper() not in sources or not scanner.connector
                or not _esphome_backend(scanner.connector.client)):
            raise RouteUnavailable()
        return "esphome"
    expected_path = re.escape(path.ble_device.address.upper().replace(":", "_"))
    if (scanner.connector is not None
            or not isinstance(scanner, HaScanner)
            or not re.fullmatch(r"/org/bluez/hci[0-9]+/dev_" + expected_path,
                                str(details.get("path", "")))):
        raise RouteUnavailable()
    return "linux_bluez"


def resolve(hass, data):
    """Validate every path HA may select, without selecting or pinning one."""
    address = data[CONF_ADDRESS]
    infos = [info for info in bluetooth.async_discovered_service_info(hass, connectable=True)
             if info.name == data[CONF_EXPECTED_NAME]]
    if {info.address.upper() for info in infos} != {address}:
        raise RouteUnavailable()
    if not any(SERVICE_UUID in info.service_uuids and 0 <= time.monotonic()-info.time <= 30
               for info in infos):
        raise RouteUnavailable()
    registered = bluetooth.async_current_scanners(hass)
    loaded = {entry.entry_id for entry in hass.config_entries.async_entries("esphome")
              if entry.state is ConfigEntryState.LOADED}
    sources = {str(entry.data["source"]).upper()
               for entry in hass.config_entries.async_entries("bluetooth")
               if entry.data.get("source_domain") == "esphome"
               and entry.data.get("source_config_entry_id") in loaded
               and entry.data.get("source")}
    paths = bluetooth.async_scanner_devices_by_address(hass, address, connectable=True)
    if not paths:
        raise RouteUnavailable()
    versions = runtime_versions()
    capacity = False
    for path in paths:
        scanner = path.scanner
        if (not any(scanner is active for active in registered) or not scanner.connectable
                or path.ble_device.address.upper() != address):
            raise RouteUnavailable()
        kind = _kind(path, sources)
        if not _runtime_supported(kind, versions):
            raise RouteUnavailable()
        # Pending native attempts may precede proxy allocation reports. The
        # public scanner API gives only a count, so conservatively reject busy paths.
        if scanner.connections_in_progress():
            raise RouteUnavailable()
        allocations = scanner.get_allocations()
        # Never take over a target another HA client already owns.
        if allocations is not None and address in {a.upper() for a in allocations.allocated}:
            raise RouteUnavailable()
        if kind == "linux_bluez":
            capacity |= allocations is not None and allocations.slots > 0 and allocations.free > 0
        else:
            # Older proxy firmware can report capacity without owned addresses.
            # That snapshot cannot prove this target is free.
            if (allocations is None or allocations.slots <= 0
                    or not 0 <= allocations.free <= allocations.slots
                    or len(allocations.allocated) != allocations.slots - allocations.free):
                raise RouteUnavailable()
            capacity |= scanner.connector.can_connect()
    if not capacity:
        raise RouteUnavailable()
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise RouteUnavailable()
    return device


class HATransport:
    """One new HA wrapper per session; HA chooses the available adapter."""

    def __init__(self, hass, data):
        self.hass = hass
        self.data = data
        self.client = HaBleakClientWrapper(resolve(hass, data), timeout=20, pair=False)
        self._connect_started = False
        self._connect_succeeded = False
        self._cleanup_confirmed = True

    async def connect(self):
        # The wrapper reselects its path before its first await. Revalidate
        # all selectable paths in the same event-loop turn, atomically.
        resolve(self.hass, self.data)
        self._connect_started = True
        self._cleanup_confirmed = False
        await self.client.connect()
        self._connect_succeeded = True

    @property
    def is_connected(self):
        return self.client.is_connected

    @property
    def cleanup_confirmed(self):
        return self._cleanup_confirmed

    def compatible(self):
        service = self.client.services.get_service(SERVICE_UUID)
        characteristic = self.client.services.get_characteristic(READ_UUID)
        return bool(service and characteristic and characteristic in service.characteristics
                    and "read" in characteristic.properties)

    async def read(self):
        return await self.client.read_gatt_char(READ_UUID)

    async def disconnect(self):
        was_connected = self.client.is_connected
        await self.client.disconnect()
        if not self._connect_started:
            self._cleanup_confirmed = True
        elif self._connect_succeeded and was_connected:
            # The allowlisted ESPHome and BlueZ3.0.2 normal disconnects await
            # actual teardown. Empty/failed/cancelled wrapper calls do not
            # establish that an abandoned attempt was released.
            self._cleanup_confirmed = not self.client.is_connected
