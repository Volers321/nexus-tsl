"""[12] Giełda i dopasowanie ładunek-przewoźnik.

Ocenia oferty przewoźników wielokryterialnie: cena, dojazd na pusto, ocena
jakości, emisyjność pojazdu. Wagi są konfigurowalne.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geo import road_km
from ..core.models import Location, Shipment, Vehicle, VehicleType


@dataclass
class CarrierOffer:
    carrier: str
    vehicle: Vehicle
    price_eur: float
    current_location: Location
    rating: float = 4.0          # 1-5
    insured: bool = True


@dataclass
class MatchWeights:
    price: float = 0.45
    empty_km: float = 0.25
    rating: float = 0.20
    green: float = 0.10


GREEN_SCORE = {
    VehicleType.ELECTRIC_TRUCK: 1.0,
    VehicleType.LNG_TRUCK: 0.6,
    VehicleType.VAN: 0.4,
    VehicleType.DIESEL_TRUCK: 0.3,
}


class FreightMatcher:
    def __init__(self, weights: MatchWeights | None = None) -> None:
        self.w = weights or MatchWeights()

    def rank(self, shipment: Shipment, offers: list[CarrierOffer]) -> list[tuple[float, CarrierOffer]]:
        eligible = [o for o in offers if o.vehicle.capacity_kg >= shipment.weight_kg and o.insured]
        if not eligible:
            return []
        prices = [o.price_eur for o in eligible]
        empties = [road_km(o.current_location, shipment.origin) for o in eligible]
        pmin, pmax = min(prices), max(prices)
        emin, emax = min(empties), max(empties)

        def norm_inv(v: float, lo: float, hi: float) -> float:
            return 1.0 if hi == lo else (hi - v) / (hi - lo)

        scored = []
        for o, empty in zip(eligible, empties):
            score = (
                self.w.price * norm_inv(o.price_eur, pmin, pmax)
                + self.w.empty_km * norm_inv(empty, emin, emax)
                + self.w.rating * (o.rating - 1) / 4
                + self.w.green * GREEN_SCORE[o.vehicle.type]
            )
            scored.append((round(score, 4), o))
        return sorted(scored, key=lambda x: x[0], reverse=True)

    def best(self, shipment: Shipment, offers: list[CarrierOffer]) -> CarrierOffer | None:
        ranked = self.rank(shipment, offers)
        return ranked[0][1] if ranked else None
