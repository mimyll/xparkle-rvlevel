"""Native entry/store/registry forward and inverse with immutable old source."""
import asyncio,importlib.util,json,sys,zipfile
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime,timezone
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er,device_registry as dr
from custom_components import xparkle_rvlevel as new
from custom_components.xparkle_rvlevel.runtime import battery_store
from test_native_lifecycle import native_entry,native_manager
from test_ha_adapter import adapter

@pytest.mark.parametrize("source_version",["0.3.0","0.4.0","0.5.0"])
async def test_old_new_old_preserves_entry_registry_options_cache_and_idle(adapter,monkeypatch,tmp_path,source_version):
    oldroot=tmp_path/'old';oldroot.mkdir()
    with zipfile.ZipFile(Path(__file__).parent/('fixtures/component-'+source_version+'.zip')) as z:z.extractall(oldroot)
    folder=oldroot/'custom_components/xparkle_rvlevel'
    package=ModuleType('xparkle_old_fixture_'+source_version.replace('.','_'));package.__path__=[str(folder)];sys.modules[package.__name__]=package
    spec=importlib.util.spec_from_file_location(package.__name__,folder/'__init__.py',submodule_search_locations=[str(folder)])
    old=importlib.util.module_from_spec(spec);sys.modules[package.__name__]=old;spec.loader.exec_module(old)
    hass=HomeAssistant(str(tmp_path/'ha'));manager,add=native_manager(hass,new,monkeypatch);manager._initialized.set()
    entry=native_entry('stable_upgrade');add(entry);manager.async_update_entry(entry,options={'battery_refresh_hours':24,'measurement_interval_seconds':.25,'level_tolerance_cm':.5,'vehicle_type':'tandem','vehicle_width_cm':215,'vehicle_length_cm':460,'mount_position':'right','directions_confirmed':True})
    dr.async_setup(hass);await asyncio.wait_for(dr.async_load(hass),3);await asyncio.wait_for(er.async_load(hass),3)
    device=dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id,identifiers={('xparkle_rvlevel',entry.unique_id)})
    rows=[er.async_get(hass).async_get_or_create(domain,'xparkle_rvlevel',entry.unique_id+'_'+suffix,device_id=device.id,config_entry=entry) for domain,suffix in [('sensor','battery'),('switch','measurement'),('sensor','levelling_status')]]
    pair={'value':73,'received_at':'2026-01-01T10:00:00+00:00'};await battery_store(hass,entry).async_save(pair)
    before=(entry.entry_id,entry.unique_id,dict(entry.options),[(x.entity_id,x.unique_id,x.device_id) for x in rows])
    # Constructors are never called: this checks idle update/restart semantics.
    monkeypatch.setattr(adapter[0],'HATransport',lambda *a:pytest.fail('Unexpected connect constructor'))
    for integration in (old,new,old):
        await asyncio.wait_for(integration.async_setup_entry(hass,entry),3)
        session=entry.runtime_data
        assert session.safe and not session.requested and session.read_count==session.connection_attempts==0
        assert session.battery==73 and session.battery_received_at.isoformat()==pair['received_at']
        assert (entry.entry_id,entry.unique_id,dict(entry.options),[(x.entity_id,x.unique_id,x.device_id) for x in rows])==before
        assert await asyncio.wait_for(integration.async_unload_entry(hass,entry),3)
        assert await battery_store(hass,entry).async_load()==pair
    await asyncio.wait_for(hass.async_stop(force=True),3)
