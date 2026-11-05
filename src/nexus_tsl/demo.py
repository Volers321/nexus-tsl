"""Dane demonstracyjne i uruchomienie: `python -m nexus_tsl.demo`"""
from __future__ import annotations

import json

from .core.geo import CITIES
from .core.models import Vehicle, VehicleType
from .modules.field_tasks import Worker
from .modules.freight_matching import CarrierOffer
from .modules.vision_inspection import Photo
from .orchestrator import NexusPlatform

SAMPLE_ORDER = """Dzień dobry,
prosimy o transport z Poznań do Berlin, 12 t, 22 palet EUR.
Towar: elektronika użytkowa, wartość 180000 EUR.
Załadunek 06.11.2026. Nr zlecenia: PZ/2026/1105
Nadawca: Elektro-Hurt Sp. z o.o.
Odbiorca: TechMarkt GmbH
"""


def sample_offers() -> list[CarrierOffer]:
    return [
        CarrierOffer("Trans-Pol", Vehicle("PO 12345", VehicleType.DIESEL_TRUCK, 24000, odometer_km=410_000,
                                          last_service_km=395_000, consumption_per_100km=29), 1150,
                     CITIES["poznan"], rating=4.6),
        CarrierOffer("EcoFreight", Vehicle("WE 7E001", VehicleType.ELECTRIC_TRUCK, 22000, battery_kwh=600,
                                           consumption_per_100km=110, odometer_km=80_000, last_service_km=60_000,
                                           age_years=1), 1290, CITIES["lodz"], rating=4.4),
        CarrierOffer("Szybki Bus", Vehicle("KR 0BUS1", VehicleType.VAN, 1200), 600, CITIES["krakow"], rating=3.9),
        CarrierOffer("OldTruck", Vehicle("DW 99999", VehicleType.DIESEL_TRUCK, 24000, odometer_km=900_000,
                                         last_service_km=700_000, sensor_alerts=6, age_years=14), 900,
                     CITIES["wroclaw"], rating=3.5),
    ]


def sample_workers() -> list[Worker]:
    return [
        Worker("W1", "Anna (kontrola jakości)", CITIES["poznan"], {"inspection", "forklift"}),
        Worker("W2", "Marek (wózek)", CITIES["poznan"], {"forklift"}),
    ]


def main() -> None:
    platform = NexusPlatform(workers=sample_workers())
    report = platform.run(
        SAMPLE_ORDER,
        sample_offers(),
        loading_photos=[Photo("L1"), Photo("L2", tags=["scratch"])],
        delivery_photos=[Photo("D1")],
    )
    for step in report.steps:
        print(f"▶ {step['module']}")
        print("   ", json.dumps(step["result"], ensure_ascii=False, default=str)[:300])
    print("\n=== PODSUMOWANIE PRZESYŁKI ===")
    print(json.dumps(report.shipment, ensure_ascii=False, indent=2, default=str))
    print(f"\nZdarzenia na szynie: {[e.topic for e in platform.bus.log]}")


if __name__ == "__main__":
    main()
