"""Integration constants; no private target identifiers."""
DOMAIN = "xparkle_rvlevel"
CONF_ADDRESS = "address"
CONF_EXPECTED_NAME = "expected_name"
CONF_BATTERY_HOURS = "battery_refresh_hours"
CONF_POLL_SECONDS = "measurement_interval_seconds"
DEFAULT_OPTIONS = {CONF_BATTERY_HOURS: 24, CONF_POLL_SECONDS: 0.5}
UI_DEFAULTS = {"level_tolerance_cm": 0.25, "vehicle_type": "caravan"}
VEHICLE_TYPES = ("caravan", "tandem", "motorhome", "van")
PLATFORMS = ("switch", "button", "sensor", "binary_sensor", "number", "select")
