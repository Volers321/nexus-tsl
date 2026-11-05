"""[19] Predykcyjne utrzymanie floty.

Wylicza ryzyko awarii (0-1) z przebiegu od serwisu, wieku pojazdu i alertów
telematycznych. Model logistyczny z ręcznie dobranymi wagami - punkt wyjścia
do zastąpienia modelem uczonym na historii napraw.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.models import Vehicle


@dataclass
class MaintenanceAssessment:
    plate: str
    risk: float
    action: str
    km_since_service: float


class PredictiveMaintenance:
    def __init__(self, service_interval_km: float = 100_000) -> None:
        self.interval = service_interval_km

    def assess(self, v: Vehicle, planned_km: float = 0.0) -> MaintenanceAssessment:
        since = v.odometer_km - v.last_service_km + planned_km
        z = -4.0 + 3.0 * (since / self.interval) + 0.15 * v.age_years + 0.35 * v.sensor_alerts
        risk = round(1 / (1 + math.exp(-z)), 3)
        if risk >= 0.6:
            action = "Zablokuj do kursu - pilny serwis"
        elif risk >= 0.3:
            action = "Zaplanuj serwis po kursie"
        else:
            action = "OK"
        return MaintenanceAssessment(v.plate, risk, action, round(since))
