"""Native delayed scheduling and cached battery persistence, without radio I/O."""
from datetime import datetime, timedelta, timezone
import asyncio
from dataclasses import dataclass, field
from collections.abc import Callable

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import CONF_BATTERY_HOURS, DEFAULT_OPTIONS, DOMAIN
from .session import Session


@dataclass
class Owner:
    """Keep target ownership beyond removal of its native config entry."""

    entry_id: str
    session: Session
    callbacks: list[Callable[[], None]] = field(default_factory=list)
    stop_listener: Callable[[], None] | None = None

    def detach(self, *, keep_stop: bool = False):
        """Detach producers before cache removal, retaining uncertain teardown."""
        while self.callbacks:
            self.callbacks.pop()()
        if not keep_stop and self.stop_listener is not None:
            self.stop_listener()
            self.stop_listener = None


@dataclass
class DomainState:
    owners: dict[str, Owner] = field(default_factory=dict)
    stores: dict[str, Store] = field(default_factory=dict)
    runtime_versions: dict[str, str] | None = None
    runtime_versions_future: asyncio.Future | None = None


def domain_state(hass):
    """HA-lifetime ownership cannot be erased by deleting a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = DomainState()
    return hass.data[DOMAIN]


def battery_store(hass, entry):
    stores = domain_state(hass).stores
    if entry.entry_id not in stores:
        stores[entry.entry_id] = Store(hass, 1, f"{DOMAIN}_battery_{entry.entry_id}",
                                       private=True, atomic_writes=True)
    return stores[entry.entry_id]


async def flush_battery(hass, entry, session):
    """Flush through the original Store to cancel its own delayed writer."""
    if session.battery is not None and session.battery_received_at is not None:
        await battery_store(hass, entry).async_save({"value": session.battery,
            "received_at": session.battery_received_at.isoformat()})


async def remove_battery(hass, entry):
    store = battery_store(hass, entry)
    await store.async_remove()
    domain_state(hass).stores.pop(entry.entry_id, None)


def restore_battery(session, data):
    """Accept a valid value and original aware timestamp as one pair."""
    if not isinstance(data, dict) or set(data) != {"value", "received_at"}:
        return
    value = data["value"]
    if type(value) is not int or not 0 <= value <= 100:
        return
    try:
        received = datetime.fromisoformat(data["received_at"])
        if received.tzinfo is None or received > datetime.now(timezone.utc):
            return
    except (ValueError, TypeError):
        return
    session.battery, session.battery_received_at = value, received


def register_schedule(hass, entry, session):
    """First attempt is one complete interval later; skip, never queue."""
    hours = entry.options.get(CONF_BATTERY_HOURS, DEFAULT_OPTIONS[CONF_BATTERY_HOURS])
    if not hours:
        return lambda: None

    async def refresh(now):
        await session.refresh_battery()

    return async_track_time_interval(hass, refresh, timedelta(hours=hours), cancel_on_shutdown=True)
