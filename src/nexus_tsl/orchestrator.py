"""Orkiestrator - przepływ zlecenia przez wszystkie 19 modułów, podzielony na etapy.

  ETAP 1  book()     mail ─► [15] intake ─► [12] giełda ─► [19] serwis? ─► [18] trasa
                     ─► [04] czas pracy ─► [06] paliwo / [11] EV + [02] energia
                     ─► [09] ubezpieczenie ─► [03] e-CMR + [16] e-waybill
  ETAP 2  load()     [10] brama ─► [01] rampa ─► [05] zadania ─► [13] inspekcja ─► podpis przewoźnika
  ETAP 3  ping()     [14] śledzenie / ETA (wielokrotnie)
  ETAP 4  deliver()  [13] inspekcja ─► podpis odbiorcy ─► [17] faktura ─► [07] emisje ─► [08] ESG

Etapy mogą być wywoływane w różnym czasie (np. z aplikacji kierowcy). Stan
między nimi jest zapisywany w bazie (`core/storage.py`), więc przeżywa restart.
`run()` wykonuje wszystkie etapy naraz - do demo i testów.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .core.events import EventBus
from .core.geo import Router
from .core.llm import LLMProvider, OfflineProvider
from .core.models import (
    Location,
    Shipment,
    ShipmentStatus,
    VehicleType,
    location_from_dict,
    shipment_from_dict,
    to_dict,
    vehicle_from_dict,
)
from .core.storage import Store
from .modules.billing import BillingEngine, Invoice
from .modules.cargo_insurance import CargoInsurance
from .modules.depot_energy import ChargeRequest, DepotEnergyManager
from .modules.dock_scheduler import Arrival, Dock, DockScheduler
from .modules.driver_compliance import DriverCompliance, DriverLedger
from .modules.ecmr import ECMRService
from .modules.emissions import EmissionsCalculator
from .modules.esg_reporting import ESGReporter
from .modules.ev_fleet import EVFleetPlanner
from .modules.ewaybill import EWaybillService
from .modules.field_tasks import FieldTaskManager, Worker
from .modules.freight_matching import CarrierOffer, FreightMatcher
from .modules.fuel_optimizer import FuelOptimizer
from .modules.gate_control import Booking, GateControl
from .modules.order_intake import OrderIntake
from .modules.predictive_maintenance import PredictiveMaintenance
from .modules.route_optimizer import RouteOptimizer
from .modules.tracking import Ping, Tracker, TrackState
from .modules.vision_inspection import Detector, Photo, VisionInspection


class StageError(ValueError):
    """Etap wywołany w złej kolejności lub dla nieznanej przesyłki."""


@dataclass
class RunReport:
    shipment: dict
    steps: list[dict] = field(default_factory=list)

    def add(self, module: str, result: object) -> None:
        self.steps.append({"module": module, "result": result})


@dataclass
class PlatformConfig:
    diesel_price_eur_l: float = 1.45
    docks: list[Dock] = field(default_factory=lambda: [Dock("R1"), Dock("R2"), Dock("R3", reefer=True)])
    tariff: list[float] = field(default_factory=lambda: [0.12] * 6 + [0.22] * 16 + [0.14] * 2)
    grid_limit_kw: float = 400.0
    gate_window: tuple[float, float] = (60, 120)   # okno awizacji w minutach od początku zmiany


class NexusPlatform:
    def __init__(self, llm: LLMProvider | None = None, config: PlatformConfig | None = None,
                 workers: list[Worker] | None = None, store: Store | None = None,
                 router: Router | None = None, detector: Detector | None = None) -> None:
        self.cfg = config or PlatformConfig()
        self.store = store or Store()
        self.bus = EventBus()
        self.bus.subscribe("*", lambda e: self.store.add_event(e.topic, e.source, e.at, e.payload))
        self.geo = router or Router()
        self.intake = OrderIntake(llm or OfflineProvider())
        self.matcher = FreightMatcher()
        self.maintenance = PredictiveMaintenance()
        self.router = RouteOptimizer(distance=self.geo.km)
        self.compliance = DriverCompliance()
        self.fuel = FuelOptimizer()
        self.ev = EVFleetPlanner()
        self.energy = DepotEnergyManager(self.cfg.grid_limit_kw, self.cfg.tariff)
        self.insurance = CargoInsurance()
        self.ecmr = ECMRService()
        self.ewaybill = EWaybillService()
        self.gate = GateControl()
        self.docks = DockScheduler(self.cfg.docks)
        self.tasks = FieldTaskManager(workers or [])
        self.vision = VisionInspection(detector)
        self.tracker = Tracker(self.bus)
        self.billing = BillingEngine(fuel_surcharge_pct=0.05)
        self.emissions = EmissionsCalculator()
        self.esg = ESGReporter()
        self.invoices: dict[str, Invoice] = {}

    # ------------------------------------------------------------------ #
    # Dostęp do danych
    # ------------------------------------------------------------------ #
    @property
    def shipments(self) -> dict[str, Shipment]:
        return {d["id"]: shipment_from_dict(d) for d in self.store.list("shipment")}

    def get(self, shipment_id: str) -> Shipment:
        d = self.store.get("shipment", shipment_id)
        if not d:
            raise StageError(f"Nieznana przesyłka {shipment_id}")
        return shipment_from_dict(d)

    def _ctx(self, shipment_id: str) -> dict:
        return self.store.get("ctx", shipment_id) or {"steps": []}

    def _save(self, s: Shipment, ctx: dict, report: RunReport) -> None:
        ctx["steps"] = ctx.get("steps", []) + report.steps
        self.store.put("shipment", s.id, to_dict(s))
        self.store.put("ctx", s.id, ctx)
        for kind, svc in (("ecmr", self.ecmr), ("ewaybill", self.ewaybill)):
            doc_id = s.documents.get(kind)
            if doc_id and doc_id in svc.docs:
                self.store.put(kind, doc_id, asdict(svc.docs[doc_id]))
        report.shipment = self.summary(s)

    def _docs(self, s: Shipment):
        """Odtwarza dokumenty z bazy (np. po restarcie)."""
        ecmr_id, wb_id = s.documents.get("ecmr"), s.documents.get("ewaybill")
        if ecmr_id not in self.ecmr.docs:
            self.ecmr.restore(self.store.get("ecmr", ecmr_id))
        if wb_id not in self.ewaybill.docs:
            self.ewaybill.restore(self.store.get("ewaybill", wb_id))
        return self.ecmr.docs[ecmr_id], self.ewaybill.docs[wb_id]

    def _require(self, s: Shipment, *allowed: ShipmentStatus) -> None:
        if s.status not in allowed:
            names = ", ".join(a.value for a in allowed)
            raise StageError(f"Przesyłka {s.id} ma status '{s.status.value}', a ten etap wymaga: {names}")

    @staticmethod
    def summary(s: Shipment) -> dict:
        return {"id": s.id, "status": s.status.value, "shipper": s.shipper, "consignee": s.consignee,
                "origin": s.origin.name, "destination": s.destination.name, "goods": s.goods_description,
                "weight_kg": s.weight_kg, "pallets": s.pallets, "reference": s.reference,
                "carrier": s.carrier, "vehicle": s.vehicle_plate, "price_eur": s.price_eur,
                "distance_km": s.distance_km, "co2e_kg": s.co2e_kg, "documents": s.documents, "history": s.history}

    def details(self, shipment_id: str) -> dict:
        s = self.get(shipment_id)
        ctx = self._ctx(shipment_id)
        return {**self.summary(s), "steps": ctx.get("steps", []), "eta_min": ctx.get("eta_min"),
                "progress": ctx.get("progress"), "events": self.store.events(100, shipment_id)}

    # ------------------------------------------------------------------ #
    # ETAP 1: przyjęcie i planowanie
    # ------------------------------------------------------------------ #
    def book(self, order_text: str, offers: list[CarrierOffer], ledger: DriverLedger | None = None) -> RunReport:
        s = self.intake.to_shipment(order_text)
        s.set_status(ShipmentStatus.BOOKED, "z wiadomości")
        report, ctx = RunReport(shipment={}), {"steps": []}
        report.add("15 order_intake", {"id": s.id, "lane": f"{s.origin.name}->{s.destination.name}", "kg": s.weight_kg})
        self.bus.publish("shipment.booked", {"id": s.id}, "order_intake")

        distance = self.geo.km(s.origin, s.destination)
        chosen: CarrierOffer | None = None
        for score, offer in self.matcher.rank(s, offers):
            m = self.maintenance.assess(offer.vehicle, planned_km=distance)
            report.add("19 predictive_maintenance", asdict(m))
            if m.risk < 0.6:
                chosen = offer
                report.add("12 freight_matching", {"carrier": offer.carrier, "score": score, "price_eur": offer.price_eur})
                break
        if not chosen:
            s.set_status(ShipmentStatus.EXCEPTION, "brak przewoźnika")
            self._save(s, ctx, report)
            raise StageError("Brak przewoźnika spełniającego wymagania")
        v = chosen.vehicle
        s.carrier, s.vehicle_plate, s.price_eur = chosen.carrier, v.plate, chosen.price_eur
        s.set_status(ShipmentStatus.ASSIGNED, chosen.carrier)
        self.bus.publish("shipment.assigned", {"id": s.id, "carrier": s.carrier}, "freight_matching")

        plan = self.router.optimize(chosen.current_location, [s.origin, s.destination])
        s.distance_km = distance
        report.add("18 route_optimizer", {"total_km": plan.total_km, "drive_h": plan.drive_hours,
                                           "stops": [x.name for x in plan.stops], "routing": self.geo.source})

        activities = self.compliance.plan_trip(plan.drive_hours)
        first_day = next((i for i, a in enumerate(activities) if a.kind == "rest"), len(activities))
        check = self.compliance.check_day(ledger or DriverLedger("D1"), activities[:first_day])
        breaks = sum(1 for a in activities if a.kind in ("break", "rest"))
        report.add("04 driver_compliance", {"ok": check.ok, "violations": check.violations,
                                            "plan": [(a.kind, a.hours) for a in activities]})

        if v.type == VehicleType.ELECTRIC_TRUCK:
            ev = self.ev.plan(v, plan.total_km, mandatory_breaks=breaks)
            report.add("11 ev_fleet", asdict(ev))
            e = self.energy.plan([ChargeRequest(v.plate, min(ev.energy_kwh, (v.battery_kwh or 0) * 0.8), ready_by_hour=6)])
            report.add("02 depot_energy", {"cost_eur": e.cost_eur, "unmet": e.unmet})
        else:
            report.add("06 fuel_optimizer", {"fuel_cost_eur": self.fuel.trip_cost(v, plan.total_km, self.cfg.diesel_price_eur_l)})

        report.add("09 cargo_insurance", asdict(self.insurance.quote(s, chosen.rating)))

        doc = self.ecmr.create(s)
        self.ecmr.sign(doc.id, "sender", s.shipper)
        wb = self.ewaybill.create(s)
        self.ewaybill.advance(wb.id, "accepted", s.carrier or "")
        report.add("03 ecmr", {"id": doc.id, "status": doc.status})
        report.add("16 ewaybill", {"id": wb.id, "state": wb.state})

        ctx.update({
            "vehicle": to_dict(v), "carrier_rating": chosen.rating,
            "empty_km": self.geo.km(chosen.current_location, s.origin),
            "drive_hours": plan.drive_hours, "deadline_min": round(plan.drive_hours * 60 * 1.5, 1),
            "pings": [],
        })
        self._save(s, ctx, report)
        return report

    # ------------------------------------------------------------------ #
    # ETAP 2: brama, rampa, załadunek
    # ------------------------------------------------------------------ #
    def load(self, shipment_id: str, photos: list[Photo] | None = None, *,
             ocr_plate: str | None = None, now_min: float = 75) -> RunReport:
        s = self.get(shipment_id)
        self._require(s, ShipmentStatus.ASSIGNED)
        ctx, report = self._ctx(s.id), RunReport(shipment={})
        doc, wb = self._docs(s)
        v_plate = s.vehicle_plate or ""

        if not any(b.shipment_id == s.id for b in self.gate.bookings):
            self.gate.add_booking(Booking(v_plate, s.id, *self.cfg.gate_window))
        gd = self.gate.check(ocr_plate or v_plate, now_min=now_min)
        report.add("10 gate_control", asdict(gd))
        if not gd.allowed:
            self._save(s, ctx, report)
            return report
        s.set_status(ShipmentStatus.AT_GATE)

        slots = self.docks.schedule([Arrival(now_min, v_plate, 40), Arrival(70, "WX0001", 60), Arrival(72, "PO1234", 50)])
        mine = next(x for x in slots if x.plate == v_plate)
        ctx["wait_min"] = mine.wait_min
        report.add("01 dock_scheduler", {"dock": mine.dock, "wait_min": mine.wait_min, "kpi": self.docks.kpis(slots)})
        s.set_status(ShipmentStatus.LOADING, mine.dock)

        if self.tasks.workers:
            t = self.tasks.create(f"Zdjęcia ładunku i plomby {v_plate}", s.origin, "inspection")
            try:
                self.tasks.dispatch(t.id)
                self.tasks.complete(t.id, proof="photo-set", minutes=15)
            except LookupError as e:
                t.status = f"pending: {e}"
            report.add("05 field_tasks", {"task": t.title, "assignee": t.assignee, "status": t.status})

        insp = self.vision.inspect(photos or [])
        report.add("13 vision_inspection(load)", {"verdict": insp.verdict, "remark": insp.ecmr_remark,
                                                   "photos": len(photos or [])})
        if insp.verdict == "reject":
            s.set_status(ShipmentStatus.EXCEPTION, "ładunek odrzucony przy załadunku")
            self.bus.publish("shipment.exception", {"id": s.id, "reason": insp.ecmr_remark}, "vision_inspection")
            self._save(s, ctx, report)
            return report

        self.ecmr.sign(doc.id, "carrier", s.carrier or "", remarks=insp.ecmr_remark)
        self.ewaybill.advance(wb.id, "loaded", s.carrier or "")
        self.ewaybill.advance(wb.id, "in_transit", s.carrier or "")
        s.set_status(ShipmentStatus.IN_TRANSIT)
        self.bus.publish("shipment.in_transit", {"id": s.id, "ecmr": doc.id}, "ecmr")
        self._save(s, ctx, report)
        return report

    # ------------------------------------------------------------------ #
    # ETAP 3: śledzenie
    # ------------------------------------------------------------------ #
    def ping(self, shipment_id: str, location: Location, minute: float) -> RunReport:
        s = self.get(shipment_id)
        self._require(s, ShipmentStatus.IN_TRANSIT)
        ctx, report = self._ctx(s.id), RunReport(shipment={})
        if s.id not in self.tracker.states:
            self.tracker.states[s.id] = TrackState(s.id, [Ping(m, location_from_dict(loc)) for m, loc in ctx["pings"]])
        st = self.tracker.ping(s, Ping(minute, location), ctx.get("deadline_min"))
        ctx["pings"] = ctx["pings"][-20:] + [[minute, asdict(location)]]
        ctx["eta_min"], ctx["progress"] = st.eta_min, st.progress
        report.add("14 tracking", {"progress": st.progress, "eta_min": st.eta_min})
        self._save(s, ctx, report)
        return report

    # ------------------------------------------------------------------ #
    # ETAP 4: dostawa, faktura, emisje
    # ------------------------------------------------------------------ #
    def deliver(self, shipment_id: str, photos: list[Photo] | None = None, signer: str | None = None) -> RunReport:
        s = self.get(shipment_id)
        self._require(s, ShipmentStatus.IN_TRANSIT)
        ctx, report = self._ctx(s.id), RunReport(shipment={})
        doc, wb = self._docs(s)
        v = vehicle_from_dict(ctx["vehicle"])

        dinsp = self.vision.inspect(photos or [])
        self.ecmr.sign(doc.id, "consignee", signer or s.consignee, remarks=dinsp.ecmr_remark)
        self.ewaybill.advance(wb.id, "delivered", s.consignee)
        self.ewaybill.advance(wb.id, "disputed" if dinsp.findings else "confirmed", s.consignee, dinsp.ecmr_remark)
        if dinsp.findings:
            self.ewaybill.advance(wb.id, "confirmed", s.consignee, "rozliczone z reklamacją")
        s.set_status(ShipmentStatus.DELIVERED)
        self.bus.publish("shipment.delivered", {"id": s.id, "remarks": dinsp.ecmr_remark}, "ecmr")
        report.add("13 vision_inspection(delivery)", {"verdict": dinsp.verdict, "remark": dinsp.ecmr_remark,
                                                       "photos": len(photos or [])})
        chain_ok = self.ecmr.verify(doc.id)
        report.add("03 ecmr(final)", {"status": doc.status, "chain_valid": chain_ok})

        inv = self.billing.invoice(s, delivery_confirmed=chain_ok and doc.status == "delivered",
                                   waiting_h=ctx.get("wait_min", 0) / 60)
        self.invoices[inv.id] = inv
        self.store.put("invoice", inv.id, {**asdict(inv), "net": inv.net, "vat": inv.vat, "gross": inv.gross,
                                           "seller": s.carrier, "issued_for": s.id})
        self.bus.publish("invoice.issued", {"id": inv.id, "shipment_id": s.id, "gross": inv.gross}, "billing")
        report.add("17 billing", {"id": inv.id, "net": inv.net, "vat": inv.vat, "gross": inv.gross})

        em = self.emissions.calculate(s, v, s.distance_km or 0, empty_km=ctx.get("empty_km", 0))
        report.add("07 emissions", asdict(em))
        self.store.put("shipment", s.id, to_dict(s))   # zapis CO2e przed raportem ESG
        esg = self.esg.build("bieżący", list(self.shipments.values()))
        report.add("08 esg_reporting", {"total_co2e_t": esg.total_co2e_t, "avg_g_tkm": esg.avg_intensity_g_tkm,
                                         "reduction_potential_t": esg.reduction_potential_t})
        self._save(s, ctx, report)
        return report

    # ------------------------------------------------------------------ #
    # Wszystkie etapy naraz
    # ------------------------------------------------------------------ #
    def run(self, order_text: str, offers: list[CarrierOffer], *, loading_photos: list[Photo] | None = None,
            delivery_photos: list[Photo] | None = None, ledger: DriverLedger | None = None) -> RunReport:
        full = self.book(order_text, offers, ledger)
        sid = full.shipment["id"]
        # symulacja typowego błędu OCR kamery bramowej (0 odczytane jako O)
        rep = self.load(sid, loading_photos, ocr_plate=(full.shipment["vehicle"] or "").replace("0", "O"))
        full.steps += rep.steps
        full.shipment = rep.shipment
        if full.shipment["status"] != ShipmentStatus.IN_TRANSIT.value:
            return full
        s = self.get(sid)
        mid = Location("trasa", (s.origin.lat + s.destination.lat) / 2, (s.origin.lon + s.destination.lon) / 2)
        drive_h = self._ctx(sid)["drive_hours"]
        for rep in (self.ping(sid, s.origin, 0), self.ping(sid, mid, drive_h * 30), self.deliver(sid, delivery_photos)):
            full.steps += rep.steps
            full.shipment = rep.shipment
        return full

