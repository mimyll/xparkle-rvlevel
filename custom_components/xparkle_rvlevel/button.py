"""Explicit activity renewal; pressing while off never opens a connection."""
from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import XparkleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([KeepMeasuringButton(entry, "keep_measuring")])


class KeepMeasuringButton(XparkleEntity, ButtonEntity):
    _attr_icon = "mdi:timer-refresh-outline"

    async def async_press(self):
        if not self.session.renew():
            raise HomeAssistantError(translation_domain="xparkle_rvlevel", translation_key="session_inactive")
