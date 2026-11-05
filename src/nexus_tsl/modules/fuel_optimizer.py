"""[06] Koszty paliwa i wybór stacji tankowania.

Liczy koszt paliwa trasy i wskazuje najtańszą stację osiągalną przy
bieżącym zapasie, uwzględniając objazd do stacji.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geo import road_km
from ..core.models import Location, Vehicle


@dataclass
class FuelStation:
    name: str
    location: Location
    price_per_l_eur: float


class FuelOptimizer:
    def trip_cost(self, vehicle: Vehicle, km: float, price_per_unit_eur: float) -> float:
        return round(km / 100 * vehicle.consumption_per_100km * price_per_unit_eur, 2)

    def best_station(
        self,
        vehicle: Vehicle,
        position: Location,
        destination: Location,
        stations: list[FuelStation],
        fuel_left_l: float,
        refill_l: float,
    ) -> FuelStation | None:
        range_km = fuel_left_l / vehicle.consumption_per_100km * 100
        direct = road_km(position, destination)
        best, best_cost = None, float("inf")
        for st in stations:
            to_station = road_km(position, st.location)
            if to_station > range_km:
                continue
            detour = to_station + road_km(st.location, destination) - direct
            detour_fuel = max(detour, 0) / 100 * vehicle.consumption_per_100km
            cost = refill_l * st.price_per_l_eur + detour_fuel * st.price_per_l_eur
            if cost < best_cost:
                best, best_cost = st, cost
        return best
