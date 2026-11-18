"""Source-derived read-only RV level protocol, independent of Home Assistant."""
from dataclasses import dataclass

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
READ_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True, slots=True)
class Measurement:
    """Unsigned magnitudes and protocol flags; physical signs are unverified."""

    pitch_magnitude: float
    roll_magnitude: float
    uphill: bool
    left_tilt: bool
    battery: int | None


def decode(data: bytes) -> Measurement:
    """Decode the established prefix, accepting unparsed trailing bytes."""
    if len(data) < 7 or data[0] not in (0, 1) or data[3] not in (0, 1):
        raise ValueError("unsupported_payload")
    return Measurement(
        int.from_bytes(data[1:3], "big") / 100,
        int.from_bytes(data[4:6], "big") / 100,
        bool(data[0]), bool(data[3]), data[6] if data[6] <= 100 else None,
    )
