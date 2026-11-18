"""Native HA classes/bus with fake Bluetooth/platforms; never live I/O."""
import asyncio
from functools import partial
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import probatio
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import config_validation as cv
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from custom_components.xparkle_rvlevel.session import Session
from test_session import FakeTransport, FAST, until

DOMAIN = "custom_components.xparkle_rvlevel"


@pytest.fixture
def adapter(monkeypatch):
    bt = ModuleType("homeassistant.components.bluetooth")
    monkeypatch.setitem(sys.modules, bt.__name__, bt)
    import homeassistant.components
    monkeypatch.setattr(homeassistant.components, "bluetooth", bt, raising=False)
    monkeypatch.delitem(sys.modules, DOMAIN + ".transport", raising=False)
    return importlib.import_module(DOMAIN + ".transport"), bt


def target():
    return {"address": "00:00:00:00:00:01", "expected_name": "RVLevel-0001"}


def route(m, bt, monkeypatch, *, fresh=True, name_count=1, approved=True, free=True):
    data = target()
    info = SimpleNamespace(address=data["address"], name=data["expected_name"],
                           service_uuids=[m.SERVICE_UUID], time=m.time.monotonic() if fresh else 0)
    backend = type("SyntheticBackend", (), {"__module__": "bleak_esphome.backend.client" if approved else "other.backend"})
    connector = SimpleNamespace(client=partial(backend, client_data=object()), can_connect=lambda: free)
    scanner = SimpleNamespace(source="SYNTHETIC_PROXY", connector=connector, connectable=True,
                              connections_in_progress=lambda: 0,
                              get_allocations=lambda: SimpleNamespace(slots=3,free=3,allocated=[]))
    path = SimpleNamespace(scanner=scanner, ble_device=SimpleNamespace(address=data["address"], details={"source":"SYNTHETIC_PROXY"}))
    monkeypatch.setattr(m, "runtime_versions", lambda: {"homeassistant":"2026.11.0", "habluetooth":"7.1.2", "bleak":"3.0.2", "bleak-esphome":"4.0.0", "aioesphomeapi":"46.25.0"})
    values = {"async_current_scanners": lambda *a: [scanner], "async_discovered_service_info": lambda *a, **k: [info] * name_count,
              "async_scanner_devices_by_address": lambda *a, **k: [path],
              "async_ble_device_from_address": lambda *a, **k: "synthetic_device"}
    for name, value in values.items(): monkeypatch.setattr(bt, name, value, raising=False)
    def entries(domain):
        if domain == "esphome":
            return [SimpleNamespace(entry_id="synthetic_entry", state=ConfigEntryState.LOADED)]
        return [SimpleNamespace(data={"source": "SYNTHETIC_PROXY", "source_domain": "esphome",
                                      "source_config_entry_id": "synthetic_entry"})]
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=entries))
    return hass, data


@pytest.mark.parametrize("fresh,count,approved,free", [(True,1,True,True),(False,1,True,True),
    (True,2,True,True),(True,1,False,True),(True,1,True,False)])
def test_ha_managed_route_gate(adapter, monkeypatch, fresh, count, approved, free):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch, fresh=fresh, name_count=count, approved=approved, free=free)
    if fresh and approved and free:
        assert m.resolve(hass, data) == "synthetic_device"
    else:
        with pytest.raises(m.RouteUnavailable): m.resolve(hass, data)


async def test_wrapper_is_new_per_session_read_only_and_gate_rechecked_before_connect(adapter, monkeypatch):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    clients = []
    def wrapper(device, *, timeout, pair):
        assert device == "synthetic_device" and timeout == 20 and pair is False
        client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), read_gatt_char=AsyncMock(return_value=b"data"), is_connected=False)
        clients.append(client)
        return client
    monkeypatch.setattr(m, "HaBleakClientWrapper", wrapper)
    first, second = m.HATransport(hass, data), m.HATransport(hass, data)
    assert first.client is not second.client
    await first.connect()
    assert await first.read() == b"data"
    await first.disconnect()
    clients[0].read_gatt_char.assert_awaited_once_with(m.READ_UUID)
    monkeypatch.setattr(m, "resolve", lambda *a: (_ for _ in ()).throw(m.RouteUnavailable()))
    with pytest.raises(m.RouteUnavailable): await second.connect()
    clients[1].connect.assert_not_called()


async def test_native_config_form_validation_and_duplicate_abort():
    flow_module = importlib.import_module(DOMAIN + ".config_flow")
    fields = probatio.to_field_list(flow_module.FORM_SCHEMA, custom_serializer=cv.custom_serializer)
    assert all(field["type"] == "string" for field in fields)
    for data in ({"address":"bad","expected_name":"RVLevel-0001"},
                 {**target(),"write_command":"bad"},
                 {**target(),"expected_name":"unsupported"}):
        with pytest.raises(vol.Invalid): flow_module.INPUT_SCHEMA(data)
    flow = flow_module.XparkleConfigFlow()
    flow.context = {"source":"user"}
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_entry_for_domain_unique_id=lambda *a: SimpleNamespace(source="user"),
        async_entries=lambda *a, **k: [SimpleNamespace(unique_id=target()["address"])],
        flow=SimpleNamespace(async_progress_by_handler=lambda *a, **k: [])))
    # Native HA duplicate rejection, with only entry enumeration faked.
    flow._async_current_entries = lambda *a, **k: [SimpleNamespace(unique_id=target()["address"])]
    with pytest.raises(AbortFlow): await flow.async_step_user(target())


def make_entry():
    callbacks = []
    return SimpleNamespace(data=target(), unique_id="synthetic_stable_id", entry_id="synthetic_entry",
                           options={"battery_refresh_hours":0},
                           add_update_listener=lambda listener: lambda: None,
                           async_on_unload=callbacks.append, unload_callbacks=callbacks)


async def test_setup_stays_idle_shutdown_and_unload_close_session(adapter, monkeypatch, tmp_path):
    transport_module, _ = adapter
    transport = FakeTransport()
    calls = []
    monkeypatch.setattr(transport_module, "HATransport", lambda *a: calls.append("factory") or transport)
    integration = importlib.import_module(DOMAIN)
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                                         async_unload_platforms=AsyncMock(return_value=True))
    entry = make_entry()
    assert await integration.async_setup_entry(hass, entry)
    session = entry.runtime_data
    session.limits = FAST
    assert calls == [] and session.safe and not session.requested
    assert await session.start()
    await until(lambda: session.read_count)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await until(lambda: session.safe)
    assert not await session.start()
    assert await integration.async_unload_entry(hass, entry)
    for callback in entry.unload_callbacks: callback()
    await hass.async_block_till_done()
    assert len(calls) == 1 and transport.calls.count("disconnect") == 1


async def test_partial_setup_failure_cleans_listener_and_runtime(adapter, monkeypatch, tmp_path):
    integration = importlib.import_module(DOMAIN)
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(side_effect=RuntimeError("synthetic_failure")),
                                         async_unload_platforms=AsyncMock(return_value=True))
    entry = make_entry()
    before = hass.bus.async_listeners().copy()
    with pytest.raises(RuntimeError): await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data.safe and not await entry.runtime_data.start()
    assert hass.bus.async_listeners() == before
    hass.config_entries.async_unload_platforms.assert_awaited_once()
    await hass.async_block_till_done()


async def test_controls_cannot_start_during_partial_setup_and_retry_has_no_prior_link(adapter, monkeypatch, tmp_path):
    transport_module, _ = adapter
    integration = importlib.import_module(DOMAIN)
    transport = FakeTransport()
    monkeypatch.setattr(transport_module, "HATransport", lambda *a:transport)
    hass = HomeAssistant(str(tmp_path))
    entry = make_entry()
    async def partial_forward(*args):
        assert not await entry.runtime_data.start()
        assert not await entry.runtime_data.refresh_battery()
        raise RuntimeError("synthetic_partial_failure")
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=partial_forward,
                                         async_unload_platforms=AsyncMock(return_value=True))
    with pytest.raises(RuntimeError): await integration.async_setup_entry(hass, entry)
    prior = entry.runtime_data
    assert prior.safe and not await prior.start() and transport.calls == []
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    assert await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data is not prior and transport.calls == []
    assert await integration.async_unload_entry(hass, entry)
    for callback in entry.unload_callbacks: callback()
    await hass.async_block_till_done()


async def test_unload_refuses_unconfirmed_cleanup(adapter, tmp_path):
    integration = importlib.import_module(DOMAIN)
    hass = HomeAssistant(str(tmp_path))
    unload = AsyncMock(return_value=True)
    hass.config_entries = SimpleNamespace(async_unload_platforms=unload)
    transport = FakeTransport()
    transport.disconnect_error = True
    entry = make_entry()
    entry.runtime_data = Session(lambda: transport, limits=FAST)
    await entry.runtime_data.start()
    await until(lambda: entry.runtime_data.read_count)
    assert not await integration.async_unload_entry(hass, entry)
    unload.assert_not_called()
    from homeassistant.exceptions import ConfigEntryNotReady
    previous = entry.runtime_data
    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data is previous
    transport.is_connected = False
    assert await entry.runtime_data.stop()


async def test_entities_manual_controls_stable_ids_freshness_and_allowlisted_diagnostics(tmp_path):
    modules = {platform: importlib.import_module(DOMAIN + "." + platform)
               for platform in ("switch", "button", "sensor", "binary_sensor")}
    entry = make_entry()
    transport = FakeTransport()
    entry.runtime_data = Session(lambda: transport, limits=FAST)
    entities = []
    for module in modules.values(): await module.async_setup_entry(None, entry, entities.extend)
    assert len(entities) == 23
    assert all(not entity.should_poll for entity in entities)
    assert len({entity.unique_id for entity in entities}) == len(entities)
    switch = next(e for e in entities if e.translation_key == "measurement")
    button = next(e for e in entities if e.translation_key == "keep_measuring")
    pitch = next(e for e in entities if e.translation_key == "pitch_magnitude")
    battery = next(e for e in entities if e.translation_key == "battery")
    assert not switch.is_on and not pitch.available
    with pytest.raises(HomeAssistantError): await button.async_press()
    assert transport.calls == []
    await switch.async_turn_on()
    await until(lambda: entry.runtime_data.read_count)
    assert switch.is_on and pitch.available and pitch.native_value == 0.09
    assert battery.native_value == 100
    old_deadline = entry.runtime_data.deadline
    await button.async_press()
    assert entry.runtime_data.deadline > old_deadline
    battery_received = entry.runtime_data.battery_received_at
    transport.payload = bytes((0,0,9,1,0,50,255))
    await until(lambda: entry.runtime_data.measurement.battery is None)
    assert pitch.available and battery.native_value == 100
    assert battery.extra_state_attributes["cached"] is True
    assert entry.runtime_data.battery_received_at == battery_received
    await switch.async_turn_off()
    assert not switch.is_on and not pitch.available
    # HA's own Entity state writer handles these push-only states.
    hass = HomeAssistant(str(tmp_path))
    pitch.hass = hass
    pitch.entity_id = "sensor.synthetic_pitch"
    from homeassistant.helpers.entity_platform import EntityPlatform
    from datetime import timedelta
    import logging
    platform = EntityPlatform(hass=hass, logger=logging.getLogger(__name__), domain="sensor",
                              platform_name="xparkle_rvlevel", platform=modules["sensor"],
                              scan_interval=timedelta(seconds=30), entity_namespace=None)
    pitch.add_to_platform_start(hass, platform, None)
    await pitch.add_to_platform_finish()
    assert hass.states.get(pitch.entity_id).state == "unavailable"
    diag = importlib.import_module(DOMAIN + ".diagnostics")
    entry.data = {"address":"PRIVATE_ADDRESS_SENTINEL", "expected_name":"PRIVATE_NAME_SENTINEL"}
    output = json.dumps(await diag.async_get_config_entry_diagnostics(None, entry))
    assert "PRIVATE" not in output and "synthetic_stable_id" not in output
    assert not hasattr(switch, "async_get_last_state")
    again = modules["switch"].MeasurementSwitch(entry, "measurement")
    assert switch.unique_id == again.unique_id and not again.is_on
    await pitch.async_remove(force_remove=True)
    await hass.async_block_till_done()


def test_translations_and_package_contain_no_runtime_target():
    component = Path(__file__).parents[1] / "custom_components/xparkle_rvlevel"
    english = json.loads((component / "strings.json").read_text())
    finnish = json.loads((component / "translations/fi.json").read_text())
    assert english["entity"].keys() == finnish["entity"].keys()
    assert finnish["entity"]["button"]["keep_measuring"]["name"] == "Jatka mittausta"
    manifest = json.loads((component / "manifest.json").read_text())
    assert manifest["version"] == "0.4.0" and manifest["config_flow"]


async def test_failed_wrapper_connect_stays_unconfirmed_even_if_local_client_is_down(adapter, monkeypatch):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    client = SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError("PRIVATE_CONNECT_SENTINEL")),
                             disconnect=AsyncMock(), is_connected=False)
    monkeypatch.setattr(m, "HaBleakClientWrapper", lambda *a, **k: client)
    transport = m.HATransport(hass, data)
    with pytest.raises(RuntimeError): await transport.connect()
    await transport.disconnect()
    assert not transport.is_connected and not transport.cleanup_confirmed


@pytest.mark.parametrize("was_connected,acknowledged", [(True,True),(False,True),(True,False)])
async def test_only_acknowledged_teardown_of_live_wrapper_confirms_cleanup(adapter, monkeypatch, was_connected, acknowledged):
    m, bt = adapter
    hass, data = route(m, bt, monkeypatch)
    client = SimpleNamespace(connect=AsyncMock(), is_connected=was_connected)
    async def disconnect():
        client.is_connected = False
        if not acknowledged: raise RuntimeError("PRIVATE_DISCONNECT_SENTINEL")
    client.disconnect = disconnect
    monkeypatch.setattr(m, "HaBleakClientWrapper", lambda *a, **k: client)
    transport = m.HATransport(hass, data)
    await transport.connect()
    try: await transport.disconnect()
    except RuntimeError: pass
    assert transport.cleanup_confirmed is (was_connected and acknowledged)


def test_options_strict_bounds_and_no_operation_overrides():
    flow = importlib.import_module(DOMAIN + ".config_flow")
    good = {"battery_refresh_hours":24,"measurement_interval_seconds":2}
    for hours in (0,1,24,168):
        assert flow.OPTIONS_SCHEMA({**good,"battery_refresh_hours":hours})["battery_refresh_hours"] == hours
    for data in ({**good,"battery_refresh_hours":True},{**good,"battery_refresh_hours":169},
                 {**good,"battery_refresh_hours":-1},{**good,"battery_refresh_hours":1.5},
                 {**good,"measurement_interval_seconds":0},{**good,"measurement_interval_seconds":11},
                 {**good,"uuid":"override"}):
        with pytest.raises(vol.Invalid): flow.OPTIONS_SCHEMA(data)


async def test_battery_schedule_registers_one_delayed_interval_skips_busy_and_cancels(monkeypatch):
    runtime = importlib.import_module(DOMAIN + ".runtime")
    registrations = []
    def register(hass, callback, interval, **kwargs):
        record = {"callback":callback,"seconds":interval.total_seconds(),"cancelled":False}
        registrations.append(record)
        def cancel(): record["cancelled"] = True
        return cancel
    monkeypatch.setattr(runtime, "async_track_time_interval", register)
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    entry = make_entry()
    entry.options = {}
    cancel = runtime.register_schedule(None, entry, session)
    assert len(registrations) == 1 and registrations[0]["seconds"] == 86400
    assert transport.calls == []
    await session.start()
    await until(lambda: session.read_count)
    mode, deadline = session.mode, session.deadline
    await registrations[0]["callback"](None)
    assert session.mode == mode and session.deadline == deadline and session.connection_attempts == 1
    assert await session.stop()
    cancel()
    assert registrations[0]["cancelled"]
    entry.options = {"battery_refresh_hours":0}
    runtime.register_schedule(None, entry, session)()
    assert len(registrations) == 1
    entry.options = {"battery_refresh_hours":1}
    runtime.register_schedule(None, entry, session)()
    assert len(registrations) == 2 and registrations[1]["seconds"] == 3600


def test_battery_restore_preserves_timestamp_and_rejects_corruption_without_connecting():
    from datetime import datetime, timezone
    runtime = importlib.import_module(DOMAIN + ".runtime")
    def no_factory(): raise AssertionError("must_not_connect")
    session = Session(no_factory)
    timestamp = "2026-01-01T00:00:00+00:00"
    runtime.restore_battery(session, {"value":75,"received_at":timestamp})
    assert session.battery == 75 and session.battery_received_at.isoformat() == timestamp
    for data in (None,{}, {"value":255,"received_at":timestamp},
                 {"value":True,"received_at":timestamp},{"value":50,"received_at":"bad"},
                 {"value":50,"received_at":"2026-01-01T00:00:00"},
                 {"value":50,"received_at":"9999-01-01T00:00:00+00:00"}):
        runtime.restore_battery(session, data)
        assert session.battery == 75 and session.battery_received_at.isoformat() == timestamp
    assert session.safe and not session.requested
