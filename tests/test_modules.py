import pytest

from nexus_tsl.core.events import EventBus
from nexus_tsl.core.geo import CITIES, road_km
from nexus_tsl.core.models import Shipment, Vehicle, VehicleType
from nexus_tsl.modules.billing import BillingEngine
from nexus_tsl.modules.cargo_insurance import CargoInsurance
from nexus_tsl.modules.depot_energy import ChargeRequest, DepotEnergyManager
from nexus_tsl.modules.dock_scheduler import Arrival, Dock, DockScheduler
from nexus_tsl.modules.driver_compliance import Activity, DriverCompliance, DriverLedger
from nexus_tsl.modules.ecmr import ECMRService
from nexus_tsl.modules.emissions import EmissionsCalculator
from nexus_tsl.modules.esg_reporting import ESGReporter
from nexus_tsl.modules.ev_fleet import EVFleetPlanner
from nexus_tsl.modules.ewaybill import EWaybillService
from nexus_tsl.modules.field_tasks import FieldTaskManager, Worker
from nexus_tsl.modules.freight_matching import CarrierOffer, FreightMatcher
from nexus_tsl.modules.fuel_optimizer import FuelOptimizer, FuelStation
from nexus_tsl.modules.gate_control import Booking, GateControl, normalize_plate
from nexus_tsl.modules.order_intake import OrderIntake
from nexus_tsl.modules.predictive_maintenance import PredictiveMaintenance
from nexus_tsl.modules.route_optimizer import RouteOptimizer
from nexus_tsl.modules.tracking import Ping, Tracker
from nexus_tsl.modules.vision_inspection import Photo, VisionInspection


def make_shipment(**kw) -> Shipment:
    base = dict(id="S1", shipper="A", consignee="B", origin=CITIES["poznan"], destination=CITIES["berlin"],
                weight_kg=12000, goods_description="elektronika", cargo_value_eur=180000, pallets=22)
    base.update(kw)
    return Shipment(**base)


def diesel(**kw) -> Vehicle:
    return Vehicle(kw.pop("plate", "PO1"), VehicleType.DIESEL_TRUCK, 24000, consumption_per_100km=30, **kw)


# [15]
def test_intake_parses_polish_order():
    f = OrderIntake().extract("Transport z Gdańsk do Kraków, 8,5 t, 10 palet, ref: ZL-77. Towar: meble")
    assert f["weight_kg"] == 8500 and f["pallets"] == 10 and f["reference"] == "ZL-77"
    s = OrderIntake().to_shipment("z Gdańsk do Kraków 8 t")
    assert s.origin.name == "Gdańsk" and s.destination.name == "Kraków"


def test_intake_rejects_incomplete():
    with pytest.raises(ValueError):
        OrderIntake().to_shipment("Prosimy o wycenę transportu")


# [12]
def test_matching_filters_capacity_and_prefers_cheap_close():
    s = make_shipment()
    offers = [
        CarrierOffer("Van", Vehicle("V", VehicleType.VAN, 1000), 300, CITIES["poznan"]),
        CarrierOffer("Far", diesel(plate="F"), 1000, CITIES["gdansk"]),
        CarrierOffer("Near", diesel(plate="N"), 1000, CITIES["poznan"]),
    ]
    ranked = FreightMatcher().rank(s, offers)
    assert [o.carrier for _, o in ranked] == ["Near", "Far"]


# [18]
def test_route_optimizer_visits_all_and_2opt_not_worse():
    stops = [CITIES[c] for c in ("krakow", "gdansk", "lodz", "wroclaw")]
    plan = RouteOptimizer().optimize(CITIES["warszawa"], stops)
    assert len(plan.stops) == 5 and set(plan.stops[1:]) == set(stops)
    naive = sum(road_km(a, b) for a, b in zip([CITIES["warszawa"], *stops], stops))
    assert plan.total_km <= naive


# [04]
def test_compliance_detects_violations():
    dc = DriverCompliance()
    bad = dc.check_day(DriverLedger("D", extensions_used=2), [Activity("drive", 5), Activity("break", 0.75), Activity("drive", 5)])
    assert not bad.ok and len(bad.violations) == 3
    good = dc.check_day(DriverLedger("D"), dc.plan_trip(8))
    assert good.ok


def test_plan_trip_inserts_daily_rest():
    plan = DriverCompliance().plan_trip(15)
    assert any(a.kind == "rest" for a in plan)
    assert sum(a.hours for a in plan if a.kind == "drive") == pytest.approx(15)


# [06]
def test_fuel_best_station_respects_range():
    v = diesel()
    near = FuelStation("near", CITIES["lodz"], 1.50)
    far_cheap = FuelStation("far", CITIES["gdansk"], 1.10)
    best = FuelOptimizer().best_station(v, CITIES["warszawa"], CITIES["wroclaw"], [near, far_cheap], fuel_left_l=60, refill_l=400)
    assert best.name == "near"


# [11]
def test_ev_planner():
    ev = Vehicle("E", VehicleType.ELECTRIC_TRUCK, 22000, battery_kwh=600, consumption_per_100km=110)
    assert EVFleetPlanner().plan(ev, 300).charging_stops == 0
    long = EVFleetPlanner().plan(ev, 900, mandatory_breaks=2)
    assert long.charging_stops >= 1 and long.feasible


# [19]
def test_maintenance_risk_ordering():
    pm = PredictiveMaintenance()
    fresh = pm.assess(diesel(odometer_km=10_000, last_service_km=5_000, age_years=1))
    worn = pm.assess(diesel(odometer_km=300_000, last_service_km=150_000, sensor_alerts=5, age_years=12))
    assert fresh.risk < 0.3
    assert worn.risk > 0.6


# [03]
def test_ecmr_signature_chain_and_tamper_detection():
    svc, s = ECMRService(), make_shipment()
    doc = svc.create(s)
    for role in ("sender", "carrier", "consignee"):
        svc.sign(doc.id, role, role.upper())
    assert doc.status == "delivered" and svc.verify(doc.id)
    doc.data["gross_weight_kg"] = 1
    assert not svc.verify(doc.id)


def test_ecmr_enforces_order():
    svc = ECMRService()
    doc = svc.create(make_shipment())
    with pytest.raises(ValueError):
        svc.sign(doc.id, "carrier", "X")


# [16]
def test_ewaybill_state_machine():
    svc, s = EWaybillService(), make_shipment(carrier="C")
    wb = svc.create(s)
    for st in ("accepted", "loaded", "in_transit", "delivered", "confirmed"):
        svc.advance(wb.id, st, "x")
    assert wb.state == "confirmed" and svc.visible_to(wb.id, "C")
    with pytest.raises(ValueError):
        svc.advance(wb.id, "loaded", "x")


# [09]
def test_insurance_shows_cmr_gap():
    q = CargoInsurance().quote(make_shipment())
    assert q.uncovered_gap_eur > 0 and q.premium_eur > 15


# [17]
def test_billing_international_zero_vat_and_waiting():
    s = make_shipment(price_eur=1000)
    inv = BillingEngine(waiting_eur_per_h=30, free_waiting_h=2).invoice(s, True, waiting_h=4)
    assert inv.vat == 0 and inv.net == 1060
    with pytest.raises(ValueError):
        BillingEngine().invoice(make_shipment(price_eur=1), delivery_confirmed=False)


# [01]
def test_dock_scheduler_reefer_and_waiting():
    sched = DockScheduler([Dock("A"), Dock("R", reefer=True)])
    slots = sched.schedule([Arrival(0, "X", 60), Arrival(0, "Y", 60, reefer=True), Arrival(10, "Z", 30)])
    by = {s.plate: s for s in slots}
    assert by["Y"].dock == "R"
    assert by["Z"].wait_min == 50


# [10]
def test_gate_ocr_tolerance_and_window():
    g = GateControl(tolerance_min=10)
    g.add_booking(Booking("PO 1B0S", "S1", 100, 130))
    assert normalize_plate("po18os") == normalize_plate("PO 1B0S")
    assert g.check("PO1BOS", 95).allowed
    assert not g.check("PO1BOS", 200).allowed
    assert not g.check("WX999", 100).allowed


# [13]
def test_vision_verdicts():
    vi = VisionInspection()
    assert vi.inspect([Photo("a")]).verdict == "clean"
    assert vi.inspect([Photo("a", ["scratch"])]).verdict == "remarks"
    assert vi.inspect([Photo("a", ["broken_seal"])]).verdict == "reject"


# [05]
def test_field_tasks_dispatch_and_payroll():
    m = FieldTaskManager([Worker("1", "Far", CITIES["gdansk"], {"x"}), Worker("2", "Near", CITIES["poznan"], {"x"})])
    t = m.create("Zadanie", CITIES["poznan"], "x")
    m.dispatch(t.id)
    assert t.assignee == "2"
    m.complete(t.id, "sig", 30)
    assert m.payroll() == {"Near": 12.5}


# [02]
def test_depot_energy_prefers_cheap_hours_and_grid_limit():
    tariff = [0.10] * 6 + [0.30] * 18
    mgr = DepotEnergyManager(grid_limit_kw=100, tariff_eur_kwh=tariff)
    plan = mgr.plan([ChargeRequest("E1", 300, ready_by_hour=6, max_kw=150)])
    assert max(plan.schedule["E1"]) <= 100 and not plan.unmet
    assert plan.cost_eur == pytest.approx(30.0)


# [14]
def test_tracking_publishes_delay_risk():
    bus = EventBus()
    t = Tracker(bus)
    s = make_shipment()
    t.ping(s, Ping(0, CITIES["poznan"]), deadline_min=60)
    assert any(e.topic == "shipment.delay_risk" for e in bus.log)


# [07] + [08]
def test_emissions_and_esg():
    s = make_shipment(distance_km=300)
    r = EmissionsCalculator().calculate(s, diesel(), 300)
    assert r.allocated_co2e_kg == pytest.approx(r.vehicle_co2e_kg * 0.5, rel=1e-3)
    ev = Vehicle("E", VehicleType.ELECTRIC_TRUCK, 24000, battery_kwh=600, consumption_per_100km=110)
    s2 = make_shipment(id="S2", distance_km=300)
    assert EmissionsCalculator().calculate(s2, ev, 300).allocated_co2e_kg < r.allocated_co2e_kg
    rep = ESGReporter().build("Q4", [s, s2])
    assert rep.shipments == 2 and rep.total_co2e_t > 0 and "A" in rep.by_customer_t
