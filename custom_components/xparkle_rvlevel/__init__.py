"""User-controlled RV level measurement; setup always leaves BLE idle."""
from .const import DOMAIN, PLATFORMS, CONF_ADDRESS, CONF_POLL_SECONDS, DEFAULT_OPTIONS
from .session import Session, Limits


def _config_schema(config):
    """Apply native config-entry-only validation while keeping protocol imports pure."""
    from homeassistant.helpers import config_validation as cv
    return cv.config_entry_only_config_schema(DOMAIN)(config)


CONFIG_SCHEMA = _config_schema


async def async_setup(hass, config):
    """Expose only the versioned, public, identifier-free card file."""
    from pathlib import Path
    from homeassistant.components.http import StaticPathConfig
    await hass.http.async_register_static_paths([StaticPathConfig(
        "/xparkle_rvlevel/0.6.0/xparkle-card.js",
        str(Path(__file__).parent / "frontend" / "xparkle-card.js"), True)])
    from .card import XparkleCardView
    hass.http.register_view(XparkleCardView())
    from .speed_test import register_speed_test
    register_speed_test(hass)
    return True


async def async_setup_entry(hass, entry):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
    from .transport import HATransport
    from .runtime import Owner, domain_state, battery_store, restore_battery, register_schedule
    from .config_flow import OPTIONS_SCHEMA
    from homeassistant.exceptions import ConfigEntryNotReady
    from .compatibility import async_load_runtime_versions
    await async_load_runtime_versions(hass)
    state = domain_state(hass)
    address = entry.data[CONF_ADDRESS].upper()
    old_owner = state.owners.get(address)
    previous = old_owner.session if old_owner else getattr(entry, "runtime_data", None)
    if previous is not None and not await previous.shutdown():
        raise ConfigEntryNotReady("Previous measurement cleanup is unconfirmed")
    if state.owners.get(address) is not old_owner:
        raise ConfigEntryNotReady("Measurement ownership changed during setup")
    if old_owner is not None:
        old_owner.detach()
    options = OPTIONS_SCHEMA({**DEFAULT_OPTIONS, **entry.options})
    from .const import UI_DEFAULTS
    from .levelling import Geometry, GEOMETRY_DEFAULTS
    Geometry.from_options(options)
    session = Session(lambda: HATransport(hass, entry.data),
                      limits=Limits(poll_interval=options[CONF_POLL_SECONDS]),
                      admission_enabled=False,
                      create_task=lambda coro: hass.async_create_background_task(
                          coro, "Xparkle measurement session", eager_start=False))
    entry.runtime_data = session
    owner = Owner(entry.entry_id, session)
    state.owners[address] = owner
    forwarding_started = False
    try:
        store = battery_store(hass, entry)
        restore_battery(session, await store.async_load())
        last_saved = session.battery_received_at

        def battery_updated():
            nonlocal last_saved
            if session.battery_received_at is not None and session.battery_received_at != last_saved:
                last_saved = session.battery_received_at
                pair = {"value": session.battery, "received_at": session.battery_received_at.isoformat()}
                store.async_delay_save(lambda: pair, 60)

        owner.callbacks.append(session.listen(battery_updated))

        async def shutdown(event):
            await session.shutdown()

        owner.stop_listener = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)
        forwarding_started = True
        await hass.config_entries.async_forward_entry_setups(entry, [Platform(p) for p in PLATFORMS])
        owner.callbacks.append(register_schedule(hass, entry, session))

        effective_defaults = {**DEFAULT_OPTIONS, **GEOMETRY_DEFAULTS, **UI_DEFAULTS}
        previous_options = options

        async def options_updated(hass, entry):
            nonlocal previous_options
            current = {**effective_defaults, **entry.options}
            changed = {key for key in previous_options.keys() | current.keys()
                       if previous_options.get(key) != current.get(key)}
            previous_options = current
            if changed <= {"level_tolerance_cm", "longitudinal_tolerance_cm", "vehicle_type"}:
                # Presentation changes never restart or renew a live session.
                session._emit()
            else:
                await hass.config_entries.async_reload(entry.entry_id)

        owner.callbacks.append(entry.add_update_listener(options_updated))
        if hass.is_stopping:
            raise ConfigEntryNotReady("Home Assistant is stopping")
    except BaseException:
        owner.detach()
        await session.shutdown()
        if forwarding_started:
            await hass.config_entries.async_unload_platforms(entry, [Platform(p) for p in PLATFORMS])
        raise
    entry.async_on_unload(owner.detach)
    session.admission_enabled = True
    return True


async def async_unload_entry(hass, entry):
    from homeassistant.const import Platform
    from .runtime import flush_battery
    # Reject unload while an owned backend operation/link remains unsettled.
    # The listener and runtime stay attached for a later cleanup attempt.
    if not await entry.runtime_data.shutdown():
        return False
    await flush_battery(hass, entry, entry.runtime_data)
    return await hass.config_entries.async_unload_platforms(entry, [Platform(p) for p in PLATFORMS])


async def async_remove_entry(hass, entry):
    from .runtime import domain_state, remove_battery
    address = entry.data[CONF_ADDRESS].upper()
    state = domain_state(hass)
    owner = state.owners.get(address)
    if owner is not None and owner.entry_id == entry.entry_id:
        # HA removes entries even after failed unload. Stop producers now,
        # but keep unsafe ownership and its shutdown listener outside entry data.
        owner.detach(keep_stop=True)
        if await owner.session.shutdown():
            owner.detach()
            if state.owners.get(address) is owner:
                state.owners.pop(address)
    await remove_battery(hass, entry)
