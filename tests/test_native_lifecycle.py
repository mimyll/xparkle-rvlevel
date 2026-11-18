"""Native HA entry/shutdown semantics with synthetic radio and platform I/O."""
import asyncio
import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntries, ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady

from test_ha_adapter import adapter, make_entry
from test_session import FakeTransport, FAST, until
from custom_components.xparkle_rvlevel.runtime import battery_store, domain_state


def native_entry(entry_id, address="00:00:00:00:00:01"):
    return ConfigEntry(version=1, minor_version=1, domain="xparkle_rvlevel",
        title="Synthetic level", data={"address": address, "expected_name": "RVLevel-0001"},
        options={"battery_refresh_hours": 0}, source="user", unique_id=address,
        entry_id=entry_id, discovery_keys={}, subentries_data=[], state=ConfigEntryState.LOADED)


def native_manager(hass, integration, monkeypatch):
    manager = ConfigEntries(hass, {})
    hass.config_entries = manager
    import homeassistant.config_entries as config_entries
    # Only frame-based deprecation reporting is unrelated to this native harness.
    monkeypatch.setattr(config_entries, "report_usage", lambda *a, **k: None)
    monkeypatch.setattr(manager, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(manager, "async_unload_platforms", AsyncMock(return_value=True))
    monkeypatch.setattr(manager, "async_update_issues", lambda: None)
    monkeypatch.setattr(manager, "_async_schedule_save", lambda: None)
    loader = SimpleNamespace(domain="xparkle_rvlevel",
        async_get_component=AsyncMock(return_value=integration), logger=logging.getLogger(__name__))

    def add(entry):
        object.__setattr__(entry, "_integration_for_domain", loader)
        manager._entries[entry.entry_id] = entry
    return manager, add


async def test_native_remove_readd_cannot_escape_uncertain_target_owner(adapter, monkeypatch, tmp_path):
    integration = importlib.import_module("custom_components.xparkle_rvlevel")
    hass = HomeAssistant(str(tmp_path))
    manager, add = native_manager(hass, integration, monkeypatch)
    old, other, replacement = FakeTransport(), FakeTransport(), FakeTransport()
    old.cleanup_confirmed = False
    transports = iter((old, other, replacement))
    monkeypatch.setattr(adapter[0], "HATransport", lambda *a: next(transports))
    entry = native_entry("synthetic_old")
    add(entry)
    await integration.async_setup_entry(hass, entry)
    session = entry.runtime_data
    session.limits = FAST
    await session.start()
    await until(lambda: session.read_count)
    original_store = battery_store(hass, entry)
    assert not await session.stop()
    unloaded, _ = await manager._async_remove(entry.entry_id)
    assert not unloaded and entry.state is ConfigEntryState.FAILED_UNLOAD
    assert manager.async_entry_for_domain_unique_id("xparkle_rvlevel", entry.unique_id) is None
    owner = domain_state(hass).owners[entry.data["address"]]
    assert owner.session is session and not owner.callbacks
    assert owner.stop_listener is not None and not session.safe
    assert await original_store.async_load() is None
    # No cache producer survives removal, even a late state publication.
    session._emit()
    assert await original_store.async_load() is None

    new_entry = native_entry("synthetic_replacement")
    add(new_entry)
    with pytest.raises(ConfigEntryNotReady, match="cleanup is unconfirmed"):
        await integration.async_setup_entry(hass, new_entry)
    assert not hasattr(new_entry, "runtime_data")
    assert not await session.start() and not await session.refresh_battery()
    assert replacement.calls == []

    unrelated = native_entry("synthetic_unrelated", "00:00:00:00:00:02")
    add(unrelated)
    await integration.async_setup_entry(hass, unrelated)
    unrelated.runtime_data.limits = FAST
    await unrelated.runtime_data.refresh_battery()
    await until(lambda: unrelated.runtime_data.safe)
    assert other.calls == ["connect", "read", "disconnect"]
    assert await manager.async_unload(unrelated.entry_id)

    old.cleanup_confirmed = True  # Verified release, never a cached free-slot inference.
    await session.stop()
    await integration.async_setup_entry(hass, new_entry)
    new_entry.runtime_data.limits = FAST
    assert await new_entry.runtime_data.refresh_battery()
    await until(lambda: new_entry.runtime_data.safe)
    assert replacement.calls == ["connect", "read", "disconnect"]
    assert await manager.async_unload(new_entry.entry_id)
    assert not owner.callbacks and owner.stop_listener is None
    await hass.async_block_till_done()


@pytest.mark.parametrize("operation", ["connect", "read"])
async def test_actual_ha_stop_settles_owned_operation_and_persists_pair(adapter, monkeypatch, tmp_path, operation):
    integration = importlib.import_module("custom_components.xparkle_rvlevel")
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True))
    transport = FakeTransport()
    monkeypatch.setattr(adapter[0], "HATransport", lambda *a: transport)
    entry = make_entry()
    await integration.async_setup_entry(hass, entry)
    session = entry.runtime_data
    session.limits = FAST
    if operation == "connect":
        transport.connect_block = asyncio.Event()
    await session.start()
    if operation == "read":
        await until(lambda: session.read_count)
        transport.read_block = asyncio.Event()
        reads = transport.calls.count("read")
        await until(lambda: transport.calls.count("read") > reads)
    else:
        await until(lambda: "connect" in transport.calls)
    received, count = session.battery_received_at, session.read_count
    # Real cancellation -> STOP -> final-write -> CLOSE sequence.
    await hass.async_stop(force=True)
    assert session.safe and not await session.start() and not await session.refresh_battery()
    assert session.read_count == count and transport.calls.count("disconnect") == 1
    saved = await battery_store(hass, entry).async_load()
    assert saved == ({"value": 100, "received_at": received.isoformat()} if received else None)


@pytest.mark.parametrize("failure", ["platform", "store"])
async def test_native_failed_unload_closes_admission_without_replacing_owner(adapter, monkeypatch, tmp_path, failure):
    integration = importlib.import_module("custom_components.xparkle_rvlevel")
    hass = HomeAssistant(str(tmp_path))
    manager, add = native_manager(hass, integration, monkeypatch)
    transport = FakeTransport()
    monkeypatch.setattr(adapter[0], "HATransport", lambda *a: transport)
    entry = native_entry("synthetic_unload")
    add(entry)
    await integration.async_setup_entry(hass, entry)
    session = entry.runtime_data
    session.limits = FAST
    await session.refresh_battery()
    await until(lambda: session.safe)
    if failure == "platform":
        manager.async_unload_platforms.side_effect = RuntimeError("synthetic platform failure")
    else:
        monkeypatch.setattr(battery_store(hass, entry), "async_save", AsyncMock(side_effect=OSError("synthetic disk full")))
    hass.config.components.add("xparkle_rvlevel")
    monkeypatch.setattr(manager, "async_setup", AsyncMock())
    assert not await manager.async_reload(entry.entry_id)
    manager.async_setup.assert_not_called()
    assert entry.state is ConfigEntryState.FAILED_UNLOAD and entry.runtime_data is session
    assert domain_state(hass).owners[entry.data["address"]].session is session
    assert session.safe and not await session.start() and not await session.refresh_battery()
    assert transport.calls == ["connect", "read", "disconnect"]
    domain_state(hass).owners[entry.data["address"]].detach()
    await hass.async_stop(force=True)


async def test_store_load_failure_never_enables_or_orphans_setup(adapter, monkeypatch, tmp_path):
    integration = importlib.import_module("custom_components.xparkle_rvlevel")
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True))
    entry = make_entry()
    before = hass.bus.async_listeners().copy()
    monkeypatch.setattr(battery_store(hass, entry), "async_load", AsyncMock(side_effect=OSError("synthetic disk failure")))
    with pytest.raises(OSError):
        await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data.safe and not await entry.runtime_data.start()
    hass.config_entries.async_forward_entry_setups.assert_not_called()
    assert hass.bus.async_listeners() == before


async def test_native_options_reload_replaces_one_owner_and_one_schedule(adapter, monkeypatch, tmp_path):
    from test_native_schedule_states import TimerClock
    from homeassistant.helpers.event import async_track_time_interval
    integration = importlib.import_module("custom_components.xparkle_rvlevel")
    runtime = importlib.import_module("custom_components.xparkle_rvlevel.runtime")
    hass = HomeAssistant(str(tmp_path))
    manager, add = native_manager(hass, integration, monkeypatch)
    hass.config.components.add("xparkle_rvlevel")
    clock = TimerClock()
    timer_hass = SimpleNamespace(loop=clock, async_run_hass_job=hass.async_run_hass_job)
    monkeypatch.setattr(runtime, "async_track_time_interval",
        lambda _, *a, **k: async_track_time_interval(timer_hass, *a, **k))
    transport = FakeTransport()
    monkeypatch.setattr(adapter[0], "HATransport", lambda *a: transport)
    entry = native_entry("synthetic_reload")
    add(entry)
    await integration.async_setup_entry(hass, entry)
    previous = entry.runtime_data
    previous.limits = FAST
    await previous.start()
    await until(lambda: previous.read_count)

    async def setup(entry_id, **kwargs):
        assert entry_id == entry.entry_id
        await integration.async_setup_entry(hass, entry)
        entry._async_set_state(hass, ConfigEntryState.LOADED, None)
        return True

    monkeypatch.setattr(manager, "async_setup", setup)
    assert manager.async_update_entry(entry, options={"battery_refresh_hours": 1})
    await until(lambda: entry.state is ConfigEntryState.LOADED
                and getattr(entry, "runtime_data", previous) is not previous)
    current = entry.runtime_data
    current.limits = FAST
    assert previous.safe and not await previous.start()
    assert not current.requested and not current.connection_attempts
    assert len(entry.update_listeners) == 1
    assert len([h for h in clock.handles if not h.cancelled]) == 1
    clock.advance(3600)
    await until(lambda: current.read_count and current.safe)
    assert transport.calls.count("connect") == 2
    assert await manager.async_unload(entry.entry_id)
    assert all(h.cancelled for h in clock.handles)
    assert not entry.update_listeners
    await hass.async_block_till_done()
