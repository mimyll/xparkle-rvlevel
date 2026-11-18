"""Actual HA/Bleak path shapes, synthetic adapters and no radio activity."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from habluetooth import BluetoothScannerDevice
from habluetooth.scanner_bleak import HaScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from test_ha_adapter import adapter, route


def local_path(m, data):
    # Real HA local scanner subtype and native path/device containers,
    # with only slot information and radio construction faked.
    class SyntheticLocal(HaScanner):
        def connections_in_progress(self):
            return 0
        def get_allocations(self):
            return SimpleNamespace(slots=3,free=3,allocated=[])
    scanner = SyntheticLocal.__new__(SyntheticLocal)
    scanner.source = "00:00:00:00:00:02"
    scanner.adapter = "hci0"
    scanner.connectable = True
    scanner.connector = None
    device = BLEDevice(data["address"], data["expected_name"],
                       {"path":"/org/bluez/hci0/dev_"+data["address"].replace(":","_"),"props":{}})
    advertisement = AdvertisementData(local_name=data["expected_name"],manufacturer_data={},
        service_data={},service_uuids=[m.SERVICE_UUID],tx_power=None,rssi=-50,platform_data=())
    return BluetoothScannerDevice(scanner, device, advertisement)


@pytest.mark.parametrize("mixed", [False,True])
def test_native_local_shape_and_mixed_routes_need_no_esphome_for_local_only(adapter, monkeypatch, mixed):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    remote = bt.async_scanner_devices_by_address(hass, data["address"])[0]
    local = local_path(m, data)
    paths = [local,remote] if mixed else [local]
    monkeypatch.setattr(m.sys,"platform","linux")
    monkeypatch.setattr(bt,"async_current_scanners",lambda *a:[p.scanner for p in paths])
    monkeypatch.setattr(bt,"async_scanner_devices_by_address",lambda *a,**k:paths)
    if not mixed:
        hass.config_entries.async_entries = lambda *a:[]
    assert m.resolve(hass,data) == "synthetic_device"


def test_newer_unreviewed_local_bluez_is_rejected_even_with_supported_remote(adapter, monkeypatch):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    remote = bt.async_scanner_devices_by_address(hass,data["address"])[0]
    paths = [remote,local_path(m,data)]
    monkeypatch.setattr(m.sys,"platform","linux")
    versions = m.runtime_versions()
    versions["bleak"] = "3.1.0"
    monkeypatch.setattr(m,"runtime_versions",lambda:versions)
    monkeypatch.setattr(bt,"async_current_scanners",lambda *a:[p.scanner for p in paths])
    monkeypatch.setattr(bt,"async_scanner_devices_by_address",lambda *a,**k:paths)
    with pytest.raises(m.RouteUnavailable): m.resolve(hass,data)


@pytest.mark.parametrize("case", ["passive","missing_device","busy_target","removed_source","wrong_address"])
def test_route_capability_ownership_and_identity_fail_closed(adapter, monkeypatch, case):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    path = bt.async_scanner_devices_by_address(hass,data["address"])[0]
    if case == "passive": path.scanner.connectable = False
    if case == "missing_device": monkeypatch.setattr(bt,"async_ble_device_from_address",lambda *a,**k:None)
    if case == "busy_target": path.scanner.get_allocations = lambda:SimpleNamespace(slots=3,free=2,allocated=[data["address"]])
    if case == "removed_source": monkeypatch.setattr(bt,"async_current_scanners",lambda *a:[])
    if case == "wrong_address":
        info = bt.async_discovered_service_info(hass)[0]
        other = SimpleNamespace(**{**info.__dict__,"address":"00:00:00:00:00:03"})
        monkeypatch.setattr(bt,"async_discovered_service_info",lambda *a,**k:[info,other])
    with pytest.raises(m.RouteUnavailable): m.resolve(hass,data)


async def test_unsupported_route_appearing_before_connect_prevents_any_native_dispatch(adapter,monkeypatch):
    m,bt = adapter
    hass,data = route(m,bt,monkeypatch)
    client = SimpleNamespace(connect=AsyncMock(),is_connected=False)
    monkeypatch.setattr(m,"HaBleakClientWrapper",lambda *a,**k:client)
    transport = m.HATransport(hass,data)
    path = bt.async_scanner_devices_by_address(hass,data["address"])[0]
    path.scanner.connector.client = type("Unknown",(),{"__module__":"unreviewed.backend"})
    with pytest.raises(m.RouteUnavailable): await transport.connect()
    client.connect.assert_not_called()
    assert transport.cleanup_confirmed


@pytest.mark.parametrize("package", ["homeassistant","habluetooth","bleak-esphome","aioesphomeapi"])
def test_unreviewed_runtime_versions_do_not_dispatch(adapter,monkeypatch,package):
    m,bt=adapter
    hass,data=route(m,bt,monkeypatch)
    versions=m.runtime_versions()
    versions[package]="999.0.0"
    monkeypatch.setattr(m,"runtime_versions",lambda:versions)
    with pytest.raises(m.RouteUnavailable):m.resolve(hass,data)


@pytest.mark.parametrize("case", ["pending", "missing", "unlisted_owner", "invalid_free"])
def test_pending_or_incomplete_proxy_ownership_refuses_dispatch(adapter, monkeypatch, case):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    scanner = bt.async_scanner_devices_by_address(hass, data["address"])[0].scanner
    if case == "pending":
        scanner.connections_in_progress = lambda: 1
    elif case == "missing":
        scanner.get_allocations = lambda: None
    elif case == "unlisted_owner":
        scanner.get_allocations = lambda: SimpleNamespace(slots=3, free=2, allocated=[])
    else:
        scanner.get_allocations = lambda: SimpleNamespace(slots=3, free=4, allocated=[])
    with pytest.raises(m.RouteUnavailable):
        m.resolve(hass, data)
