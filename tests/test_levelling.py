"""Independent geometry oracles, native HA options/entities, no real transport."""
from dataclasses import replace
from math import asin, degrees
from types import SimpleNamespace
import asyncio
import importlib
from datetime import timedelta
import logging
import pytest
import voluptuous as vol

from custom_components.xparkle_rvlevel.levelling import (
    Geometry, height_difference, corrections, CORRECTION_KEYS, CORNER_KEYS)
from custom_components.xparkle_rvlevel.protocol import Measurement
from custom_components.xparkle_rvlevel.sensor import LevellingSensor, LEVEL_KEYS
from custom_components.xparkle_rvlevel.session import Session
from test_ha_adapter import make_entry
from test_session import FakeTransport, FAST, until


SETTINGS = {"vehicle_width_cm": 200, "vehicle_length_cm": 500,
            "mount_position": "front", "directions_confirmed": True}


def test_independent_triangle_and_degree_unit_oracles():
    assert height_difference(500, degrees(asin(3/5))) == pytest.approx(3000)
    assert height_difference(200, 45) == pytest.approx(1414.213562373095)
    assert height_difference(500, 0) == 0
    out = corrections(20, -10)
    assert [out[k] for k in CORRECTION_KEYS] == [-20, 20, 10, -10]
    assert [out[k] for k in CORNER_KEYS] == [10, 0, 30, 20]
    assert all(v == 0 for v in corrections(0, 0).values())


@pytest.mark.parametrize("pitch,roll", [(20, 10), (20, -10), (-20, 10), (-20, -10), (20, 0), (0, -10)])
def test_highest_reference_anchor_and_alternatives(pitch, roll):
    out = corrections(pitch, roll)
    assert out["front_correction"] == -out["rear_correction"] == -pitch
    assert out["left_correction"] == -out["right_correction"] == -roll
    lifts = [out[k] for k in CORNER_KEYS]
    assert min(lifts) == 0 and max(lifts) == abs(pitch) + abs(roll)
    assert lifts[0] - lifts[2] == -pitch
    assert lifts[0] - lifts[1] == -roll


@pytest.mark.parametrize("value", [True, False, -1, .5, float("nan"), float("inf"), "200", 10**1000])
def test_invalid_dimensions_are_rejected(value):
    with pytest.raises((ValueError, vol.Invalid)):
        Geometry.from_options({**SETTINGS, "vehicle_width_cm": value})


@pytest.mark.parametrize("angle", [-.01, 45.01, 90, 655.35, float("nan"), float("inf"), True, 10**1000])
def test_unsupported_angles_never_produce_guidance(angle):
    with pytest.raises(ValueError):
        height_difference(200, angle)


@pytest.mark.parametrize("uphill,left_tilt", [(False,False), (False,True), (True,False), (True,True)])
def test_flags_follow_explicit_confirmed_current_output_not_mount_rotation(uphill, left_tilt):
    measurement = Measurement(degrees(asin(.004)), degrees(asin(.005)), uphill, left_tilt, 75)
    geom = Geometry.from_options(SETTINGS)
    values = geom.values(measurement)
    assert values["front_correction"] == pytest.approx(-20 if uphill else 20)
    assert values["left_correction"] == pytest.approx(10 if left_tilt else -10)
    for mount in ("front", "rear", "left", "right"):
        assert replace(geom, mount_position=mount).values(measurement) == values


def test_missing_direction_confirmation_never_gives_signed_or_corner_guidance():
    m = Measurement(1, 2, True, True, 75)
    assert Geometry.from_options({}).values(m) == {}
    geom = Geometry.from_options({**SETTINGS, "directions_confirmed": False})
    assert set(geom.values(m)) == {"longitudinal_difference", "transverse_difference"}
    for options in ({**SETTINGS,"mount_position":"not_set"}, {**SETTINGS,"vehicle_width_cm":0},
                    {**SETTINGS,"directions_confirmed":1}, {**SETTINGS,"mount_position":"top"}):
        with pytest.raises(ValueError): Geometry.from_options(options)


async def test_native_options_preserve_old_values_and_clear_confirmation_on_mount_change():
    from custom_components.xparkle_rvlevel.config_flow import XparkleOptionsFlow, OPTIONS_SCHEMA
    from homeassistant.config_entries import ConfigEntry
    entry = ConfigEntry(version=1,minor_version=1,domain="xparkle_rvlevel",title="Synthetic",
        data={},options={"battery_refresh_hours":72,"measurement_interval_seconds":7,**SETTINGS},
        source="user",unique_id="synthetic",discovery_keys={},subentries_data=[])
    flow = XparkleOptionsFlow()
    flow.handler = entry.entry_id
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda _:entry))
    form = await flow.async_step_init()
    assert form["type"] == "form"
    changed = await flow.async_step_init({**dict(entry.options), "mount_position":"rear"})
    assert changed["data"]["directions_confirmed"] is False
    assert changed["data"]["battery_refresh_hours"] == 72
    assert changed["data"]["measurement_interval_seconds"] == 7
    # A later separate confirmation for the saved mounting remains possible.
    entry = SimpleNamespace(options=changed["data"])
    flow.hass.config_entries.async_get_known_entry = lambda _: entry
    confirmed = await flow.async_step_init({**entry.options, "directions_confirmed":True})
    assert confirmed["data"]["directions_confirmed"] is True
    # Defaults must accept exactly the old two-field option shape.
    old = OPTIONS_SCHEMA({"battery_refresh_hours":72,"measurement_interval_seconds":7})
    assert old["mount_position"] == "not_set" and old["directions_confirmed"] is False


@pytest.mark.parametrize("ending", ["stop", "stalled_read"])
async def test_native_derived_states_close_with_manual_session_and_battery_does_not_reactivate(tmp_path, ending):
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import EntityPlatform
    module = importlib.import_module("custom_components.xparkle_rvlevel.sensor")
    hass = HomeAssistant(str(tmp_path))
    entry = make_entry()
    entry.options.update(SETTINGS)
    transport = FakeTransport()
    entry.runtime_data = Session(lambda: transport, limits=FAST)
    session = entry.runtime_data
    entity = LevellingSensor(entry,"front_correction")
    entity.entity_id = "sensor.synthetic_correction"
    platform = EntityPlatform(hass=hass, logger=logging.getLogger(__name__), domain="sensor",
        platform_name="xparkle_rvlevel",platform=module,scan_interval=timedelta(seconds=30),entity_namespace=None)
    entity.add_to_platform_start(hass,platform,None)
    await entity.add_to_platform_finish()
    assert hass.states.get(entity.entity_id).state == "unavailable" and transport.calls == []
    await session.start()
    await until(lambda: session.read_count)
    assert hass.states.get(entity.entity_id).state != "unavailable"
    assert entity.extra_state_attributes["alternatives_not_simultaneous"] is True
    if ending == "stalled_read":
        transport.read_block = asyncio.Event()
        await until(lambda: session.safe)
        transport.read_block = None
    else:
        await session.stop()
    assert hass.states.get(entity.entity_id).state == "unavailable"
    await session.refresh_battery()
    await until(lambda: session.safe)
    assert hass.states.get(entity.entity_id).state == "unavailable"
    await entity.async_remove(force_remove=True)
    await hass.async_block_till_done()


def test_native_zero_vs_missing_and_identity_and_mount_status():
    entry = make_entry()
    entry.options.update(SETTINGS)
    entry.runtime_data = SimpleNamespace(fresh=True, mode="manual", measurement=Measurement(0,0,False,False,75))
    for key in LEVEL_KEYS:
        e = LevellingSensor(entry,key)
        assert e.available and e.native_value == 0 and not e.should_poll
        assert e.unique_id == entry.unique_id + "_" + key
    missing = make_entry()
    missing.runtime_data = entry.runtime_data
    assert not LevellingSensor(missing,"front_correction").available
    assert LevellingSensor(missing,"levelling_status").native_value == "dimensions_missing"
    assert LevellingSensor(entry,"mount_position").native_value == "front"
    entry.runtime_data.measurement = Measurement(655.35,0,False,False,75)
    assert not LevellingSensor(entry,"front_correction").available
    assert LevellingSensor(entry,"levelling_status").native_value == "unsupported_angle"


def test_caravan_icon_is_native_and_no_external_resource():
    from custom_components.xparkle_rvlevel.switch import MeasurementSwitch
    entry = make_entry();entry.runtime_data = SimpleNamespace()
    assert MeasurementSwitch(entry,"measurement").icon == "mdi:caravan"


def test_default_dashboard_uses_builtin_cards_and_only_explicit_actions():
    from pathlib import Path
    import yaml
    root=Path(__file__).parents[1]/"examples"
    text=(root/"levelling-card.yaml").read_text()
    card=yaml.safe_load(text)
    nodes=[]
    def walk(value):
        if isinstance(value,dict):
            nodes.append(value)
            for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(card)
    assert {x['type'] for x in nodes if 'type' in x}<={'vertical-stack','tile','toggle','entities'}
    assert not any(k in node for node in nodes for k in ('card_mod','style','styles','theme','resources'))
    assert 'custom:' not in text and 'javascript' not in text.lower()
    actions=[x for x in nodes if x.get('action')=='perform-action']
    assert len(actions)==1 and actions[0]['perform_action']=='button.press'
    assert actions[0]['target']['entity_id']=='button.example_keep_measuring'
    assert card['cards'][0]['entity']=='switch.example_measurement'


@pytest.mark.parametrize("field,value", [("vehicle_width_cm",501), ("vehicle_length_cm",2001),
    ("vehicle_length_cm",True), ("directions_confirmed",1), ("mount_position","bottom")])
def test_native_options_reject_invalid_new_values(field,value):
    from custom_components.xparkle_rvlevel.config_flow import OPTIONS_SCHEMA
    with pytest.raises(vol.Invalid):
        OPTIONS_SCHEMA({"battery_refresh_hours":24,"measurement_interval_seconds":2,**SETTINGS,field:value})
