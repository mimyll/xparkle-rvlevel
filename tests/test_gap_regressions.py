"""Failure-oriented regressions from the independent TEA gap plan; fake radio only."""
import asyncio
from dataclasses import replace
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from homeassistant.exceptions import HomeAssistantError
from test_session import FakeTransport, FAST, Clock, until
from test_ha_adapter import adapter, route, make_entry
from custom_components.xparkle_rvlevel.session import Session
from custom_components.xparkle_rvlevel.switch import MeasurementSwitch


async def test_expired_switch_start_reports_failure_without_reconnect():
    transport=FakeTransport();clock=Clock();entry=make_entry()
    entry.runtime_data=Session(lambda:transport,limits=FAST,clock=clock)
    switch=MeasurementSwitch(entry,'measurement')
    await switch.async_turn_on();await until(lambda:entry.runtime_data.read_count)
    clock.value=600
    assert switch.is_on and entry.runtime_data.deadline==600
    try:
        with pytest.raises(HomeAssistantError) as error:
            await switch.async_turn_on()
        assert error.value.translation_key=='session_inactive'
    finally:
        await entry.runtime_data.stop()
    assert not switch.is_on and transport.calls.count('connect')==1
    assert entry.runtime_data.deadline==600
    await switch.async_turn_on();await until(lambda:entry.runtime_data.read_count)
    assert entry.runtime_data.deadline==1200 and transport.calls.count('connect')==2
    await switch.async_turn_off()


async def test_connect_deadline_cancels_and_disconnects_without_retry():
    transport=FakeTransport();transport.connect_block=asyncio.Event()
    session=Session(lambda:transport,limits=replace(FAST,connect=0.01))
    await session.start();await until(lambda:session.safe)
    assert session.reason=='operation_timeout' and session.read_count==0
    assert transport.calls==['connect','disconnect'] and session.pending_operations==0


@pytest.mark.parametrize('failure',[RuntimeError('PRIVATE_READ_ERROR'),PermissionError('PRIVATE_SECURITY_ERROR')])
async def test_failed_read_preserves_cached_pair_and_closes_without_fallback(failure):
    class ReadFailure(FakeTransport):
        async def read(self):
            self.calls.append('read');raise failure
    good,bad=FakeTransport(),ReadFailure();transports=iter([good,bad])
    session=Session(lambda:next(transports),limits=FAST)
    await session.refresh_battery();await until(lambda:session.safe)
    pair=(session.battery,session.battery_received_at)
    await session.refresh_battery();await until(lambda:session.safe)
    assert (session.battery,session.battery_received_at)==pair
    assert session.reason=='connection_or_read_error' and session.read_count==0
    assert bad.calls==['connect','read','disconnect'] and not session.fresh


async def test_measurement_switch_busy_during_battery_refresh_does_not_queue():
    transport=FakeTransport();transport.read_block=asyncio.Event();entry=make_entry()
    entry.runtime_data=Session(lambda:transport,limits=FAST)
    switch=MeasurementSwitch(entry,'measurement')
    await entry.runtime_data.refresh_battery();await until(lambda:'read' in transport.calls)
    with pytest.raises(HomeAssistantError) as error:await switch.async_turn_on()
    assert error.value.translation_key=='cleanup_pending'
    transport.read_block.set();await until(lambda:entry.runtime_data.safe)
    await asyncio.sleep(0)
    assert transport.calls==['connect','read','disconnect'] and not switch.is_on


@pytest.mark.parametrize('poll',[1,10])
def test_manual_poll_endpoints_are_accepted(poll):
    from custom_components.xparkle_rvlevel.config_flow import OPTIONS_SCHEMA
    assert OPTIONS_SCHEMA({'battery_refresh_hours':24,'measurement_interval_seconds':poll})['measurement_interval_seconds']==poll


@pytest.mark.parametrize('case',['valid','wrong_service','no_read','wrong_member'])
async def test_literal_read_uuid_and_gatt_metadata_gate(adapter,monkeypatch,case):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch)
    # Independent literal oracle, not a comparison against the same constant.
    assert m.READ_UUID=='0000fff2-0000-1000-8000-00805f9b34fb'
    assert m.SERVICE_UUID=='0000fff0-0000-1000-8000-00805f9b34fb'
    char=SimpleNamespace(properties=[] if case=='no_read' else ['read'])
    service=SimpleNamespace(characteristics=[] if case=='wrong_member' else [char])
    services=SimpleNamespace(get_service=lambda uuid: None if case=='wrong_service' else service,
                             get_characteristic=lambda uuid:char)
    client=SimpleNamespace(services=services,read_gatt_char=AsyncMock(return_value=b'payload'))
    monkeypatch.setattr(m,'HaBleakClientWrapper',lambda *a,**k:client)
    transport=m.HATransport(hass,data)
    assert transport.compatible() is (case=='valid')
    if case=='valid':
        assert await transport.read()==b'payload'
        client.read_gatt_char.assert_awaited_once_with('0000fff2-0000-1000-8000-00805f9b34fb')
    # Session admission/compatible-before-read is exercised by the engine error test.


async def test_diagnostics_exact_allowlist_omits_proxy_and_transport_error(adapter,monkeypatch):
    diag=importlib.import_module('custom_components.xparkle_rvlevel.diagnostics')
    class Broken(FakeTransport):
        async def read(self):raise PermissionError('PRIVATE_AUTH_ERROR')
    entry=make_entry();entry.data.update(address='PRIVATE_TARGET',expected_name='PRIVATE_NAME',proxy='PRIVATE_PROXY')
    entry.runtime_data=Session(lambda:Broken(),limits=FAST)
    await entry.runtime_data.start();await until(lambda:entry.runtime_data.safe)
    result=await diag.async_get_config_entry_diagnostics(None,entry)
    assert set(result)=={'runtime_versions','adapter_selection','session_status','stop_reason','requested','mode','connected','owned_operations_pending','session_task_pending','cleanup_confirmed','read_count','connection_attempts','auto_stop_seconds','poll_interval_seconds','battery_refresh_hours','battery_last_received','last_received','sensor_sample_age','physical_direction_mapping','cadence','fresh_timeout_seconds','read_duration_seconds','timing_sample_limit','sample_interval_seconds','speed_test_report'}
    assert 'PRIVATE' not in json.dumps(result)
    assert result['sensor_sample_age']=='unknown' and result['stop_reason']=='connection_or_read_error'


def test_display_name_change_preserves_function_and_device_identity():
    entry=make_entry();entry.runtime_data=Session(lambda:FakeTransport(),limits=FAST)
    before=MeasurementSwitch(entry,'measurement');entry.title='Renamed display';entry.data['expected_name']='RVLevel-9999'
    after=MeasurementSwitch(entry,'measurement')
    assert after.unique_id==before.unique_id
    assert after.device_info['identifiers']==before.device_info['identifiers']
