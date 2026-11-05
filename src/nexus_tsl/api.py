"""REST API platformy (FastAPI). Start: `uvicorn nexus_tsl.api:app --reload`

Dokumentacja interaktywna: http://localhost:8000/docs
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .core.geo import CITIES, road_km
from .core.llm import get_provider
from .demo import sample_offers, sample_workers
from .modules.driver_compliance import Activity, DriverLedger
from .modules.order_intake import OrderIntake
from .modules.vision_inspection import Photo
from .orchestrator import NexusPlatform

app = FastAPI(
    title="NexusTSL",
    version="0.1.0",
    description="Zintegrowana platforma AI dla transportu, spedycji i logistyki - 19 modułów w jednym przepływie.",
)
platform = NexusPlatform(llm=get_provider(), workers=sample_workers())


class OrderIn(BaseModel):
    text: str = Field(..., examples=["Transport z Poznań do Berlin, 12 t, 22 palet. Towar: elektronika, wartość 180000 EUR"])
    loading_photo_tags: list[list[str]] = []
    delivery_photo_tags: list[list[str]] = []


class ActivityIn(BaseModel):
    kind: str
    hours: float


class ComplianceIn(BaseModel):
    driver_id: str = "D1"
    week_drive_h: float = 0
    prev_week_drive_h: float = 0
    day: list[ActivityIn]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "modules": 19}


@app.post("/orders/parse")
def parse_order(body: OrderIn) -> dict:
    return OrderIntake(platform.intake.llm).extract(body.text)


@app.post("/orders/run")
def run_order(body: OrderIn) -> dict:
    try:
        rep = platform.run(
            body.text,
            sample_offers(),
            loading_photos=[Photo(f"L{i}", t) for i, t in enumerate(body.loading_photo_tags)],
            delivery_photos=[Photo(f"D{i}", t) for i, t in enumerate(body.delivery_photo_tags)],
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(422, str(e)) from e
    return {"shipment": rep.shipment, "steps": rep.steps}


@app.get("/shipments")
def list_shipments() -> list[dict]:
    return [platform._summary(s) for s in platform.shipments.values()]


@app.get("/documents/ecmr/{doc_id}")
def get_ecmr(doc_id: str) -> dict:
    if doc_id not in platform.ecmr.docs:
        raise HTTPException(404, "Nie znaleziono e-CMR")
    return platform.ecmr.export(doc_id)


@app.post("/compliance/check")
def compliance(body: ComplianceIn) -> dict:
    ledger = DriverLedger(body.driver_id, body.week_drive_h, body.prev_week_drive_h)
    return asdict(platform.compliance.check_day(ledger, [Activity(a.kind, a.hours) for a in body.day]))


@app.get("/distance")
def distance(origin: str, destination: str) -> dict:
    try:
        return {"km": road_km(CITIES[origin.lower()], CITIES[destination.lower()])}
    except KeyError as e:
        raise HTTPException(404, f"Nieznane miasto: {e}. Dostępne: {sorted(CITIES)}") from e


@app.get("/esg")
def esg() -> dict:
    return asdict(platform.esg.build("bieżący", list(platform.shipments.values())))


@app.get("/events")
def events(limit: int = 50) -> list[dict]:
    return [asdict(e) for e in platform.bus.log[-limit:]]
