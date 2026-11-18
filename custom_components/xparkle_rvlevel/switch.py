"""Explicit measurement switch, deliberately never restored as on."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import XparkleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MeasurementSwitch(entry, "measurement")])


class MeasurementSwitch(XparkleEntity, SwitchEntity):
    _attr_icon = "mdi:caravan"

    @property
    def is_on(self):
        return self.session.mode == "manual" and self.session.requested

    async def async_turn_on(self, **kwargs):
        if self.is_on:
            if not self.session.renew():
                raise HomeAssistantError(translation_domain="xparkle_rvlevel", translation_key="session_inactive")
            return
        if not await self.session.start():
            raise HomeAssistantError(translation_domain="xparkle_rvlevel", translation_key="cleanup_pending")

    async def async_turn_off(self, **kwargs):
        if not await self.session.stop():
            raise HomeAssistantError(translation_domain="xparkle_rvlevel", translation_key="cleanup_pending")
