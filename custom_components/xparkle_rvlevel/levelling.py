"""Advisory rigid-span geometry; no HA, device settings or transport I/O."""
from dataclasses import dataclass
from math import isfinite, radians, sin

MOUNT_POSITIONS = ("not_set", "front", "rear", "right", "left")
GEOMETRY_DEFAULTS = {"vehicle_width_cm": 0, "vehicle_length_cm": 0,
                     "mount_position": "not_set", "directions_confirmed": False}
CORRECTION_KEYS = ("front_correction", "rear_correction", "left_correction", "right_correction")
CORNER_KEYS = ("front_left_raise", "front_right_raise", "rear_left_raise", "rear_right_raise")
DISTANCE_KEYS = ("longitudinal_difference", "transverse_difference")


def dimension(value, maximum, *, allow_unset=False):
    if type(value) not in (int, float) or not 0 <= value <= maximum or not isfinite(value):
        raise ValueError("invalid_geometry")
    if allow_unset and value == 0:
        return value
    if not 1 <= value <= maximum:
        raise ValueError("invalid_geometry")
    return value


def height_difference(span_cm, angle):
    """Span is measured along the rigid body, not its horizontal projection."""
    if type(angle) not in (int, float) or not 0 <= angle <= 45 or not isfinite(angle):
        raise ValueError("unsupported_angle")
    return dimension(span_cm, 2000) * 10 * sin(radians(angle))


def corrections(longitudinal_mm, transverse_mm):
    """Positive gaps mean front/left high. Opposite-end moves are alternatives.

    Corner values are raise-only relative reference-point estimates anchored
    to the current highest reference corner, not jack/steady instructions.
    """
    if any(type(x) not in (int, float) or not isfinite(x)
           for x in (longitudinal_mm, transverse_mm)):
        raise ValueError("invalid_geometry")
    p, r = longitudinal_mm, transverse_mm
    result = dict(zip(CORRECTION_KEYS, (-p, p, -r, r)))
    corners = ((p+r)/2, (p-r)/2, (-p+r)/2, (-p-r)/2)
    high = max(corners)
    result.update(zip(CORNER_KEYS, (max(0., high-v) for v in corners)))
    return result


@dataclass(frozen=True)
class Geometry:
    width_cm: float
    length_cm: float
    mount_position: str
    directions_confirmed: bool

    @classmethod
    def from_options(cls, options):
        values = {**GEOMETRY_DEFAULTS, **options}
        width = dimension(values["vehicle_width_cm"], 500, allow_unset=True)
        length = dimension(values["vehicle_length_cm"], 2000, allow_unset=True)
        mount = values["mount_position"]
        confirmed = values["directions_confirmed"]
        if mount not in MOUNT_POSITIONS or type(confirmed) is not bool:
            raise ValueError("invalid_geometry")
        if confirmed and (not width or not length or mount == "not_set"):
            raise ValueError("invalid_geometry")
        return cls(width, length, mount, confirmed)

    def values(self, measurement):
        """Do not rotate finished device axes based on a mounting-side label."""
        values = {}
        if self.length_cm:
            values["longitudinal_difference"] = height_difference(self.length_cm, measurement.pitch_magnitude)
        if self.width_cm:
            values["transverse_difference"] = height_difference(self.width_cm, measurement.roll_magnitude)
        if self.directions_confirmed and len(values) == 2:
            p = values["longitudinal_difference"] * (1 if measurement.uphill else -1)
            r = values["transverse_difference"] * (-1 if measurement.left_tilt else 1)
            values.update(corrections(p, r))
        return values
