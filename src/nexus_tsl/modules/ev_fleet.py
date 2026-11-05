"""[11] Elektryfikacja floty - zasięg i ładowanie e-ciężarówek.

Ocenia, czy trasę da się obsłużyć pojazdem elektrycznym, ile postojów
ładowania potrzeba i jak wpisać je w obowiązkowe przerwy kierowcy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.models import Vehicle, VehicleType


@dataclass
class EVPlan:
    feasible: bool
    charging_stops: int
    energy_kwh: float
    charge_minutes_total: float
    fits_in_breaks: bool
    note: str


class EVFleetPlanner:
    def __init__(self, reserve_pct: float = 0.15, charger_kw: float = 400.0, usable_pct: float = 0.8) -> None:
        self.reserve_pct = reserve_pct
        self.charger_kw = charger_kw
        self.usable_pct = usable_pct  # ładowanie zwykle 10-90%

    def plan(self, vehicle: Vehicle, km: float, mandatory_breaks: int = 0) -> EVPlan:
        if vehicle.type != VehicleType.ELECTRIC_TRUCK or not vehicle.battery_kwh:
            return EVPlan(False, 0, 0, 0, False, "Pojazd nie jest elektryczny")
        energy = km / 100 * vehicle.consumption_per_100km
        first_leg = vehicle.battery_kwh * (1 - self.reserve_pct)
        if energy <= first_leg:
            return EVPlan(True, 0, round(energy, 1), 0, True, "Trasa bez ładowania")
        per_charge = vehicle.battery_kwh * self.usable_pct
        stops = math.ceil((energy - first_leg) / per_charge)
        minutes = stops * per_charge / self.charger_kw * 60
        fits = stops <= mandatory_breaks and minutes / max(stops, 1) <= 45
        note = "Ładowanie mieści się w przerwach 45 min" if fits else "Ładowanie wydłuży kurs"
        return EVPlan(True, stops, round(energy, 1), round(minutes), fits, note)
