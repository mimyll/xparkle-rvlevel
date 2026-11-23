"""Observed metadata is cached off-loop, never a Home Assistant version gate."""
import asyncio
from importlib.metadata import PackageNotFoundError, version

PACKAGES = ("homeassistant", "habluetooth", "bleak", "bleak-esphome", "aioesphomeapi")
BASELINE = {"homeassistant": "2026.11.0", "habluetooth": "7.1.2",
            "bleak-esphome": "4.0.0", "aioesphomeapi": "46.25.0"}


def _collect_versions():
    """Filesystem-backed discovery; call only through HA's executor."""
    result = {}
    for package in PACKAGES:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not_installed"
        except Exception:
            result[package] = "unavailable"
    return result


def runtime_versions(hass=None):
    """Return a detached snapshot, with no metadata or scanner I/O."""
    from .runtime import domain_state
    snapshot = domain_state(hass).runtime_versions if hass is not None else None
    return dict(snapshot) if snapshot is not None else dict.fromkeys(PACKAGES, "unavailable")


async def async_load_runtime_versions(hass):
    """Share one HA-lifetime executor job, including concurrent entry setup."""
    from .runtime import domain_state
    state = domain_state(hass)
    if state.runtime_versions is None:
        try:
            if state.runtime_versions_future is None:
                state.runtime_versions_future = hass.async_add_executor_job(_collect_versions)
            snapshot = await asyncio.shield(state.runtime_versions_future)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            snapshot = dict.fromkeys(PACKAGES, "unavailable")
        except Exception:
            snapshot = dict.fromkeys(PACKAGES, "unavailable")
        state.runtime_versions = dict(snapshot)
    return runtime_versions(hass)


def runtime_review_status(versions):
    """Evidence label only: an untested version is not incompatible."""
    if any(versions.get(p) in (None, "unavailable", "not_installed") for p in PACKAGES):
        return "metadata_unavailable"
    if all(versions.get(p) == v for p, v in BASELINE.items()) and versions.get("bleak") in ("3.0.2", "3.1.0"):
        return "matches_recorded_versions"
    return "untested_runtime"
