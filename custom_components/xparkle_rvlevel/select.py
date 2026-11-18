"""Persistent illustration selection; no device configuration command."""
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from .const import VEHICLE_TYPES
from .entity import XparkleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VehicleSelect(entry)])


class VehicleSelect(XparkleEntity, SelectEntity):
    _attr_options = list(VEHICLE_TYPES)
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:caravan"

    def __init__(self, entry):
        super().__init__(entry, "vehicle_type")
        self.entry = entry

    @property
    def current_option(self):
        return self.entry.options.get("vehicle_type", "caravan")

    async def async_select_option(self, option):
        if option not in VEHICLE_TYPES:
            raise ValueError("invalid_vehicle_type")
        self.hass.config_entries.async_update_entry(self.entry,
            options={**self.entry.options, "vehicle_type": option})
