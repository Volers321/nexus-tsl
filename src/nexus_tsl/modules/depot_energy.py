"""[02] Zarządzanie energią w bazie/magazynie - ładowanie, PV, taryfy.

Układa harmonogram ładowania pojazdów elektrycznych w bazie tak, by zmieścić
się w mocy przyłączeniowej, wykorzystać produkcję PV i najtańsze godziny taryfy.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChargeRequest:
    plate: str
    energy_kwh: float
    ready_by_hour: int          # 0-23, godzina wyjazdu
    max_kw: float = 150.0


@dataclass
class EnergyPlan:
    schedule: dict[str, list[float]]    # plate -> kWh w każdej godzinie (24)
    cost_eur: float
    pv_used_kwh: float
    unmet: dict[str, float]


class DepotEnergyManager:
    def __init__(self, grid_limit_kw: float, tariff_eur_kwh: list[float], pv_kwh: list[float] | None = None):
        assert len(tariff_eur_kwh) == 24
        self.grid_limit = grid_limit_kw
        self.tariff = tariff_eur_kwh
        self.pv = pv_kwh or [0.0] * 24

    def plan(self, requests: list[ChargeRequest], base_load_kw: list[float] | None = None) -> EnergyPlan:
        base = base_load_kw or [0.0] * 24
        headroom = [max(0.0, self.grid_limit - base[h]) + self.pv[h] for h in range(24)]
        pv_left = list(self.pv)
        schedule = {r.plate: [0.0] * 24 for r in requests}
        cost = pv_used = 0.0
        unmet: dict[str, float] = {}
        # Najpilniejsze najpierw (najwcześniejszy wyjazd).
        for r in sorted(requests, key=lambda r: r.ready_by_hour):
            need = r.energy_kwh
            hours = sorted(range(r.ready_by_hour), key=lambda h: (self.tariff[h] if pv_left[h] <= 0 else 0, h))
            for h in hours:
                if need <= 0:
                    break
                take = min(need, r.max_kw, headroom[h])
                if take <= 0:
                    continue
                from_pv = min(take, pv_left[h])
                pv_left[h] -= from_pv
                pv_used += from_pv
                cost += (take - from_pv) * self.tariff[h]
                headroom[h] -= take
                schedule[r.plate][h] += take
                need -= take
            if need > 1e-6:
                unmet[r.plate] = round(need, 1)
        return EnergyPlan(schedule, round(cost, 2), round(pv_used, 1), unmet)
