"""Native timer jobs and HA state publication; deterministic clock, fake radio."""
import asyncio
import pytest
from datetime import timedelta
import importlib
import logging
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.xparkle_rvlevel.runtime import register_schedule
from custom_components.xparkle_rvlevel.session import Session
from test_ha_adapter import make_entry
from test_session import FakeTransport, FAST, until


class TimerClock:
    """Only the event helper's timer boundary is virtual; native jobs run normally."""
    def __init__(self):
        self.now = 0
        self.handles = []

    def time(self):
        return self.now

    def call_at(self, when, callback, *args):
        handle = SimpleNamespace(when=when, callback=callback, args=args, cancelled=False)
        handle.cancel = lambda: setattr(handle, "cancelled", True)
        self.handles.append(handle)
        return handle

    def advance(self, seconds):
        self.now += seconds
        due = [h for h in self.handles if not h.cancelled and h.when <= self.now]
        for handle in due:
            handle.cancelled = True
            handle.callback(*handle.args)


async def test_native_interval_waits_skips_busy_and_does_not_catch_up(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    clock = TimerClock()
    timer_hass = SimpleNamespace(loop=clock, async_run_hass_job=hass.async_run_hass_job)
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    entry = make_entry()
    entry.options = {"battery_refresh_hours": 1}
    cancel = register_schedule(timer_hass, entry, session)
    clock.advance(3599)
    await asyncio.sleep(0)
    assert transport.calls == []
    clock.advance(1)
    await until(lambda: session.read_count == 1 and session.safe)
    assert transport.calls == ["connect", "read", "disconnect"]
    await session.start()
    await until(lambda: session.read_count)
    connections = transport.calls.count("connect")
    clock.advance(5 * 3600)  # Missed ticks never generate a catch-up burst.
    await asyncio.sleep(0)
    assert transport.calls.count("connect") == connections
    assert await session.stop()
    clock.advance(3599)
    await asyncio.sleep(0)
    assert transport.calls.count("connect") == connections
    clock.advance(1)
    await until(lambda: transport.calls.count("connect") == connections + 1 and session.safe)
    cancel()
    clock.advance(3600)
    await asyncio.sleep(0)
    assert transport.calls.count("connect") == connections + 1
    entry.options = {"battery_refresh_hours": 0}
    register_schedule(timer_hass, entry, session)()
    assert all(h.cancelled for h in clock.handles)
    await hass.async_block_till_done()


@pytest.mark.parametrize("ending", ["stop", "stalled_read"])
async def test_ha_states_are_invalidated_on_stalled_read_and_detach_on_remove(tmp_path, ending):
    hass = HomeAssistant(str(tmp_path))
    sensors = importlib.import_module("custom_components.xparkle_rvlevel.sensor")
    binaries = importlib.import_module("custom_components.xparkle_rvlevel.binary_sensor")
    entry = make_entry()
    transport = FakeTransport()
    entry.runtime_data = Session(lambda: transport, limits=FAST)
    session = entry.runtime_data
    candidates = []
    await sensors.async_setup_entry(hass, entry, candidates.extend)
    await binaries.async_setup_entry(hass, entry, candidates.extend)
    chosen = [e for e in candidates if e.translation_key in ("pitch_magnitude", "battery", "connected", "uphill", "left_tilt")]
    for entity in chosen:
        domain = "binary_sensor" if entity.translation_key in ("connected", "uphill", "left_tilt") else "sensor"
        module = binaries if domain == "binary_sensor" else sensors
        platform = EntityPlatform(hass=hass, logger=logging.getLogger(__name__), domain=domain,
            platform_name="xparkle_rvlevel", platform=module,
            scan_interval=timedelta(seconds=30), entity_namespace=None)
        entity.entity_id = domain + ".synthetic_" + entity.translation_key
        entity.add_to_platform_start(hass, platform, None)
        await entity.add_to_platform_finish()
    assert hass.states.get("sensor.synthetic_pitch_magnitude").state == "unavailable"
    await session.start()
    await until(lambda: session.read_count)
    assert hass.states.get("sensor.synthetic_pitch_magnitude").state == "0.09"
    assert hass.states.get("binary_sensor.synthetic_connected").state == "on"
    assert hass.states.get("binary_sensor.synthetic_uphill").state == "off"
    assert hass.states.get("binary_sensor.synthetic_left_tilt").state == "on"
    assert hass.states.get("sensor.synthetic_battery").attributes["sensor_sample_age"] == "unknown"
    received = session.battery_received_at.isoformat()
    if ending == "stop":
        assert await session.stop()
        assert session.reason == "user_stop"
    else:
        transport.read_block = asyncio.Event()
        await until(lambda: session.safe)
        assert session.reason == "operation_timeout"
    assert hass.states.get("sensor.synthetic_pitch_magnitude").state == "unavailable"
    assert hass.states.get("binary_sensor.synthetic_connected").state == "off"
    assert hass.states.get("binary_sensor.synthetic_uphill").state == "unavailable"
    assert hass.states.get("binary_sensor.synthetic_left_tilt").state == "unavailable"
    battery = hass.states.get("sensor.synthetic_battery")
    assert battery.state == "100" and battery.attributes["last_received"] == received
    assert battery.attributes["cached"] is True
    for entity in chosen:
        await entity.async_remove(force_remove=True)
    assert not session._listeners
    await hass.async_block_till_done()
