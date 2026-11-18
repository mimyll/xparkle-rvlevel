"""Actual reviewed HA wrapper selection with a strict synthetic remote backend."""
import asyncio
from types import SimpleNamespace

import pytest

from test_ha_adapter import adapter, route
from habluetooth import HaBleakClientWrapper
import habluetooth.wrappers as wrappers
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['normal', 'pending_before_dispatch', 'manager_shutdown', 'unregistered_mid_connect'])
async def test_actual_wrapper_with_fake_remote_backend(adapter, monkeypatch, boundary):
    module, bt = adapter
    hass, data = route(module, bt, monkeypatch)
    calls = []
    # Deliberately has no pair/unpair/write/notify/auth/reset methods.
    class StrictBackend:
        __module__ = 'bleak_esphome.backend.client'
        def __init__(self, device, **kwargs):
            assert device.address == data['address']
            assert kwargs['timeout'] == 20
            self.is_connected = False
            self.callback = kwargs['disconnected_callback']
        async def connect(self, pair, **kwargs):
            calls.append(('connect', pair))
            assert pair is False
            await asyncio.sleep(0)
            self.is_connected = True
            if boundary == 'unregistered_mid_connect':
                manager.registered = False
        async def disconnect(self):
            calls.append(('disconnect',))
            self.is_connected = False
        def set_disconnected_callback(self, callback, **kwargs):
            self.callback = callback

    scanner = SimpleNamespace(source='SYNTHETIC_PROXY', adapter_idx=None,
        name='Synthetic proxy', connectable=True, _clients=set(), pending=0,
        connector=SimpleNamespace(client=StrictBackend, can_connect=lambda: True),
        get_allocations=lambda: SimpleNamespace(slots=3, free=3, allocated=[]),
        connection_failures=lambda address: 0)
    scanner.connections_in_progress = lambda: scanner.pending
    def add_connecting(address):
        assert address == data['address']
        scanner.pending += 1
    def finished_connecting(address, connected):
        assert address == data['address']
        scanner.pending -= 1
    scanner._add_connecting = add_connecting
    scanner._finished_connecting = finished_connecting
    device = BLEDevice(data['address'], data['expected_name'], {'source':scanner.source})
    path = SimpleNamespace(scanner=scanner, ble_device=device,
        advertisement=SimpleNamespace(rssi=-50))
    manager = SimpleNamespace(shutdown=False, registered=True,
        async_scanner_devices_by_address=lambda address, connectable: [path],
        async_current_scanners=lambda: [scanner])
    manager.async_scanner_by_source = lambda source: scanner if manager.registered else None
    monkeypatch.setattr(wrappers, 'get_manager', lambda: manager)
    monkeypatch.setattr(bt, 'async_scanner_devices_by_address', lambda *a, **k: [path])
    monkeypatch.setattr(bt, 'async_current_scanners', lambda *a, **k: [scanner])
    monkeypatch.setattr(bt, 'async_ble_device_from_address', lambda *a, **k: device)
    # No replacement of HaBleakClientWrapper or its backend-selection/connect/disconnect code.
    assert module.HaBleakClientWrapper is HaBleakClientWrapper
    transport = module.HATransport(hass, data)
    if boundary == 'pending_before_dispatch':
        scanner.pending = 1
    elif boundary == 'manager_shutdown':
        manager.shutdown = True
    if boundary == 'normal':
        await transport.connect()
        assert transport.is_connected and calls == [('connect', False)]
        await transport.disconnect()
        assert not transport.is_connected and transport.cleanup_confirmed
        assert calls == [('connect', False), ('disconnect',)]
    elif boundary == 'unregistered_mid_connect':
        with pytest.raises(BleakError):
            await transport.connect()
        assert calls == [('connect', False), ('disconnect',)]
        assert not transport.is_connected and not transport.cleanup_confirmed
    else:
        with pytest.raises(module.RouteUnavailable if boundary == 'pending_before_dispatch' else BleakError):
            await transport.connect()
        assert calls == []
        assert transport.cleanup_confirmed is (boundary == 'pending_before_dispatch')
    assert not scanner._clients
