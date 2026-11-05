"""[18] Optymalizacja tras wielopunktowych i ETA.

Heurystyka najbliższego sąsiada + poprawa 2-opt. Dla dużych instancji
podmień na OR-Tools / VROOM, zachowując interfejs `optimize`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geo import road_km
from ..core.models import Location


@dataclass
class RoutePlan:
    stops: list[Location]
    total_km: float
    drive_hours: float


def _length(route: list[Location]) -> float:
    return sum(road_km(a, b) for a, b in zip(route, route[1:]))


class RouteOptimizer:
    def __init__(self, avg_speed_kmh: float = 70.0) -> None:
        self.avg_speed_kmh = avg_speed_kmh

    def optimize(self, depot: Location, stops: list[Location], return_to_depot: bool = False) -> RoutePlan:
        remaining = list(stops)
        route = [depot]
        while remaining:
            nxt = min(remaining, key=lambda s: road_km(route[-1], s))
            route.append(nxt)
            remaining.remove(nxt)
        if return_to_depot:
            route.append(depot)

        improved = True
        while improved:
            improved = False
            end = len(route) - (1 if return_to_depot else 0)
            for i in range(1, end - 1):
                for j in range(i + 1, end):
                    candidate = route[:i] + route[i : j + 1][::-1] + route[j + 1 :]
                    if _length(candidate) + 1e-9 < _length(route):
                        route, improved = candidate, True
        km = round(_length(route), 1)
        return RoutePlan(stops=route, total_km=km, drive_hours=round(km / self.avg_speed_kmh, 2))

    def eta_hours(self, a: Location, b: Location, traffic_factor: float = 1.0) -> float:
        return round(road_km(a, b) / self.avg_speed_kmh * traffic_factor, 2)
