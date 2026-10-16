"""Maidenhead locators, distance and beam heading (for the callsign panel)."""
from __future__ import annotations

import math
import re

GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}(?:[A-X]{2})?$", re.I)
EARTH_KM = 6371.0


def grid_to_latlon(grid: str) -> tuple[float, float] | None:
    """Centre of a 4- or 6-character locator, or None."""
    g = (grid or "").strip()[:6]
    if len(g) not in (4, 6) or not GRID_RE.match(g):
        return None
    g = g[:2].upper() + g[2:4] + g[4:].lower()
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        lon += (ord(g[4]) - 97) * (5 / 60) + 2.5 / 60
        lat += (ord(g[5]) - 97) * (2.5 / 60) + 1.25 / 60
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def distance_bearing(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Great-circle distance (km) and initial bearing (degrees) from a to b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlo = lo2 - lo1
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    dist = 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return dist, (math.degrees(math.atan2(y, x)) + 360) % 360
