"""Native setup binds a private target without making a BLE connection."""
import re

import voluptuous as vol
from homeassistant import config_entries

from .const import (CONF_ADDRESS, CONF_EXPECTED_NAME, DOMAIN, CONF_BATTERY_HOURS,
                    CONF_POLL_SECONDS, DEFAULT_OPTIONS, UI_DEFAULTS, VEHICLE_TYPES)
from homeassistant.core import callback
from .levelling import Geometry, GEOMETRY_DEFAULTS, MOUNT_POSITIONS
from homeassistant.helpers import selector


def _address(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
        raise vol.Invalid("invalid_target")
    return value.upper()


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:RVLevel|RVbalance)-[0-9a-fA-F]{4}", value):
        raise vol.Invalid("invalid_target")
    return value


INPUT_SCHEMA = vol.Schema({vol.Required(CONF_ADDRESS): _address,
                          vol.Required(CONF_EXPECTED_NAME): _name})
FORM_SCHEMA = vol.Schema({vol.Required(CONF_ADDRESS): str,
                         vol.Required(CONF_EXPECTED_NAME): str})


class XparkleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return XparkleOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = INPUT_SCHEMA(user_input)
            except vol.Invalid:
                errors["base"] = "invalid_target"
            else:
                await self.async_set_unique_id(data[CONF_ADDRESS])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Xparkle RV level", data=data)
        return self.async_show_form(step_id="user", data_schema=FORM_SCHEMA, errors=errors)


def _integer_in_range(low, high):
    def validate(value):
        if type(value) is not int or not low <= value <= high:
            raise vol.Invalid("invalid_options")
        return value
    return validate


def _dimension(maximum):
    from .levelling import dimension
    def validate(value):
        try:
            return dimension(value, maximum, allow_unset=True)
        except ValueError as err:
            raise vol.Invalid("invalid_geometry") from err
    return validate


def _boolean(value):
    if type(value) is not bool:
        raise vol.Invalid("invalid_geometry")
    return value


def _finite_range(low, high):
    from math import isfinite
    def validate(value):
        if type(value) not in (int, float) or not low <= value <= high or not isfinite(value):
            raise vol.Invalid("invalid_options")
        return value
    return validate


OPTIONS_SCHEMA = vol.Schema({vol.Required(CONF_BATTERY_HOURS): _integer_in_range(0, 168),
                            vol.Required(CONF_POLL_SECONDS): _finite_range(0.1, 10),
    vol.Optional("level_tolerance_cm", default=0.25): _finite_range(0.05, 5),
    vol.Optional("longitudinal_tolerance_cm", default=UI_DEFAULTS["longitudinal_tolerance_cm"]): _finite_range(0.05, 5),
    vol.Optional("vehicle_type", default="caravan"): vol.In(VEHICLE_TYPES),
    vol.Optional("vehicle_width_cm", default=0): _dimension(500),
    vol.Optional("vehicle_length_cm", default=0): _dimension(2000),
    vol.Optional("mount_position", default="not_set"): vol.In(MOUNT_POSITIONS),
    vol.Optional("directions_confirmed", default=False): _boolean})


class XparkleOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                options = OPTIONS_SCHEMA(user_input)
                previous_mount = self.config_entry.options.get("mount_position", "not_set")
                if options["mount_position"] != previous_mount:
                    # A location change can never carry over direction confirmation.
                    options["directions_confirmed"] = False
                Geometry.from_options(options)
            except (vol.Invalid, ValueError):
                errors["base"] = "invalid_options"
            else:
                return self.async_create_entry(title="", data=options)
        current = {**DEFAULT_OPTIONS, **GEOMETRY_DEFAULTS, **UI_DEFAULTS, **self.config_entry.options}
        schema = vol.Schema({vol.Required(CONF_BATTERY_HOURS, default=current[CONF_BATTERY_HOURS]): int,
            vol.Required(CONF_POLL_SECONDS, default=current[CONF_POLL_SECONDS]): selector.NumberSelector(selector.NumberSelectorConfig(min=0.1, max=10, step=0.05, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="s")),
            vol.Required("level_tolerance_cm", default=current["level_tolerance_cm"]): selector.NumberSelector(selector.NumberSelectorConfig(min=0.05, max=5, step=0.05, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="cm")),
            vol.Required("longitudinal_tolerance_cm", default=current["longitudinal_tolerance_cm"]): selector.NumberSelector(selector.NumberSelectorConfig(min=0.05, max=5, step=0.05, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="cm")),
            vol.Required("vehicle_type", default=current["vehicle_type"]): selector.SelectSelector(selector.SelectSelectorConfig(options=list(VEHICLE_TYPES), translation_key="vehicle_type", mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Required("vehicle_width_cm", default=current["vehicle_width_cm"]): selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=500, step=0.1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="cm")),
            vol.Required("vehicle_length_cm", default=current["vehicle_length_cm"]): selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=2000, step=0.1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="cm")),
            vol.Required("mount_position", default=current["mount_position"]): selector.SelectSelector(selector.SelectSelectorConfig(options=list(MOUNT_POSITIONS), translation_key="mount_position", mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Required("directions_confirmed", default=current["directions_confirmed"]): bool})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
