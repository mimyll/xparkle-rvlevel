"""Persistent UI tolerance; changes never dispatch Bluetooth operations."""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory
from .entity import XparkleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ToleranceNumber(entry)])


class ToleranceNumber(XparkleEntity, NumberEntity):
    _attr_native_min_value = 0.05
    _attr_native_max_value = 5
    _attr_native_step = 0.05
    _attr_native_unit_of_measurement = "cm"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:spirit-level"

    def __init__(self, entry):
        super().__init__(entry, "level_tolerance_cm")
        self.entry = entry

    @property
    def native_value(self):
        return self.entry.options.get("level_tolerance_cm", 0.25)

    async def async_set_native_value(self, value):
        from .config_flow import _finite_range
        value = _finite_range(0.05, 5)(value)
        self.hass.config_entries.async_update_entry(self.entry,
            options={**self.entry.options, "level_tolerance_cm": value})
