"""[07] Kalkulator emisji CO2e przewozów.

Metodyka w duchu ISO 14083 / GLEC: zużycie energii pojazdu -> emisja
well-to-wheel -> alokacja na przesyłkę wg udziału masy w ładowności.
UWAGA: współczynniki poniżej są orientacyjne. Do raportowania zastąp je
aktualnymi wartościami z GLEC Framework / KOBiZE.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import Shipment, Vehicle, VehicleType

# kg CO2e na jednostkę paliwa/energii (WTW), wartości orientacyjne
WTW_FACTORS = {
    VehicleType.DIESEL_TRUCK: 3.2,    # kg/l oleju napędowego
    VehicleType.VAN: 3.2,             # kg/l
    VehicleType.LNG_TRUCK: 3.0,       # kg/kg LNG (bez bio-LNG)
    VehicleType.ELECTRIC_TRUCK: 0.65, # kg/kWh - przybliżony miks sieci w PL; zmień dla zielonej energii
}


@dataclass
class EmissionResult:
    shipment_id: str
    km: float
    vehicle_co2e_kg: float
    allocated_co2e_kg: float
    intensity_g_tkm: float


class EmissionsCalculator:
    def __init__(self, factors: dict[VehicleType, float] | None = None) -> None:
        self.factors = factors or WTW_FACTORS

    def calculate(self, s: Shipment, v: Vehicle, km: float, empty_km: float = 0.0) -> EmissionResult:
        energy = (km + empty_km) / 100 * v.consumption_per_100km
        vehicle_co2e = energy * self.factors[v.type]
        share = min(1.0, s.weight_kg / v.capacity_kg) if v.capacity_kg else 1.0
        allocated = vehicle_co2e * share
        tkm = s.weight_kg / 1000 * km
        intensity = allocated * 1000 / tkm if tkm else 0.0
        s.co2e_kg = round(allocated, 1)
        return EmissionResult(s.id, km, round(vehicle_co2e, 1), round(allocated, 1), round(intensity, 1))
