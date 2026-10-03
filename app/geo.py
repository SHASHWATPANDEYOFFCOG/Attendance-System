"""Geofence check for mobile and QR attendance.

The browser reports a position and an accuracy radius. A student is inside when the centre of
their reported circle is within the fence radius, allowing for the reading's own uncertainty only
up to a cap — otherwise a deliberately vague reading ("somewhere within 5 km") would pass. A
reading less precise than `geo_max_accuracy_m` is refused outright with a clear message.

This raises the bar; it is not proof of location (a determined student can spoof GPS), which is
why the face match and the rotating classroom code are separate, independent checks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

EARTH_RADIUS_M = 6_371_008.8
ACCURACY_ALLOWANCE_CAP_M = 50.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class GeoResult:
    ok: bool
    reason: str
    distance_m: Optional[float] = None


def check_location(*, enabled: bool, center_lat: Optional[float], center_lng: Optional[float],
                   radius_m: float, max_accuracy_m: float, lat: Optional[float],
                   lng: Optional[float], accuracy_m: Optional[float]) -> GeoResult:
    if not enabled:
        return GeoResult(True, "geofence disabled")
    if center_lat is None or center_lng is None:
        # Fail closed: an enabled fence with no centre would otherwise accept everyone.
        return GeoResult(False, "The campus location has not been configured yet. Ask your "
                                "teacher to mark you, or the administrator to set it.")
    if lat is None or lng is None:
        return GeoResult(False, "Your location is needed to mark attendance. Allow location "
                                "access and try again.")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return GeoResult(False, "That location reading is not valid.")
    acc = float(accuracy_m) if accuracy_m is not None else max_accuracy_m
    if acc > max_accuracy_m:
        return GeoResult(False, f"Your location is too imprecise (±{acc:.0f} m). Turn on GPS / "
                                f"precise location, step near a window, and try again.")
    d = haversine_m(center_lat, center_lng, lat, lng)
    if d - min(acc, ACCURACY_ALLOWANCE_CAP_M) > radius_m:
        return GeoResult(False, f"You are outside campus ({d:.0f} m from the classroom area; "
                                f"allowed {radius_m:.0f} m).", d)
    return GeoResult(True, "inside geofence", d)
