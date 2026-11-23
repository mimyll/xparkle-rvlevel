"""Explicit allowlist: no names, addresses, payloads or exception text."""


async def async_get_config_entry_diagnostics(hass, entry):
    from .compatibility import runtime_versions, runtime_review_status
    session = entry.runtime_data
    versions = runtime_versions(hass)
    return {
        "runtime_versions": versions,
        "runtime_review_status": runtime_review_status(versions),
        "runtime_admission_policy": "required_capabilities_not_core_version",
        "adapter_selection": "home_assistant_automatic",
        "session_status": session.status,
        "stop_reason": session.reason,
        "requested": session.requested,
        "mode": session.mode,
        "connected": session.connected if session.status != "cleanup_unknown" else None,
        "owned_operations_pending": session.pending_operations,
        "session_task_pending": session.busy,
        "cleanup_confirmed": session.cleanup_confirmed,
        "read_count": session.read_count,
        "connection_attempts": session.connection_attempts,
        "auto_stop_seconds": 600,
        "poll_interval_seconds": session.limits.poll_interval,
        "battery_refresh_hours": entry.options.get("battery_refresh_hours", 24),
        "battery_last_received": session.battery_received_at.isoformat() if session.battery_received_at else None,
        "last_received": session.received_at.isoformat() if session.received_at else None,
        "sensor_sample_age": "unknown",
        "physical_direction_mapping": "unverified",
        "cadence": "start_to_start_no_catchup_min_quiet_gap_20ms",
        "fresh_timeout_seconds": session.fresh_timeout,
        "timing_sample_limit": 256,
        "read_duration_seconds": list(session.read_durations),
        "sample_interval_seconds": list(session.sample_intervals),
        "speed_test_report": session.speed_report,
    }
