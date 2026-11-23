"""Home Assistant automatic routing across reviewed ESPHome and Linux BlueZ paths."""
from functools import partial
from .compatibility import runtime_versions
import re
import sys
import time
import math

from habluetooth import HaBleakClientWrapper, HaScanner
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntryState

from .const import CONF_ADDRESS, CONF_EXPECTED_NAME
from .protocol import READ_UUID, SERVICE_UUID
from .session import TransportAdmissionError

class RouteUnavailable(TransportAdmissionError):
    """No safe, reviewed route is currently available for the bound target."""


def _local_disconnect_contract(hass):
    # The legacy BlueZ3.0.2 disconnect contract is independently reviewed.
    # BlueZ3.1.0 can silently synthesize disconnection on D-Bus loss. Other
    # local implementations need a target-specific release proof, which this
    # adapter does not currently have. None of this restricts ESPHome routes
    # or Home Assistant versions. Never start an uncloseable owned session.
    if sys.platform != "linux" or runtime_versions(hass).get("bleak") != "3.0.2":
        raise RouteUnavailable("local_disconnect_confirmation_unavailable")


def _require_callables(obj, names):
    if not all(callable(getattr(obj, name, None)) for name in names):
        raise RouteUnavailable("required_bluetooth_api_unavailable")


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
                or not callable(scanner.connector.client)
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


def _resolve(hass, data):
    """Validate every path HA may select, without selecting or pinning one."""
    _require_callables(bluetooth, ("async_discovered_service_info", "async_current_scanners",
        "async_scanner_devices_by_address", "async_ble_device_from_address"))
    _require_callables(hass.config_entries, ("async_entries",))
    address = data[CONF_ADDRESS]
    infos = [info for info in bluetooth.async_discovered_service_info(hass, connectable=True)
             if info.name == data[CONF_EXPECTED_NAME]]
    if {info.address.upper() for info in infos} != {address}:
        raise RouteUnavailable()
    if not any(isinstance(info.service_uuids, (list, tuple, set, frozenset))
               and SERVICE_UUID in info.service_uuids
               and type(info.time) in (float, int) and math.isfinite(info.time)
               and 0 <= time.monotonic()-info.time <= 30
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
    capacity = False
    for path in paths:
        scanner = path.scanner
        if (not any(scanner is active for active in registered) or scanner.connectable is not True
                or path.ble_device.address.upper() != address):
            raise RouteUnavailable()
        kind = _kind(path, sources)
        _require_callables(scanner, ("connections_in_progress", "get_allocations"))
        if kind == "linux_bluez":
            _local_disconnect_contract(hass)
        else:
            _require_callables(scanner.connector, ("can_connect",))
        # Pending native attempts may precede proxy allocation reports. The
        # public scanner API gives only a count, so conservatively reject busy paths.
        pending = scanner.connections_in_progress()
        if type(pending) is not int or pending < 0:
            raise RouteUnavailable("required_bluetooth_api_unavailable")
        if pending:
            raise RouteUnavailable()
        allocations = scanner.get_allocations()
        if (allocations is None or type(allocations.slots) is not int
                or type(allocations.free) is not int or allocations.slots <= 0
                or not 0 <= allocations.free <= allocations.slots
                or not isinstance(allocations.allocated, (list, tuple, set, frozenset))
                or not all(isinstance(a, str) and a for a in allocations.allocated)
                or len(allocations.allocated) != allocations.slots - allocations.free
                or len({a.upper() for a in allocations.allocated}) != len(allocations.allocated)):
            raise RouteUnavailable()
        # Never take over a target another HA client already owns.
        if allocations is not None and address in {a.upper() for a in allocations.allocated}:
            raise RouteUnavailable()
        if kind == "linux_bluez":
            capacity |= allocations is not None and allocations.slots > 0 and allocations.free > 0
        else:
            can_connect = scanner.connector.can_connect()
            if type(can_connect) is not bool:
                raise RouteUnavailable("required_bluetooth_api_unavailable")
            capacity |= can_connect and allocations.free > 0
    if not capacity:
        raise RouteUnavailable()
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None or str(getattr(device, "address", "")).upper() != address:
        raise RouteUnavailable()
    return device


def resolve(hass, data):
    """Normalize missing/changed API shapes without exposing exception text."""
    try:
        return _resolve(hass, data)
    except RouteUnavailable:
        raise
    except (AttributeError, KeyError, TypeError, ValueError):
        raise RouteUnavailable("required_bluetooth_api_unavailable") from None


class HATransport:
    """One new HA wrapper per session; HA chooses the available adapter."""

    def __init__(self, hass, data):
        self.hass = hass
        self.data = data
        self.client = HaBleakClientWrapper(resolve(hass, data), timeout=20, pair=False)
        _require_callables(self.client, ("connect", "disconnect", "read_gatt_char"))
        if getattr(self.client, "is_connected", None) is not False:
            raise RouteUnavailable("required_bluetooth_api_unavailable")
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
        elif self._connect_succeeded and was_connected is True:
            # The native ESPHome and legacy BlueZ3.0.2 normal disconnects await
            # actual teardown. Empty/failed/cancelled wrapper calls do not
            # establish that an abandoned attempt was released.
            self._cleanup_confirmed = self.client.is_connected is False
