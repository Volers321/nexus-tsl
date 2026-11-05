"""Wspólny model domenowy platformy NexusTSL.

Wszystkie moduły operują na tych samych obiektach, dzięki czemu dane
wprowadzone raz (np. zlecenie z maila) płyną dalej bez przepisywania:
zlecenie -> giełda -> trasa -> dokumenty -> rampa -> dostawa -> faktura -> ESG.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Location:
    name: str
    lat: float
    lon: float
    country: str = "PL"


class VehicleType(str, Enum):
    DIESEL_TRUCK = "diesel_truck"      # ciągnik + naczepa, 40 t
    LNG_TRUCK = "lng_truck"
    ELECTRIC_TRUCK = "electric_truck"
    VAN = "van"                        # do 3,5 t


@dataclass
class Vehicle:
    plate: str
    type: VehicleType
    capacity_kg: float
    odometer_km: float = 0.0
    battery_kwh: float | None = None          # tylko EV
    consumption_per_100km: float = 30.0       # l (diesel/LNG kg) lub kWh dla EV
    last_service_km: float = 0.0
    sensor_alerts: int = 0                    # liczba alertów telematycznych w ostatnich 30 dniach
    age_years: float = 3.0


@dataclass
class Driver:
    id: str
    name: str
    languages: list[str] = field(default_factory=lambda: ["pl"])


class ShipmentStatus(str, Enum):
    DRAFT = "draft"
    BOOKED = "booked"
    ASSIGNED = "assigned"
    AT_GATE = "at_gate"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    INVOICED = "invoiced"
    EXCEPTION = "exception"


@dataclass
class Shipment:
    id: str
    shipper: str
    consignee: str
    origin: Location
    destination: Location
    weight_kg: float
    goods_description: str
    cargo_value_eur: float = 0.0
    pallets: int = 0
    pickup_date: str | None = None
    reference: str | None = None
    status: ShipmentStatus = ShipmentStatus.DRAFT
    carrier: str | None = None
    vehicle_plate: str | None = None
    driver_id: str | None = None
    price_eur: float | None = None
    distance_km: float | None = None
    co2e_kg: float | None = None
    documents: dict[str, str] = field(default_factory=dict)   # typ -> id dokumentu
    history: list[tuple[str, str]] = field(default_factory=list)

    def set_status(self, status: ShipmentStatus, note: str = "") -> None:
        self.status = status
        self.history.append((utcnow().isoformat(), f"{status.value} {note}".strip()))
