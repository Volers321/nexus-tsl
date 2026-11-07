import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nexus_tsl.core.geo import CITIES, OSRMRouter, Router, road_km
from nexus_tsl.core.storage import Store
from nexus_tsl.demo import SAMPLE_ORDER, sample_offers, sample_workers
from nexus_tsl.modules.vision_inspection import ClaudeVisionDetector, Photo
from nexus_tsl.orchestrator import NexusPlatform, StageError


# ------------------------------------------------------------------ etapy + baza
def test_stages_persist_across_restart(tmp_path):
    db = str(tmp_path / "n.db")
    p1 = NexusPlatform(store=Store(db), workers=sample_workers())
    sid = p1.book(SAMPLE_ORDER, sample_offers()).shipment["id"]
    assert p1.load(sid, [Photo("a")]).shipment["status"] == "in_transit"

    # "restart serwera": nowa instancja, ta sama baza
    p2 = NexusPlatform(store=Store(db))
    s = p2.get(sid)
    p2.ping(sid, CITIES["poznan"], 0)
    rep = p2.ping(sid, CITIES["berlin"], 200)
    assert rep.steps[0]["result"]["progress"] == 1.0
    final = p2.deliver(sid, [], signer="Jan Odbiorca")
    assert final.shipment["status"] == "invoiced"
    d = p2.details(sid)
    modules = {x["module"].split()[0] for x in d["steps"]}
    assert {"15", "12", "10", "01", "13", "14", "17", "07", "08"} <= modules
    assert p2.ecmr.export(s.documents["ecmr"])["signatures"][-1]["signer"] == "Jan Odbiorca"
    assert any(e["topic"] == "invoice.issued" for e in d["events"])


def test_stage_order_is_enforced():
    p = NexusPlatform()
    sid = p.book(SAMPLE_ORDER, sample_offers()).shipment["id"]
    with pytest.raises(StageError):
        p.deliver(sid)
    with pytest.raises(StageError):
        p.get("SHP-nieistnieje")


def test_gate_rejects_unknown_plate():
    p = NexusPlatform()
    sid = p.book(SAMPLE_ORDER, sample_offers()).shipment["id"]
    rep = p.load(sid, ocr_plate="XX 00000")
    assert rep.shipment["status"] == "assigned"
    assert rep.steps[0]["result"]["allowed"] is False


# ------------------------------------------------------------------ OSRM
class FakeResp:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self.payload


def test_osrm_router_uses_server_and_caches(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout):
        calls.append(url)
        return FakeResp({"code": "Ok", "routes": [{"distance": 270_400.0, "duration": 3 * 3600}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    r = OSRMRouter("http://osrm:5000")
    assert r.km(CITIES["poznan"], CITIES["berlin"]) == 270.4
    assert r.km(CITIES["poznan"], CITIES["berlin"]) == 270.4
    assert len(calls) == 1 and "/route/v1/driving/16.925200,52.406400;13.405000,52.520000" in calls[0]
    assert r.duration_h(CITIES["poznan"], CITIES["berlin"]) == 3.75
    assert r.source == "osrm"


def test_osrm_falls_back_when_offline(monkeypatch):
    import urllib.error

    def boom(url, timeout):
        raise urllib.error.URLError("brak sieci")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = OSRMRouter("http://osrm:5000")
    assert r.km(CITIES["warszawa"], CITIES["krakow"]) == road_km(CITIES["warszawa"], CITIES["krakow"])
    assert "fallback" in r.source


def test_platform_uses_injected_router():
    class Fixed(Router):
        source = "fixed"

        def km(self, a, b):
            return 0.0 if a == b else 500.0

    rep = NexusPlatform(router=Fixed()).book(SAMPLE_ORDER, sample_offers())
    assert rep.shipment["distance_km"] == 500.0
    assert next(s for s in rep.steps if s["module"] == "18 route_optimizer")["result"]["routing"] == "fixed"


# ------------------------------------------------------------------ wizja
def fake_client(answer: str):
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=answer)])

    return SimpleNamespace(messages=SimpleNamespace(create=create)), seen


def test_claude_vision_detector_parses_findings():
    client, seen = fake_client('```json\n{"findings": ["dent", "unknown_thing"]}\n```')
    det = ClaudeVisionDetector(client=client, model="test-model")
    found = det.detect(Photo("p1", tags=["wet"], data=b"\xff\xd8jpeg"))
    assert {f.kind for f in found} == {"dent", "wet"}
    img = seen["messages"][0]["content"][0]
    assert img["type"] == "image" and base64.b64decode(img["source"]["data"]) == b"\xff\xd8jpeg"


def test_claude_vision_detector_tolerates_garbage():
    client, _ = fake_client("Nie widzę uszkodzeń.")
    assert ClaudeVisionDetector(client=client).detect(Photo("p", data=b"x")) == []


# ------------------------------------------------------------------ API: przepływ kierowcy
@pytest.fixture()
def client(monkeypatch, tmp_path):
    import nexus_tsl.api as api

    monkeypatch.setattr(api, "platform", NexusPlatform(store=Store(str(tmp_path / "api.db")), workers=sample_workers()))
    return TestClient(api.app)


def test_api_driver_flow(client):
    sid = client.post("/orders/book", json={"text": SAMPLE_ORDER}).json()["shipment"]["id"]
    assert any(s["id"] == sid for s in client.get("/shipments", params={"status": "assigned"}).json())

    jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8fake").decode()
    r = client.post(f"/shipments/{sid}/load", json={"photos": [{"image_b64": jpeg, "tags": ["scratch"]}]})
    assert r.status_code == 200 and r.json()["shipment"]["status"] == "in_transit"

    assert client.post(f"/shipments/{sid}/ping", json={"lat": 52.45, "lon": 15.0, "minute": 120}).status_code == 200
    r = client.post(f"/shipments/{sid}/deliver", json={"photos": [], "signer": "Anna Nowak"})
    shipment = r.json()["shipment"]
    assert shipment["status"] == "invoiced"

    xml = client.get(f"/invoices/{shipment['documents']['invoice']}/ksef.xml")
    assert xml.status_code == 200 and "FA (3)" in xml.text
    assert client.post(f"/shipments/{sid}/deliver", json={}).status_code == 409


def test_api_rejects_bad_photo(client):
    sid = client.post("/orders/book", json={"text": SAMPLE_ORDER}).json()["shipment"]["id"]
    r = client.post(f"/shipments/{sid}/load", json={"photos": [{"image_b64": "@@@nie-base64"}]})
    assert r.status_code == 422


def test_driver_pwa_assets(client):
    assert "NexusTSL Kierowca" in client.get("/driver").text
    assert client.get("/driver/manifest.webmanifest").json()["start_url"] == "/driver"
    assert client.get("/driver/sw.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/driver/icon.svg").status_code == 200


def test_api_survives_unwritable_db(monkeypatch):
    import nexus_tsl.api as api

    monkeypatch.setenv("NEXUS_DB_PATH", "/nie/istnieje/katalog/nexus.db")
    assert api._open_store().path == ":memory:"
