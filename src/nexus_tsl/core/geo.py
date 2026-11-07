"""Narzędzia geograficzne: dystanse drogowe z OSRM lub przybliżenie offline."""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from functools import lru_cache

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


log = logging.getLogger(__name__)


class Router:
    """Źródło dystansów drogowych. Bazowo: przybliżenie z ortodromy."""

    source = "haversine"

    def km(self, a: Location, b: Location) -> float:
        return road_km(a, b)

    def duration_h(self, a: Location, b: Location, avg_speed_kmh: float = 70.0) -> float:
        return round(self.km(a, b) / avg_speed_kmh, 2)


class OSRMRouter(Router):
    """Prawdziwe dystanse po drogach z serwera OSRM (Open Source Routing Machine).

    Własny serwer: `docker compose --profile osrm up` (patrz docs/OSRM.md).
    Przy błędzie sieci lub braku trasy wraca do przybliżenia, więc platforma
    nie przestaje działać, a pole `source` pokazuje, skąd pochodzi wynik.
    """

    def __init__(self, base_url: str, timeout_s: float = 5.0, profile: str = "driving") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.profile = profile
        self.fallbacks = 0
        self._route = lru_cache(maxsize=4096)(self._fetch)

    @property
    def source(self) -> str:  # type: ignore[override]
        return "osrm" if self.fallbacks == 0 else f"osrm (fallback x{self.fallbacks})"

    def _fetch(self, lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float] | None:
        url = f"{self.base_url}/route/v1/{self.profile}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=false"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as resp:   # noqa: S310 - URL z konfiguracji
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            log.warning("OSRM niedostępny (%s), używam przybliżenia", e)
            return None
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        r = data["routes"][0]
        return r["distance"] / 1000, r["duration"] / 3600

    def _get(self, a: Location, b: Location) -> tuple[float, float] | None:
        res = self._route(round(a.lat, 5), round(a.lon, 5), round(b.lat, 5), round(b.lon, 5))
        if res is None:
            self.fallbacks += 1
        return res

    def km(self, a: Location, b: Location) -> float:
        if a == b:
            return 0.0
        res = self._get(a, b)
        return round(res[0], 1) if res else road_km(a, b)

    def duration_h(self, a: Location, b: Location, avg_speed_kmh: float = 70.0) -> float:
        res = self._get(a, b) if a != b else (0.0, 0.0)
        # OSRM liczy czas dla samochodu osobowego; ciężarówka jest wolniejsza (~x1.25).
        return round(res[1] * 1.25, 2) if res else super().duration_h(a, b, avg_speed_kmh)


def get_router() -> Router:
    url = os.getenv("NEXUS_OSRM_URL")
    return OSRMRouter(url) if url else Router()


# Punkty referencyjne do demo i testów. W produkcji: geokodowanie (Nominatim, HERE, Google).
CITIES = {
    "warszawa": Location("Warszawa", 52.2297, 21.0122),
    "poznan": Location("Poznań", 52.4064, 16.9252),
    "wroclaw": Location("Wrocław", 51.1079, 17.0385),
    "gdansk": Location("Gdańsk", 54.3520, 18.6466),
    "krakow": Location("Kraków", 50.0647, 19.9450),
    "lodz": Location("Łódź", 51.7592, 19.4560),
    "katowice": Location("Katowice", 50.2649, 19.0238),
    "szczecin": Location("Szczecin", 53.4285, 14.5528),
    "bydgoszcz": Location("Bydgoszcz", 53.1235, 18.0084),
    "lublin": Location("Lublin", 51.2465, 22.5684),
    "rzeszow": Location("Rzeszów", 50.0412, 21.9991),
    "bialystok": Location("Białystok", 53.1325, 23.1688),
    "berlin": Location("Berlin", 52.5200, 13.4050, "DE"),
    "hamburg": Location("Hamburg", 53.5511, 9.9937, "DE"),
    "dortmund": Location("Dortmund", 51.5136, 7.4653, "DE"),
    "monachium": Location("Monachium", 48.1351, 11.5820, "DE"),
    "lipsk": Location("Lipsk", 51.3397, 12.3731, "DE"),
    "praga": Location("Praga", 50.0755, 14.4378, "CZ"),
    "wieden": Location("Wiedeń", 48.2082, 16.3738, "AT"),
    "budapeszt": Location("Budapeszt", 47.4979, 19.0402, "HU"),
    "wilno": Location("Wilno", 54.6872, 25.2797, "LT"),
    "tallinn": Location("Tallinn", 59.4370, 24.7536, "EE"),
    "rotterdam": Location("Rotterdam", 51.9244, 4.4777, "NL"),
    "mediolan": Location("Mediolan", 45.4642, 9.1900, "IT"),
    "paryz": Location("Paryż", 48.8566, 2.3522, "FR"),
}

# Nazwy obce i warianty pisowni -> klucz w CITIES (porównywane po usunięciu diakrytyków).
CITY_ALIASES = {
    "warsaw": "warszawa", "warschau": "warszawa", "posen": "poznan", "breslau": "wroclaw",
    "danzig": "gdansk", "cracow": "krakow", "krakau": "krakow", "stettin": "szczecin",
    "munich": "monachium", "munchen": "monachium", "muenchen": "monachium", "leipzig": "lipsk",
    "prague": "praga", "prag": "praga", "praha": "praga", "vienna": "wieden", "wien": "wieden",
    "budapest": "budapeszt", "vilnius": "wilno", "milan": "mediolan", "milano": "mediolan",
    "paris": "paryz",
}
