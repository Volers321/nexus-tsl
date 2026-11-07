"""[16] E-waybill - cyfrowy obieg dokumentów przewozowych w transporcie krajowym.

Maszyna stanów z kontrolą przejść i dziennikiem zdarzeń widocznym dla
wszystkich stron. Uzupełnia moduł e-CMR (przewozy międzynarodowe).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import Shipment, new_id, utcnow

TRANSITIONS = {
    "created": {"accepted", "cancelled"},
    "accepted": {"loaded", "cancelled"},
    "loaded": {"in_transit"},
    "in_transit": {"delivered", "rejected"},
    "delivered": {"confirmed", "disputed"},
    "disputed": {"confirmed"},
    "confirmed": set(),
    "rejected": set(),
    "cancelled": set(),
}


@dataclass
class EWaybill:
    id: str
    shipment_id: str
    parties: dict[str, str]
    lines: list[dict]
    state: str = "created"
    log: list[dict] = field(default_factory=list)


class EWaybillService:
    def __init__(self) -> None:
        self.docs: dict[str, EWaybill] = {}

    def restore(self, d: dict) -> EWaybill:
        wb = EWaybill(**d)
        self.docs[wb.id] = wb
        return wb

    def create(self, s: Shipment) -> EWaybill:
        wb = EWaybill(
            id=new_id("EWB"),
            shipment_id=s.id,
            parties={"shipper": s.shipper, "carrier": s.carrier or "", "receiver": s.consignee},
            lines=[{"description": s.goods_description, "qty": s.pallets, "weight_kg": s.weight_kg}],
        )
        wb.log.append({"at": utcnow().isoformat(), "state": "created", "by": s.shipper})
        self.docs[wb.id] = wb
        s.documents["ewaybill"] = wb.id
        return wb

    def advance(self, wb_id: str, new_state: str, by: str, note: str = "") -> EWaybill:
        wb = self.docs[wb_id]
        if new_state not in TRANSITIONS[wb.state]:
            raise ValueError(f"Niedozwolone przejście {wb.state} -> {new_state}")
        wb.state = new_state
        wb.log.append({"at": utcnow().isoformat(), "state": new_state, "by": by, "note": note})
        return wb

    def visible_to(self, wb_id: str, party: str) -> bool:
        return party in self.docs[wb_id].parties.values()
