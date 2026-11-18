"""Raw coherence: raw coherence, timing ownership and admin-only finite test."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from math import asin, degrees
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from homeassistant.core import HomeAssistant, Context
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized, ServiceValidationError
import voluptuous as vol
from custom_components.xparkle_rvlevel.config_flow import OPTIONS_SCHEMA
from custom_components.xparkle_rvlevel.session import Session, SPEED_STAGES
from custom_components.xparkle_rvlevel.sensor import LevellingSensor
from custom_components.xparkle_rvlevel.protocol import Measurement
from test_ha_adapter import make_entry, adapter
from test_session import FakeTransport, Clock, FAST, until

BASE = {'battery_refresh_hours':24,'measurement_interval_seconds':2}
GEOM = {'vehicle_width_cm':200,'vehicle_length_cm':500,'mount_position':'right','directions_confirmed':True}


@pytest.mark.parametrize('interval',[0.1,0.25,0.5,1,2,10])
def test_fractional_interval_and_existing_integer_options(interval):
    result=OPTIONS_SCHEMA({**BASE,'measurement_interval_seconds':interval})
    assert result['measurement_interval_seconds']==interval
    assert result['level_tolerance_cm']==0.25 and result['vehicle_type']=='caravan'


@pytest.mark.parametrize('field,value',[(field,value) for field in ('measurement_interval_seconds','level_tolerance_cm') for value in (True,False,float('nan'),float('inf'),-1,'0.5',None,10**1000)]+[('measurement_interval_seconds',0.099),('measurement_interval_seconds',10.01),('level_tolerance_cm',0.049),('level_tolerance_cm',5.01),('vehicle_type','bus')])
def test_invalid_speed_or_tolerance_is_not_coerced(field,value):
    with pytest.raises(vol.Invalid):OPTIONS_SCHEMA({**BASE,field:value})


@pytest.mark.parametrize('tolerance,gap,expected',[(.25,2.5,True),(.25,2.5001,False),(.5,5,True),(.5,5.0001,False),(0.05,0,True)])
@pytest.mark.parametrize('uphill,left_tilt',[(False,False),(True,True)])
def test_raw_atomic_level_sample_and_signed_tolerance(tolerance,gap,expected,uphill,left_tilt):
    entry=make_entry();entry.options.update({**GEOM,'level_tolerance_cm':tolerance})
    now=datetime.now(timezone.utc)
    longitudinal = 0 if gap == 0 else 2
    entry.runtime_data=SimpleNamespace(fresh=True,mode='manual',status='measuring',
        measurement=Measurement(degrees(asin(longitudinal/5000)),degrees(asin(gap/2000)),uphill,left_tilt,100),
        received_at=now,expires_at=now+timedelta(seconds=600),_sample_sequence=7,
        identifier='synthetic',fresh_timeout=1.5,limits=SimpleNamespace(poll_interval=.5))
    sensor=LevellingSensor(entry,'levelling_status');a=sensor.extra_state_attributes
    assert a['sequence']==7 and a['received_at']==now.isoformat()
    assert a['within_tolerance'] is expected
    assert abs(a['transverse_mm'])==pytest.approx(gap)
    assert abs(a['longitudinal_mm'])==pytest.approx(longitudinal)
    assert a['session_id']=='synthetic'
    for mode,fresh in [('battery_refresh',True),('speed_test',True),('manual',False)]:
        entry.runtime_data.mode=mode;entry.runtime_data.fresh=fresh
        unknown=sensor.extra_state_attributes
        assert unknown['within_tolerance'] is None and unknown['transverse_mm'] is None


async def test_start_to_start_spacing_slow_reads_no_overlap_or_deadline_renewal():
    class Slow(FakeTransport):
        active=0;peak=0
        async def read(self):
            self.active+=1;self.peak=max(self.active,self.peak)
            try:
                result=await super().read();await asyncio.sleep(.025);return result
            finally:self.active-=1
    transport=Slow();session=Session(lambda:transport,limits=replace(FAST,poll_interval=.02))
    await session.start();deadline=session.deadline
    await until(lambda:session.read_count>=4);await session.stop()
    assert transport.peak==1 and session.deadline==deadline
    assert all(b-a>=.04 for a,b in zip(transport.read_times,transport.read_times[1:]))
    assert session.safe and len(session.read_durations)<=256


async def test_fixed_speed_plan_one_connection_32_reads_and_confirmed_cleanup():
    clock=Clock()
    class SlowClock(FakeTransport):
        async def read(self):
            result=await super().read();clock.value+=1;return result
    transport=SlowClock();session=Session(lambda:transport,limits=FAST,clock=clock)
    report=await session.test_update_speed()
    assert SPEED_STAGES==(1,.5,.25,.1)
    assert report['complete'] and report['cleanup_confirmed']
    assert transport.calls.count('connect')==transport.calls.count('disconnect')==1
    assert report['completed_reads']==transport.calls.count('read')==32
    assert [s['interval_seconds'] for s in report['stages']]==list(SPEED_STAGES)
    assert [s['completed_reads'] for s in report['stages']]==[8]*4
    assert all(len(s['start_spacing_seconds'])==7 for s in report['stages'])
    assert session.safe and not session.fresh and not session.renew()
    assert set(transport.calls)=={'connect','read','disconnect'}
    assert 'physical_or_internal' in report['measures']


async def test_speed_deadline_includes_connect_and_does_not_dispatch_late_read():
    clock=Clock()
    class Late(FakeTransport):
        async def connect(self):await super().connect();clock.value=40
    transport=Late();session=Session(lambda:transport,limits=FAST,clock=clock)
    report=await session.test_update_speed()
    assert report['completed_reads']==0 and not report['complete']
    assert transport.calls==['connect','disconnect'] and session.safe
    assert report['stop_reason']=='speed_test_timeout'


async def test_rejected_diagnostic_does_not_stop_manual_owner():
    transport=FakeTransport();session=Session(lambda:transport,limits=FAST)
    await session.start();await until(lambda:session.read_count>=1)
    assert await session.test_update_speed() is None
    assert session.requested and session.mode=='manual'
    await session.stop();assert session.safe


@pytest.mark.parametrize('phase',['connect','read'])
async def test_speed_caller_cancellation_settles_owned_run(phase):
    transport=FakeTransport();setattr(transport,phase+'_block',asyncio.Event())
    session=Session(lambda:transport,limits=FAST)
    caller=asyncio.create_task(session.test_update_speed())
    await until(lambda:phase in transport.calls)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):await caller
    await until(lambda:session.safe)
    assert transport.calls.count('connect')==1 and not session.requested


async def test_native_admin_service_strict_inputs_and_no_admission_before_authority(tmp_path):
    from custom_components.xparkle_rvlevel.speed_test import register_speed_test
    hass=HomeAssistant(str(tmp_path))
    user=SimpleNamespace(is_admin=False)
    hass.auth=SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    session=SimpleNamespace(test_update_speed=AsyncMock(return_value={'complete':True}))
    entry=SimpleNamespace(domain='xparkle_rvlevel',disabled_by=None,state=ConfigEntryState.LOADED,runtime_data=session)
    hass.config_entries=SimpleNamespace(async_get_entry=lambda key:entry if key=='synthetic' else None)
    register_speed_test(hass)
    async def call(data,uid='synthetic_admin'):
        return await hass.services.async_call('xparkle_rvlevel','test_update_speed',data,
            blocking=True,return_response=True,context=Context(user_id=uid))
    with pytest.raises(Unauthorized):await call({'entry_id':'synthetic'})
    user.is_admin=True
    hass.auth.async_get_user.return_value=None
    with pytest.raises(Unauthorized):await call({'entry_id':'synthetic'})
    hass.auth.async_get_user.return_value=user
    with pytest.raises(ServiceValidationError):await call({'entry_id':'synthetic'},None)
    with pytest.raises((vol.Invalid,ValueError)):await call({'entry_id':'synthetic','interval':0.01})
    with pytest.raises(ServiceValidationError):await call({'entry_id':'unknown'})
    entry.disabled_by='user'
    with pytest.raises(ServiceValidationError):await call({'entry_id':'synthetic'})
    session.test_update_speed.assert_not_awaited()
    entry.disabled_by=None
    assert await call({'entry_id':'synthetic'})=={'complete':True}
    session.test_update_speed.assert_awaited_once()


async def test_static_registration_is_one_public_file_and_calibration_absent():
    from custom_components.xparkle_rvlevel import async_setup
    hass=SimpleNamespace(http=SimpleNamespace(async_register_static_paths=AsyncMock(),register_view=Mock()),
        services=SimpleNamespace(async_register=lambda *a,**k:None))
    assert await async_setup(hass,{})
    registered=hass.http.async_register_static_paths.await_args.args[0]
    assert len(registered)==1 and Path(registered[0].path).is_file()
    assert registered[0].url_path=='/xparkle_rvlevel/0.5.0/xparkle-card.js'
    component=Path(__file__).parents[1]/'custom_components/xparkle_rvlevel'
    assert (component/'brand/icon.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert not (component/'calibration.py').exists()
    view=hass.http.register_view.call_args.args[0]
    assert view.url=='/xparkle_rvlevel/xparkle-card.js' and not view.requires_auth


async def test_native_tolerance_persists_without_reload_or_connection(adapter,monkeypatch,tmp_path):
    import importlib
    from test_native_lifecycle import native_entry,native_manager
    from custom_components.xparkle_rvlevel.number import ToleranceNumber
    from custom_components.xparkle_rvlevel.select import VehicleSelect
    integration=importlib.import_module('custom_components.xparkle_rvlevel')
    hass=HomeAssistant(str(tmp_path));manager,add=native_manager(hass,integration,monkeypatch)
    transport=FakeTransport();monkeypatch.setattr(adapter[0],'HATransport',lambda *a:transport)
    monkeypatch.setattr(manager,'async_reload',AsyncMock())
    entry=native_entry('synthetic_ui');add(entry)
    await integration.async_setup_entry(hass,entry)
    number=ToleranceNumber(entry);number.hass=hass
    await number.async_set_native_value(.5);await hass.async_block_till_done()
    assert entry.options['level_tolerance_cm']==.5
    assert number.native_value==.5 and entry.runtime_data.safe
    vehicle=VehicleSelect(entry);vehicle.hass=hass
    await vehicle.async_select_option('tandem');await hass.async_block_till_done()
    assert vehicle.current_option=='tandem' and entry.options['level_tolerance_cm']==.5
    manager.async_reload.assert_not_awaited();assert transport.calls==[]
    await integration.async_unload_entry(hass,entry)


async def test_actual_native_static_route_serves_only_exact_public_file(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    from homeassistant.components.http.server import HomeAssistantHTTP
    from homeassistant.components.http.cors import KEY_ALLOW_CONFIGURED_CORS
    from custom_components.xparkle_rvlevel import async_setup
    hass=HomeAssistant(str(tmp_path))
    http=HomeAssistantHTTP(hass,None,None,None,['127.0.0.1'],0,[],'modern')
    http.app[KEY_ALLOW_CONFIGURED_CORS]=lambda route:None
    hass.http=http
    await async_setup(hass,{})
    client=TestClient(TestServer(http.app,host='127.0.0.1'))
    try:
        await client.start_server()
        response=await client.get('/xparkle_rvlevel/0.5.0/xparkle-card.js')
        expected=Path(__file__).parents[1]/'custom_components/xparkle_rvlevel/frontend/xparkle-card.js'
        assert response.status==200 and await response.read()==expected.read_bytes()
        for method in ('get','head'):
            response=await getattr(client,method)('/xparkle_rvlevel/xparkle-card.js')
            assert response.status==200 and response.headers['Cache-Control']=='no-store'
            if method=='get':assert await response.read()==expected.read_bytes()
        response=await client.get('/xparkle_rvlevel/xparkle-card.js?file=manifest.json')
        assert response.status==200 and await response.read()==expected.read_bytes()
        for path in ('/xparkle_rvlevel/','/xparkle_rvlevel/manifest.json','/xparkle_rvlevel/xparkle-card.js/../manifest.json'):
            assert (await client.get(path)).status==404
        for path in ('/xparkle_rvlevel/0.5.0/','/xparkle_rvlevel/0.5.0/manifest.json',
                     '/xparkle_rvlevel/0.5.0/xparkle-card.js/../manifest.json'):
            response=await client.get(path)
            assert response.status==404
    finally:
        await client.close()
