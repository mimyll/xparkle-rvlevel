"""HA Store and delayed-schedule ownership in a disposable HA directory."""
import asyncio
from datetime import datetime, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.xparkle_rvlevel.session import Session
from custom_components.xparkle_rvlevel.runtime import battery_store, restore_battery
from test_ha_adapter import make_entry, DOMAIN
from test_session import FakeTransport, FAST, until


async def test_original_store_delayed_write_cannot_recreate_cache_after_unload_remove(tmp_path):
    integration = importlib.import_module(DOMAIN)
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
    entry = make_entry()
    entry.runtime_data = Session(lambda: FakeTransport(), limits=FAST)
    session = entry.runtime_data
    session.battery = 75
    session.battery_received_at = datetime(2026,1,1,tzinfo=timezone.utc)
    original = battery_store(hass, entry)
    original.async_delay_save(lambda: {"value":75,"received_at":session.battery_received_at.isoformat()}, 0.02)
    assert battery_store(hass, entry) is original
    assert await integration.async_unload_entry(hass, entry)
    assert (await original.async_load())["value"] == 75
    await integration.async_remove_entry(hass, entry)
    await asyncio.sleep(0.05)  # Beyond the deliberately shortened pending delay.
    await hass.async_block_till_done()
    # Use the owning storage API, never inspect HA's storage files manually.
    assert await original.async_load() is None
    assert await battery_store(hass, entry).async_load() is None
    assert session.safe and not await session.start()


async def test_options_form_native_serialization_and_submit():
    import probatio
    from homeassistant.helpers import config_validation as cv
    from custom_components.xparkle_rvlevel.config_flow import XparkleOptionsFlow
    entry = make_entry()
    entry.options = {}
    flow = XparkleOptionsFlow()
    flow.handler = entry.entry_id
    flow.context = {}
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda key:entry))
    result = await flow.async_step_init()
    fields = probatio.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    assert {f["name"]:f["default"] for f in fields} == {
        "battery_refresh_hours":24, "measurement_interval_seconds":0.5, "level_tolerance_cm":0.25, "vehicle_type":"caravan", "vehicle_width_cm":0, "vehicle_length_cm":0, "mount_position":"not_set", "directions_confirmed":False}
    result = await flow.async_step_init({"battery_refresh_hours":0,"measurement_interval_seconds":5})
    assert result["data"] == {"battery_refresh_hours":0,"measurement_interval_seconds":5, "level_tolerance_cm":0.25, "vehicle_type":"caravan", "vehicle_width_cm":0, "vehicle_length_cm":0, "mount_position":"not_set", "directions_confirmed":False}
