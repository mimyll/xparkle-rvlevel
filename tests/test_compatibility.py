"""Capability admission, off-loop metadata and literal cleanup proof; no radio."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from test_ha_adapter import adapter, route, make_entry
from test_adapter_routes import local_path
from test_session import FakeTransport, FAST, until
from custom_components.xparkle_rvlevel.session import Session, TransportAdmissionError
from custom_components.xparkle_rvlevel import compatibility as compat


@pytest.mark.parametrize('ha_version',['2026.11.2','2026.12.0','999.0.0','unavailable'])
def test_new_core_version_does_not_reject_same_actual_remote_capabilities(adapter,monkeypatch,ha_version):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch)
    monkeypatch.setattr(m,'runtime_versions',lambda hass=None:{'homeassistant':ha_version})
    assert m.resolve(hass,data).address==data['address']


@pytest.mark.parametrize('case',['missing_api','noncallable_api','pending_api','allocation_api','connector_api','constructor','passive_shape','pending_shape','can_connect_shape','slots_shape','free_shape','allocated_shape','duplicate_owner','full_proxy','wrong_final_device','future_advertisement','wrong_service','stale_advertisement'])
def test_concrete_missing_or_inconsistent_capabilities_never_construct_native_client(adapter,monkeypatch,case):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch);path=bt.async_scanner_devices_by_address(hass,data['address'])[0];s=path.scanner
    if case=='missing_api':monkeypatch.delattr(bt,'async_current_scanners')
    elif case=='noncallable_api':bt.async_current_scanners=42
    elif case=='pending_api':s.connections_in_progress=None
    elif case=='allocation_api':s.get_allocations=None
    elif case=='connector_api':s.connector.can_connect=None
    elif case=='constructor':s.connector.client=None
    elif case=='passive_shape':s.connectable='true'
    elif case=='pending_shape':s.connections_in_progress=lambda:None
    elif case=='can_connect_shape':s.connector.can_connect=lambda:'true'
    elif case=='slots_shape':s.get_allocations=lambda:SimpleNamespace(slots=True,free=1,allocated=[])
    elif case=='free_shape':s.get_allocations=lambda:SimpleNamespace(slots=3,free=True,allocated=[])
    elif case=='allocated_shape':s.get_allocations=lambda:SimpleNamespace(slots=3,free=3,allocated='')
    elif case=='duplicate_owner':s.get_allocations=lambda:SimpleNamespace(slots=3,free=2,allocated=['other','OTHER'])
    elif case=='full_proxy':s.get_allocations=lambda:SimpleNamespace(slots=1,free=0,allocated=['other'])
    elif case=='wrong_final_device':bt.async_ble_device_from_address=lambda *a,**k:SimpleNamespace(address='00:00:00:00:00:99')
    else:
        info=bt.async_discovered_service_info(hass)[0]
        if case=='future_advertisement':info.time=m.time.monotonic()+100
        elif case=='wrong_service':info.service_uuids=[]
        else:info.time=m.time.monotonic()-31
    wrapper=AsyncMock();monkeypatch.setattr(m,'HaBleakClientWrapper',wrapper)
    with pytest.raises(m.RouteUnavailable):m.HATransport(hass,data)
    wrapper.assert_not_called()


@pytest.mark.parametrize('change',['pending','full','unregistered','backend'])
async def test_final_recheck_retains_every_path_ownership_without_native_dispatch(adapter,monkeypatch,change):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch);path=bt.async_scanner_devices_by_address(hass,data['address'])[0]
    client=SimpleNamespace(connect=AsyncMock(),disconnect=AsyncMock(),read_gatt_char=AsyncMock(),is_connected=False)
    monkeypatch.setattr(m,'HaBleakClientWrapper',lambda *a,**k:client)
    t=m.HATransport(hass,data)
    if change=='pending':path.scanner.connections_in_progress=lambda:1
    elif change=='full':path.scanner.get_allocations=lambda:SimpleNamespace(slots=1,free=0,allocated=['other'])
    elif change=='unregistered':bt.async_current_scanners=lambda *a:[]
    else:path.scanner.connector.client=type('Other',(),{'__module__':'other.backend'})
    with pytest.raises(m.RouteUnavailable):await t.connect()
    client.connect.assert_not_called();assert t.cleanup_confirmed


@pytest.mark.parametrize('version',['3.1.0','3.2.0','unavailable'])
def test_local_route_without_release_confirmation_contract_is_explicit(adapter,monkeypatch,version):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch);p=local_path(m,data)
    monkeypatch.setattr(m.sys,'platform','linux');monkeypatch.setattr(m,'runtime_versions',lambda hass=None:{'bleak':version})
    bt.async_current_scanners=lambda *a:[p.scanner];bt.async_scanner_devices_by_address=lambda *a,**k:[p]
    with pytest.raises(m.RouteUnavailable) as error:m.resolve(hass,data)
    assert error.value.reason=='local_disconnect_confirmation_unavailable'


@pytest.mark.parametrize('after',[None,0,'false'])
async def test_normal_disconnect_needs_literal_false_not_falsy_sentinel(adapter,monkeypatch,after):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch)
    client=SimpleNamespace(connect=AsyncMock(),read_gatt_char=AsyncMock(),is_connected=False)
    async def disconnect():client.is_connected=after
    client.disconnect=disconnect;monkeypatch.setattr(m,'HaBleakClientWrapper',lambda *a,**k:client)
    t=m.HATransport(hass,data);await t.connect();client.is_connected=True;await t.disconnect()
    assert not t.cleanup_confirmed


@pytest.mark.parametrize('value',[None,0,True,'false'])
def test_new_wrapper_requires_detached_literal_false(adapter,monkeypatch,value):
    m,bt=adapter;hass,data=route(m,bt,monkeypatch)
    c=SimpleNamespace(connect=AsyncMock(),disconnect=AsyncMock(),read_gatt_char=AsyncMock(),is_connected=value)
    monkeypatch.setattr(m,'HaBleakClientWrapper',lambda *a,**k:c)
    with pytest.raises(m.RouteUnavailable):m.HATransport(hass,data)
    c.connect.assert_not_called()


async def test_metadata_once_off_loop_and_detached_diagnostics_cache(tmp_path,monkeypatch):
    hass=HomeAssistant(str(tmp_path));loop_thread=threading.get_ident();calls=[]
    def version(package):
        assert threading.get_ident()!=loop_thread;calls.append(package)
        return '2026.11.2' if package=='homeassistant' else 'synthetic'
    monkeypatch.setattr(compat,'version',version)
    snapshots=await asyncio.gather(*(compat.async_load_runtime_versions(hass) for _ in range(5)))
    assert calls==list(compat.PACKAGES)
    snapshots[0]['homeassistant']='modified'
    assert compat.runtime_versions(hass)['homeassistant']=='2026.11.2'
    monkeypatch.setattr(compat,'version',lambda *a:pytest.fail('metadata read on event loop'))
    entry=make_entry();entry.runtime_data=Session(lambda:FakeTransport())
    diag=importlib.import_module('custom_components.xparkle_rvlevel.diagnostics')
    for _ in range(3):
        result=await diag.async_get_config_entry_diagnostics(hass,entry)
        assert result['runtime_review_status']=='untested_runtime'
        result['runtime_versions'].clear()
        assert (await compat.async_load_runtime_versions(hass))['homeassistant']=='2026.11.2'
    await hass.async_stop(force=True)


async def test_cancelled_metadata_waiter_does_not_cancel_shared_executor_job():
    started=threading.Event();release=threading.Event();loop=asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        def collect():started.set();assert release.wait(3);return dict.fromkeys(compat.PACKAGES,'synthetic')
        hass=SimpleNamespace(data={},async_add_executor_job=lambda fn:loop.run_in_executor(pool,collect))
        one=asyncio.create_task(compat.async_load_runtime_versions(hass));two=asyncio.create_task(compat.async_load_runtime_versions(hass))
        try:
            await until(started.is_set);one.cancel()
            with pytest.raises(asyncio.CancelledError):await one
        finally:release.set()
        assert (await two)['homeassistant']=='synthetic'
        assert (await compat.async_load_runtime_versions(hass))['homeassistant']=='synthetic'


@pytest.mark.parametrize('kind',['schedule','failed_future','cancelled_future'])
async def test_optional_metadata_failure_does_not_prevent_setup(kind):
    calls=[]
    def schedule(fn):
        calls.append(1)
        if kind=='schedule':raise OSError('PRIVATE_METADATA_ERROR')
        f=asyncio.get_running_loop().create_future()
        if kind=='failed_future':f.set_exception(OSError('PRIVATE_METADATA_ERROR'))
        else:f.cancel()
        return f
    hass=SimpleNamespace(data={},async_add_executor_job=schedule)
    for _ in range(2):
        versions=await compat.async_load_runtime_versions(hass)
        assert set(versions.values())=={'unavailable'} and 'PRIVATE' not in json.dumps(versions)
    assert calls==[1]


def test_missing_package_and_review_labels_are_not_admission_decisions(monkeypatch):
    def missing(package):raise compat.PackageNotFoundError(package)
    monkeypatch.setattr(compat,'version',missing)
    versions=compat._collect_versions();assert set(versions.values())=={'not_installed'}
    assert compat.runtime_review_status(versions)=='metadata_unavailable'
    assert compat.runtime_review_status({**compat.BASELINE,'bleak':'3.0.2'})=='matches_recorded_versions'


async def test_allowlisted_admission_reason_never_leaks_raw_context():
    def broken():raise TransportAdmissionError('PRIVATE_ADDRESS_AND_ERROR')
    s=Session(broken,limits=FAST);await s.start();await until(lambda:s.safe)
    assert s.reason=='route_unavailable' and s.connection_attempts==0
