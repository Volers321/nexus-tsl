"""REST API platformy (FastAPI). Start: `uvicorn nexus_tsl.api:app --reload`

- `/`        panel dyspozytora
- `/driver`  aplikacja kierowcy (PWA)
- `/docs`    interaktywna dokumentacja API
"""
from __future__ import annotations

import base64
import binascii
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .core.geo import CITIES, get_router
from .core.llm import get_provider
from .core.models import Location
from .core.storage import Store
from .demo import sample_offers, sample_workers
from .modules.driver_compliance import Activity, DriverLedger
from .modules.ksef import invoice_xml
from .modules.order_intake import OrderIntake
from .modules.vision_inspection import Photo, get_detector
from .orchestrator import NexusPlatform, StageError

STATIC = Path(__file__).parent / "static"
MAX_PHOTO_BYTES = 6 * 1024 * 1024

app = FastAPI(
    title="NexusTSL",
    version="0.2.0",
    description="Zintegrowana platforma AI dla transportu, spedycji i logistyki - 19 modułów w jednym przepływie.",
)
platform = NexusPlatform(
    llm=get_provider(),
    workers=sample_workers(),
    store=Store(os.getenv("NEXUS_DB_PATH", "nexus.db")),
    router=get_router(),
    detector=get_detector(),
)


# --------------------------------------------------------------------------- #
# Modele wejściowe
# --------------------------------------------------------------------------- #
class PhotoIn(BaseModel):
    tags: list[str] = []
    image_b64: str | None = Field(None, description="Obraz JPEG/PNG w base64 (opcjonalnie)")
    media_type: str = "image/jpeg"


class OrderIn(BaseModel):
    text: str = Field(..., examples=["Transport z Poznań do Berlin, 12 t, 22 palet. Towar: elektronika, wartość 180000 EUR"])
    loading_photo_tags: list[list[str]] = []
    delivery_photo_tags: list[list[str]] = []


class BookIn(BaseModel):
    text: str


class LoadIn(BaseModel):
    photos: list[PhotoIn] = []
    plate_read: str | None = Field(None, description="Odczyt tablicy z kamery bramy; domyślnie tablica z awizacji")
    minute: float = 75


class PingIn(BaseModel):
    lat: float
    lon: float
    minute: float


class DeliverIn(BaseModel):
    photos: list[PhotoIn] = []
    signer: str | None = None


class ActivityIn(BaseModel):
    kind: str
    hours: float


class ComplianceIn(BaseModel):
    driver_id: str = "D1"
    week_drive_h: float = 0
    prev_week_drive_h: float = 0
    day: list[ActivityIn]


def _photos(items: list[PhotoIn], prefix: str) -> list[Photo]:
    out = []
    for i, p in enumerate(items):
        data = None
        if p.image_b64:
            raw = p.image_b64.split(",", 1)[-1]   # dopuszcza "data:image/jpeg;base64,..."
            try:
                data = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError) as e:
                raise HTTPException(422, f"Zdjęcie {i + 1}: niepoprawne base64") from e
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, f"Zdjęcie {i + 1} przekracza {MAX_PHOTO_BYTES // 1024 // 1024} MB")
        out.append(Photo(f"{prefix}{i}", p.tags, data, p.media_type))
    return out


def _stage(fn, *args, **kwargs) -> dict:
    try:
        rep = fn(*args, **kwargs)
    except StageError as e:
        raise HTTPException(409 if "status" in str(e) else 404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"shipment": rep.shipment, "steps": rep.steps}


# --------------------------------------------------------------------------- #
# Strony
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def panel() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/driver", response_class=HTMLResponse, include_in_schema=False)
def driver_app() -> str:
    return (STATIC / "driver.html").read_text(encoding="utf-8")


@app.get("/driver/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/driver/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Service-Worker-Allowed": "/driver"})


@app.get("/driver/icon.svg", include_in_schema=False)
def icon() -> FileResponse:
    return FileResponse(STATIC / "icon.svg", media_type="image/svg+xml")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "modules": 19, "routing": platform.geo.source,
            "vision": type(platform.vision.detector).__name__}


@app.post("/orders/parse")
def parse_order(body: BookIn) -> dict:
    return OrderIntake(platform.intake.llm).extract(body.text)


@app.post("/orders/run")
def run_order(body: OrderIn) -> dict:
    """Cały przepływ naraz (demo)."""
    return _stage(
        platform.run, body.text, sample_offers(),
        loading_photos=[Photo(f"L{i}", t) for i, t in enumerate(body.loading_photo_tags)],
        delivery_photos=[Photo(f"D{i}", t) for i, t in enumerate(body.delivery_photo_tags)],
    )


@app.post("/orders/book")
def book_order(body: BookIn) -> dict:
    """Etap 1: przyjęcie zlecenia, wybór przewoźnika, plan i dokumenty."""
    return _stage(platform.book, body.text, sample_offers())


@app.post("/shipments/{shipment_id}/load")
def load(shipment_id: str, body: LoadIn) -> dict:
    """Etap 2: brama, rampa, inspekcja i podpis przewoźnika."""
    return _stage(platform.load, shipment_id, _photos(body.photos, "L"), ocr_plate=body.plate_read, now_min=body.minute)


@app.post("/shipments/{shipment_id}/ping")
def ping(shipment_id: str, body: PingIn) -> dict:
    """Etap 3: pozycja GPS z telefonu lub telematyki."""
    return _stage(platform.ping, shipment_id, Location("GPS", body.lat, body.lon), body.minute)


@app.post("/shipments/{shipment_id}/deliver")
def deliver(shipment_id: str, body: DeliverIn) -> dict:
    """Etap 4: inspekcja przy dostawie, podpis odbiorcy, faktura i emisje."""
    return _stage(platform.deliver, shipment_id, _photos(body.photos, "D"), body.signer)


@app.get("/shipments")
def list_shipments(status: str | None = None) -> list[dict]:
    items = [platform.summary(s) for s in platform.shipments.values()]
    return [x for x in items if not status or x["status"] == status]


@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str) -> dict:
    try:
        return platform.details(shipment_id)
    except StageError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/documents/ecmr/{doc_id}")
def get_ecmr(doc_id: str) -> dict:
    if doc_id not in platform.ecmr.docs:
        stored = platform.store.get("ecmr", doc_id)
        if not stored:
            raise HTTPException(404, "Nie znaleziono e-CMR")
        platform.ecmr.restore(stored)
    return platform.ecmr.export(doc_id)


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str) -> dict:
    inv = platform.store.get("invoice", invoice_id)
    if not inv:
        raise HTTPException(404, "Nie znaleziono faktury")
    return inv


@app.get("/invoices/{invoice_id}/ksef.xml")
def get_invoice_ksef(invoice_id: str) -> Response:
    """Faktura w strukturze KSeF FA(3) - do walidacji XSD przed wysyłką."""
    inv = platform.store.get("invoice", invoice_id)
    if not inv:
        raise HTTPException(404, "Nie znaleziono faktury")
    s = platform.get(inv["shipment_id"])
    return Response(invoice_xml(inv, s), media_type="application/xml",
                    headers={"Content-Disposition": f'inline; filename="{invoice_id}.xml"'})


@app.post("/compliance/check")
def compliance(body: ComplianceIn) -> dict:
    ledger = DriverLedger(body.driver_id, body.week_drive_h, body.prev_week_drive_h)
    return asdict(platform.compliance.check_day(ledger, [Activity(a.kind, a.hours) for a in body.day]))


@app.get("/distance")
def distance(origin: str, destination: str) -> dict:
    try:
        a, b = CITIES[origin.lower()], CITIES[destination.lower()]
    except KeyError as e:
        raise HTTPException(404, f"Nieznane miasto: {e}. Dostępne: {sorted(CITIES)}") from e
    return {"km": platform.geo.km(a, b), "source": platform.geo.source}


@app.get("/esg")
def esg() -> dict:
    return asdict(platform.esg.build("bieżący", list(platform.shipments.values())))


@app.get("/events")
def events(limit: int = 50) -> list[dict]:
    return platform.store.events(limit)
