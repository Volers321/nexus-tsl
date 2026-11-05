"""[03] Elektroniczny list przewozowy e-CMR.

Zgodny z ideą Protokołu dodatkowego do Konwencji CMR (Genewa 2008).
Dokument z łańcuchem podpisów (nadawca -> przewoźnik -> odbiorca), gdzie każdy
podpis zawiera skrót poprzedniego stanu - każda późniejsza zmiana danych
jest wykrywalna. W produkcji: kwalifikowany podpis/pieczęć eIDAS i zgodność z eFTI.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from ..core.models import Shipment, new_id, utcnow

SIGN_ORDER = ["sender", "carrier", "consignee"]


@dataclass
class Signature:
    role: str
    signer: str
    at: str
    prev_hash: str
    hash: str
    remarks: str = ""


@dataclass
class ECMR:
    id: str
    shipment_id: str
    data: dict
    signatures: list[Signature] = field(default_factory=list)

    @property
    def status(self) -> str:
        return {0: "draft", 1: "issued", 2: "in_transit", 3: "delivered"}[len(self.signatures)]


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ECMRService:
    def __init__(self) -> None:
        self.docs: dict[str, ECMR] = {}

    def create(self, s: Shipment) -> ECMR:
        data = {
            "sender": s.shipper,
            "consignee": s.consignee,
            "place_of_taking_over": f"{s.origin.name}, {s.origin.country}",
            "place_of_delivery": f"{s.destination.name}, {s.destination.country}",
            "goods": s.goods_description,
            "packages": s.pallets,
            "gross_weight_kg": s.weight_kg,
            "carrier": s.carrier,
            "vehicle": s.vehicle_plate,
            "reference": s.reference,
        }
        doc = ECMR(id=new_id("ECMR"), shipment_id=s.id, data=data)
        self.docs[doc.id] = doc
        s.documents["ecmr"] = doc.id
        return doc

    def sign(self, doc_id: str, role: str, signer: str, remarks: str = "") -> ECMR:
        doc = self.docs[doc_id]
        expected = SIGN_ORDER[len(doc.signatures)] if len(doc.signatures) < 3 else None
        if role != expected:
            raise ValueError(f"Oczekiwany podpis: {expected}, otrzymano: {role}")
        prev = doc.signatures[-1].hash if doc.signatures else _digest(doc.data)
        at = utcnow().isoformat()
        h = _digest({"prev": prev, "role": role, "signer": signer, "at": at, "remarks": remarks})
        doc.signatures.append(Signature(role, signer, at, prev, h, remarks))
        return doc

    def verify(self, doc_id: str) -> bool:
        doc = self.docs[doc_id]
        prev = _digest(doc.data)
        for sig in doc.signatures:
            if sig.prev_hash != prev:
                return False
            expected = _digest({"prev": prev, "role": sig.role, "signer": sig.signer, "at": sig.at, "remarks": sig.remarks})
            if sig.hash != expected:
                return False
            prev = sig.hash
        return True

    def export(self, doc_id: str) -> dict:
        doc = self.docs[doc_id]
        return {**asdict(doc), "status": doc.status, "valid": self.verify(doc_id)}
