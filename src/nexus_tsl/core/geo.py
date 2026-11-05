"""Narzędzia geograficzne (bez zewnętrznych zależności)."""
from __future__ import annotations

import math

from .models import Location

EARTH_RADIUS_KM = 6371.0
# Współczynnik krętości dróg względem linii prostej (typowo 1.2-1.35 w Europie).
ROAD_FACTOR = 1.25


def haversine_km(a: Location, b: Location) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def road_km(a: Location, b: Location) -> float:
    """Przybliżony dystans drogowy. W produkcji: OSRM / GraphHopper / HERE."""
    return round(haversine_km(a, b) * ROAD_FACTOR, 1)


# Kilka punktów referencyjnych do demo i testów.
CITIES = {
    "warszawa": Location("Warszawa", 52.2297, 21.0122),
    "poznan": Location("Poznań", 52.4064, 16.9252),
    "wroclaw": Location("Wrocław", 51.1079, 17.0385),
    "gdansk": Location("Gdańsk", 54.3520, 18.6466),
    "krakow": Location("Kraków", 50.0647, 19.9450),
    "lodz": Location("Łódź", 51.7592, 19.4560),
    "katowice": Location("Katowice", 50.2649, 19.0238),
    "berlin": Location("Berlin", 52.5200, 13.4050, "DE"),
    "dortmund": Location("Dortmund", 51.5136, 7.4653, "DE"),
    "praga": Location("Praga", 50.0755, 14.4378, "CZ"),
    "tallinn": Location("Tallinn", 59.4370, 24.7536, "EE"),
}
