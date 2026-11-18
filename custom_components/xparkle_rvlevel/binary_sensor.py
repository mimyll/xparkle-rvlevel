"""Connection state and protocol direction flags kept separate from angles."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.entity import EntityCategory

from .entity import XparkleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([XparkleBinarySensor(entry, key) for key in ("connected", "uphill", "left_tilt")])


class XparkleBinarySensor(XparkleEntity, BinarySensorEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        if key == "connected":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        if self.key == "connected":
            return self.session.status != "cleanup_unknown"
        return self.session.fresh

    @property
    def is_on(self):
        if self.key == "connected":
            return self.session.connected
        return getattr(self.session.measurement, self.key, None)
