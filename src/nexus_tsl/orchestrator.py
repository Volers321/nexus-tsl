"""Orkiestrator - jeden przepływ zlecenia przez wszystkie 19 modułów.

  mail ─► [15] intake ─► [12] giełda ─► [19] serwis? ─► [18] trasa ─► [04] czas pracy
       ─► [06] paliwo / [11] EV + [02] energia bazy ─► [09] ubezpieczenie
       ─► [03] e-CMR + [16] e-waybill ─► [10] brama ─► [01] rampa ─► [05] zadania
       ─► [13] inspekcja ─► [14] śledzenie ─► dostawa ─► [17] faktura
       ─► [07] emisje ─► [08] raport ESG
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .core.events import EventBus
from .core.geo import road_km
from .core.llm import LLMProvider, OfflineProvider
from .core.models import Location, Shipment, ShipmentStatus, VehicleType
from .modules.billing import BillingEngine
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
from .modules.tracking import Ping, Tracker
from .modules.vision_inspection import Photo, VisionInspection


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


class NexusPlatform:
    def __init__(self, llm: LLMProvider | None = None, config: PlatformConfig | None = None,
                 workers: list[Worker] | None = None) -> None:
        self.cfg = config or PlatformConfig()
        self.bus = EventBus()
        self.intake = OrderIntake(llm or OfflineProvider())
        self.matcher = FreightMatcher()
        self.maintenance = PredictiveMaintenance()
        self.router = RouteOptimizer()
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
        self.vision = VisionInspection()
        self.tracker = Tracker(self.bus)
        self.billing = BillingEngine(fuel_surcharge_pct=0.05)
        self.emissions = EmissionsCalculator()
        self.esg = ESGReporter()
        self.shipments: dict[str, Shipment] = {}

    # ------------------------------------------------------------------ #
    def run(self, order_text: str, offers: list[CarrierOffer], *, loading_photos: list[Photo] | None = None,
            delivery_photos: list[Photo] | None = None, ledger: DriverLedger | None = None) -> RunReport:
        # [15] Intake
        s = self.intake.to_shipment(order_text)
        s.set_status(ShipmentStatus.BOOKED, "z wiadomości")
        self.shipments[s.id] = s
        report = RunReport(shipment={})
        report.add("15 order_intake", {"id": s.id, "lane": f"{s.origin.name}->{s.destination.name}", "kg": s.weight_kg})
        self.bus.publish("shipment.booked", {"id": s.id}, "order_intake")

        # [12] Giełda + [19] blokada pojazdów wymagających serwisu
        distance = road_km(s.origin, s.destination)
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
            raise RuntimeError("Brak przewoźnika spełniającego wymagania")
        v = chosen.vehicle
        s.carrier, s.vehicle_plate, s.price_eur = chosen.carrier, v.plate, chosen.price_eur
        s.set_status(ShipmentStatus.ASSIGNED, chosen.carrier)
        self.bus.publish("shipment.assigned", {"id": s.id, "carrier": s.carrier}, "freight_matching")

        # [18] Trasa (dojazd + kurs)
        plan = self.router.optimize(chosen.current_location, [s.origin, s.destination])
        s.distance_km = distance
        report.add("18 route_optimizer", {"total_km": plan.total_km, "drive_h": plan.drive_hours,
                                           "stops": [x.name for x in plan.stops]})

        # [04] Czas pracy kierowcy
        activities = self.compliance.plan_trip(plan.drive_hours)
        check = self.compliance.check_day(ledger or DriverLedger("D1"), activities[: self._first_day(activities)])
        breaks = sum(1 for a in activities if a.kind in ("break", "rest"))
        report.add("04 driver_compliance", {"ok": check.ok, "violations": check.violations,
                                            "plan": [(a.kind, a.hours) for a in activities]})

        # [06] Paliwo  lub  [11] EV + [02] energia bazy
        if v.type == VehicleType.ELECTRIC_TRUCK:
            ev = self.ev.plan(v, plan.total_km, mandatory_breaks=breaks)
            report.add("11 ev_fleet", asdict(ev))
            depot_need = min(ev.energy_kwh, (v.battery_kwh or 0) * 0.8)
            e = self.energy.plan([ChargeRequest(v.plate, depot_need, ready_by_hour=6)])
            report.add("02 depot_energy", {"cost_eur": e.cost_eur, "unmet": e.unmet})
        else:
            cost = self.fuel.trip_cost(v, plan.total_km, self.cfg.diesel_price_eur_l)
            report.add("06 fuel_optimizer", {"fuel_cost_eur": cost})

        # [09] Ubezpieczenie
        q = self.insurance.quote(s, chosen.rating)
        report.add("09 cargo_insurance", asdict(q))

        # [03] e-CMR + [16] e-waybill
        doc = self.ecmr.create(s)
        self.ecmr.sign(doc.id, "sender", s.shipper)
        wb = self.ewaybill.create(s)
        self.ewaybill.advance(wb.id, "accepted", s.carrier or "")
        report.add("03 ecmr", {"id": doc.id, "status": doc.status})
        report.add("16 ewaybill", {"id": wb.id, "state": wb.state})

        # [10] Brama + [01] rampa
        self.gate.add_booking(Booking(v.plate, s.id, 60, 120))
        gd = self.gate.check(v.plate.replace("0", "O"), now_min=75)   # symulacja błędu OCR
        s.set_status(ShipmentStatus.AT_GATE)
        report.add("10 gate_control", asdict(gd))
        slots = self.docks.schedule([Arrival(75, v.plate, 40), Arrival(70, "WX0001", 60), Arrival(72, "PO1234", 50)])
        mine = next(x for x in slots if x.plate == v.plate)
        report.add("01 dock_scheduler", {"dock": mine.dock, "wait_min": mine.wait_min, "kpi": self.docks.kpis(slots)})

        # [05] Zadanie dla pracownika + [13] inspekcja przy załadunku
        s.set_status(ShipmentStatus.LOADING, mine.dock)
        if self.tasks.workers:
            t = self.tasks.create(f"Zdjęcia ładunku i plomby {v.plate}", s.origin, "inspection")
            self.tasks.dispatch(t.id)
            self.tasks.complete(t.id, proof="photo-set-1", minutes=15)
            report.add("05 field_tasks", {"task": t.title, "assignee": t.assignee, "status": t.status})
        insp = self.vision.inspect(loading_photos or [])
        report.add("13 vision_inspection(load)", {"verdict": insp.verdict, "remark": insp.ecmr_remark})
        if insp.verdict == "reject":
            s.set_status(ShipmentStatus.EXCEPTION, "ładunek odrzucony przy załadunku")
            self.bus.publish("shipment.exception", {"id": s.id, "reason": insp.ecmr_remark}, "vision_inspection")
            report.shipment = self._summary(s)
            return report
        self.ecmr.sign(doc.id, "carrier", s.carrier or "", remarks=insp.ecmr_remark)
        self.ewaybill.advance(wb.id, "loaded", s.carrier or "")
        self.ewaybill.advance(wb.id, "in_transit", s.carrier or "")
        s.set_status(ShipmentStatus.IN_TRANSIT)
        self.bus.publish("shipment.in_transit", {"id": s.id, "ecmr": doc.id}, "ecmr")

        # [14] Śledzenie
        deadline = plan.drive_hours * 60 * 1.5
        mid = Location("trasa", (s.origin.lat + s.destination.lat) / 2, (s.origin.lon + s.destination.lon) / 2)
        self.tracker.ping(s, Ping(0, s.origin), deadline)
        st = self.tracker.ping(s, Ping(plan.drive_hours * 30, mid), deadline)
        report.add("14 tracking", {"progress": st.progress, "eta_min": st.eta_min})

        # Dostawa: [13] inspekcja + podpis odbiorcy
        dinsp = self.vision.inspect(delivery_photos or [])
        self.ecmr.sign(doc.id, "consignee", s.consignee, remarks=dinsp.ecmr_remark)
        self.ewaybill.advance(wb.id, "delivered", s.consignee)
        self.ewaybill.advance(wb.id, "disputed" if dinsp.findings else "confirmed", s.consignee, dinsp.ecmr_remark)
        if dinsp.findings:
            self.ewaybill.advance(wb.id, "confirmed", s.consignee, "rozliczone z reklamacją")
        s.set_status(ShipmentStatus.DELIVERED)
        self.bus.publish("shipment.delivered", {"id": s.id, "remarks": dinsp.ecmr_remark}, "ecmr")
        report.add("13 vision_inspection(delivery)", {"verdict": dinsp.verdict, "remark": dinsp.ecmr_remark})
        report.add("03 ecmr(final)", {"status": doc.status, "chain_valid": self.ecmr.verify(doc.id)})

        # [17] Faktura
        inv = self.billing.invoice(s, delivery_confirmed=self.ecmr.verify(doc.id) and doc.status == "delivered",
                                   waiting_h=mine.wait_min / 60)
        self.bus.publish("invoice.issued", {"id": inv.id, "gross": inv.gross}, "billing")
        report.add("17 billing", {"id": inv.id, "net": inv.net, "vat": inv.vat, "gross": inv.gross})

        # [07] Emisje + [08] ESG
        em = self.emissions.calculate(s, v, distance, empty_km=road_km(chosen.current_location, s.origin))
        report.add("07 emissions", asdict(em))
        esg = self.esg.build("bieżący", list(self.shipments.values()))
        report.add("08 esg_reporting", {"total_co2e_t": esg.total_co2e_t, "avg_g_tkm": esg.avg_intensity_g_tkm,
                                         "reduction_potential_t": esg.reduction_potential_t})
        report.shipment = self._summary(s)
        return report

    @staticmethod
    def _first_day(activities: list) -> int:
        for i, a in enumerate(activities):
            if a.kind == "rest":
                return i
        return len(activities)

    @staticmethod
    def _summary(s: Shipment) -> dict:
        return {"id": s.id, "status": s.status.value, "carrier": s.carrier, "vehicle": s.vehicle_plate,
                "price_eur": s.price_eur, "distance_km": s.distance_km, "co2e_kg": s.co2e_kg,
                "documents": s.documents, "history": s.history}
