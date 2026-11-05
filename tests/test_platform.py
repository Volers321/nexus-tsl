from fastapi.testclient import TestClient

from nexus_tsl.api import app
from nexus_tsl.core.geo import CITIES
from nexus_tsl.core.models import Vehicle, VehicleType
from nexus_tsl.demo import SAMPLE_ORDER, sample_offers, sample_workers
from nexus_tsl.modules.freight_matching import CarrierOffer
from nexus_tsl.modules.vision_inspection import Photo
from nexus_tsl.orchestrator import NexusPlatform


def modules_used(report) -> set[str]:
    return {step["module"].split()[0] for step in report.steps}


def test_end_to_end_diesel_uses_all_relevant_modules():
    p = NexusPlatform(workers=sample_workers())
    rep = p.run(SAMPLE_ORDER, sample_offers(), loading_photos=[Photo("a", ["scratch"])])
    assert rep.shipment["status"] == "invoiced"
    assert {"ecmr", "ewaybill", "invoice"} <= set(rep.shipment["documents"])
    used = modules_used(rep)
    # wszystkie poza EV/energią (używane przy pojeździe elektrycznym)
    assert {f"{i:02d}" for i in range(1, 20)} - {"02", "11"} <= used
    topics = [e.topic for e in p.bus.log]
    assert topics[0] == "shipment.booked" and "invoice.issued" in topics


def test_end_to_end_electric_covers_ev_and_energy():
    ev = CarrierOffer("EcoOnly", Vehicle("EV1", VehicleType.ELECTRIC_TRUCK, 24000, battery_kwh=600,
                                         consumption_per_100km=110, age_years=1), 1000, CITIES["poznan"], rating=5)
    rep = NexusPlatform().run(SAMPLE_ORDER, [ev])
    assert {"02", "11"} <= modules_used(rep)


def test_rejected_cargo_stops_flow():
    p = NexusPlatform()
    rep = p.run(SAMPLE_ORDER, sample_offers(), loading_photos=[Photo("x", ["broken_seal"])])
    assert rep.shipment["status"] == "exception"
    assert "invoice" not in rep.shipment["documents"]


def test_api_smoke():
    c = TestClient(app)
    assert c.get("/health").json()["modules"] == 19
    r = c.post("/orders/run", json={"text": SAMPLE_ORDER})
    assert r.status_code == 200
    ecmr_id = r.json()["shipment"]["documents"]["ecmr"]
    assert c.get(f"/documents/ecmr/{ecmr_id}").json()["valid"] is True
    assert c.get("/distance", params={"origin": "warszawa", "destination": "krakow"}).json()["km"] > 250
    assert c.post("/orders/run", json={"text": "brak danych"}).status_code == 422
