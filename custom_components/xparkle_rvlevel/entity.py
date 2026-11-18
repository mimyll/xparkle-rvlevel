"""Push-only entities: state updates never request a sensor read."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class XparkleEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, key):
        self.session = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)}, name="Xparkle RV level",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.session.listen(self.async_write_ha_state))
