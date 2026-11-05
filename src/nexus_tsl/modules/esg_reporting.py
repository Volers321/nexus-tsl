"""[08] Raportowanie ESG / śladu węglowego łańcucha dostaw (Scope 3).

Agreguje emisje z modułu [07] per klient, kraj i typ pojazdu oraz wylicza
potencjał redukcji przy przejściu na pojazdy niskoemisyjne - dane wejściowe
do raportów klientów objętych CSRD (kategoria 4/9 Scope 3).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..core.models import Shipment


@dataclass
class ESGReport:
    period: str
    shipments: int
    total_co2e_t: float
    total_tkm: float
    avg_intensity_g_tkm: float
    by_customer_t: dict[str, float]
    by_lane_t: dict[str, float]
    reduction_potential_t: float


class ESGReporter:
    def __init__(self, low_emission_intensity_ratio: float = 0.45) -> None:
        # Udział emisji pozostający po przejściu na pojazd niskoemisyjny (założenie scenariuszowe).
        self.ratio = low_emission_intensity_ratio

    def build(self, period: str, shipments: list[Shipment]) -> ESGReport:
        done = [s for s in shipments if s.co2e_kg is not None and s.distance_km]
        total_kg = sum(s.co2e_kg or 0 for s in done)
        tkm = sum(s.weight_kg / 1000 * (s.distance_km or 0) for s in done)
        by_cust: dict[str, float] = defaultdict(float)
        by_lane: dict[str, float] = defaultdict(float)
        for s in done:
            by_cust[s.shipper] += (s.co2e_kg or 0) / 1000
            by_lane[f"{s.origin.country}->{s.destination.country}"] += (s.co2e_kg or 0) / 1000
        return ESGReport(
            period=period,
            shipments=len(done),
            total_co2e_t=round(total_kg / 1000, 3),
            total_tkm=round(tkm, 1),
            avg_intensity_g_tkm=round(total_kg * 1000 / tkm, 1) if tkm else 0.0,
            by_customer_t={k: round(v, 3) for k, v in by_cust.items()},
            by_lane_t={k: round(v, 3) for k, v in by_lane.items()},
            reduction_potential_t=round(total_kg / 1000 * (1 - self.ratio), 3),
        )

    @staticmethod
    def to_csv(report: ESGReport) -> str:
        rows = ["customer,co2e_t"] + [f"{k},{v}" for k, v in report.by_customer_t.items()]
        return "\n".join(rows)
