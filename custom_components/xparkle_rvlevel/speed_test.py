"""Authenticated administrator-only fixed read timing diagnostic."""
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service
from .const import DOMAIN


def register_speed_test(hass):
    async def run(call):
        # Internal/automation contexts must not launch the one-shot radio test.
        if not call.context.user_id:
            raise ServiceValidationError("An authenticated administrator is required")
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain != DOMAIN or entry.disabled_by is not None or entry.state != ConfigEntryState.LOADED:
            raise ServiceValidationError("The selected integration is not ready")
        session = entry.runtime_data
        result = await session.test_update_speed()
        if result is None:
            raise ServiceValidationError("Measurement is busy or cleanup is unconfirmed")
        return result

    async_register_admin_service(hass, DOMAIN, "test_update_speed", run,
        schema=vol.Schema({vol.Required("entry_id"): str}),
        supports_response=SupportsResponse.ONLY)
