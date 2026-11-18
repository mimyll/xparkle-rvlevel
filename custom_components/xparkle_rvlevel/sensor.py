"""Magnitudes, battery and explicit session timing/state."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory

from .entity import XparkleEntity
from .levelling import Geometry, DISTANCE_KEYS, CORRECTION_KEYS, CORNER_KEYS, MOUNT_POSITIONS

LEVEL_KEYS = (*DISTANCE_KEYS, *CORRECTION_KEYS, *CORNER_KEYS)

VALUE_KEYS = ("pitch_magnitude", "roll_magnitude", "battery")
STATUS_OPTIONS = ("idle", "connecting", "measuring", "stopping", "error", "cleanup_unknown")


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([XparkleSensor(entry, key) for key in
                        (*VALUE_KEYS, "session_status", "last_received", "expires_at")])
    async_add_entities([LevellingSensor(entry, key) for key in (*LEVEL_KEYS, "mount_position", "levelling_status")])


class XparkleSensor(XparkleEntity, SensorEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        self.entry = entry
        if key in VALUE_KEYS:
            self._attr_native_unit_of_measurement = PERCENTAGE if key == "battery" else "°"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if key == "battery":
                self._attr_device_class = SensorDeviceClass.BATTERY
            else:
                self._attr_suggested_display_precision = 2
        elif key in ("last_received", "expires_at"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(STATUS_OPTIONS)
            self._attr_icon = "mdi:caravan"

    @property
    def available(self):
        if self.key == "battery":
            return self.session.battery is not None
        return self.session.fresh if self.key in VALUE_KEYS else True

    @property
    def native_value(self):
        if self.key == "battery":
            return self.session.battery
        if self.key in VALUE_KEYS:
            return getattr(self.session.measurement, self.key, None)
        if self.key == "last_received":
            return self.session.received_at
        if self.key == "expires_at":
            return self.session.expires_at
        return self.session.status

    @property
    def extra_state_attributes(self):
        if self.key == "session_status":
            return {"stop_reason": self.session.reason,
                    "mode": self.session.mode,
                    "auto_stop_minutes": 10,
                    "sensor_sample_age": "unknown"}
        if self.key in ("pitch_magnitude", "roll_magnitude"):
            return {"physical_direction_mapping": "unverified", "sensor_sample_age": "unknown"}
        if self.key == "battery":
            return {"last_received": self.session.battery_received_at.isoformat()
                    if self.session.battery_received_at else None,
                    "cached": not (self.session.fresh and self.session.measurement is not None
                                   and self.session.measurement.battery is not None
                                   and self.session.battery_received_at == self.session.received_at),
                    "sensor_sample_age": "unknown"}
        return None


class LevellingSensor(XparkleEntity, SensorEntity):
    """Calculated advice is never a reason to acquire or renew a measurement."""

    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        self.entry = entry
        self.geometry = Geometry.from_options(entry.options)
        self._attr_icon = "mdi:caravan" if key == "levelling_status" else "mdi:arrow-up-down"
        if key in LEVEL_KEYS:
            self._attr_native_unit_of_measurement = "mm"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 0
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_options = (list(MOUNT_POSITIONS) if key == "mount_position" else
                ["dimensions_missing", "mount_missing", "directions_unconfirmed", "no_measurement", "unsupported_angle", "ready"])
            if key == "mount_position":
                self._attr_icon = "mdi:map-marker"

    def _values(self):
        if not self.session.fresh or self.session.mode != "manual" or self.session.measurement is None:
            return {}
        try:
            return self.geometry.values(self.session.measurement)
        except ValueError:
            return {}

    @property
    def available(self):
        return self.key not in LEVEL_KEYS or self.key in self._values()

    @property
    def native_value(self):
        if self.key == "mount_position":
            return self.geometry.mount_position
        if self.key == "levelling_status":
            if not self.geometry.width_cm or not self.geometry.length_cm:
                return "dimensions_missing"
            if self.geometry.mount_position == "not_set":
                return "mount_missing"
            if not self.geometry.directions_confirmed:
                return "directions_unconfirmed"
            if not self.session.fresh or self.session.mode != "manual":
                return "no_measurement"
            return "ready" if self._values() else "unsupported_angle"
        value = self._values().get(self.key)
        return round(value) if value is not None else None

    @property
    def extra_state_attributes(self):
        if self.key == "levelling_status":
            from .const import UI_DEFAULTS
            session = self.session
            # Both axes and freshness belong to one immutable read sample.
            values = self._values()
            tolerance = self.entry.options.get("level_tolerance_cm", UI_DEFAULTS["level_tolerance_cm"])
            ready = self.native_value == "ready"
            return {"entry_id": self.entry.entry_id,
                "vehicle_type": self.entry.options.get("vehicle_type", UI_DEFAULTS["vehicle_type"]),
                "level_tolerance_cm": tolerance,
                "mount_position": self.geometry.mount_position,
                "width_cm": self.geometry.width_cm, "length_cm": self.geometry.length_cm,
                "directions_confirmed": self.geometry.directions_confirmed,
                "session_status": session.status,
                "mode": session.mode,
                "received_at": session.received_at.isoformat() if session.received_at else None,
                "sequence": session._sample_sequence,
                "session_id": session.identifier,
                "fresh_timeout_seconds": session.fresh_timeout,
                "poll_interval_seconds": session.limits.poll_interval,
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
                "longitudinal_mm": -values["front_correction"] if ready else None,
                "transverse_mm": -values["left_correction"] if ready else None,
                "within_tolerance": (values["longitudinal_difference"] <= tolerance * 10
                    and values["transverse_difference"] <= tolerance * 10) if ready else None,
                "sensor_sample_age": "unknown"}
        if self.key not in LEVEL_KEYS:
            return None
        result = {"estimate": True, "sensor_sample_age": "unknown",
                  "width_cm": self.geometry.width_cm, "length_cm": self.geometry.length_cm,
                  "mount_position": self.geometry.mount_position,
                  "direction_basis": "user_confirmed_current_output" if self.geometry.directions_confirmed else "unconfirmed"}
        if self.key in CORRECTION_KEYS:
            result.update({"positive": "raise", "negative": "lower",
                           "reference": "opposite_reference_point_fixed", "alternatives_not_simultaneous": True})
        elif self.key in CORNER_KEYS:
            result["reference"] = "current_highest_reference_corner"
        else:
            result["reference"] = "unsigned_vertical_difference_across_rigid_span"
        return result
