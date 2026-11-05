"""[17] Automatyczne rozliczenia i faktury z potwierdzenia dostawy.

Faktura powstaje automatycznie, gdy dostawa jest potwierdzona (podpis odbiorcy
w e-CMR lub stan `confirmed` w e-waybill). Obsługuje dopłaty (paliwowa,
postojowe) i stawki VAT. Eksport do struktury zbliżonej do KSeF (FA) do dopięcia.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import Shipment, ShipmentStatus, new_id

# Usługa transportu międzynarodowego - zwykle 0% (art. 83 ustawy o VAT); krajowy - 23%.
VAT_DOMESTIC = 0.23
VAT_INTERNATIONAL = 0.0


@dataclass
class InvoiceLine:
    description: str
    net_eur: float


@dataclass
class Invoice:
    id: str
    shipment_id: str
    buyer: str
    lines: list[InvoiceLine] = field(default_factory=list)
    vat_rate: float = VAT_DOMESTIC

    @property
    def net(self) -> float:
        return round(sum(line.net_eur for line in self.lines), 2)

    @property
    def vat(self) -> float:
        return round(self.net * self.vat_rate, 2)

    @property
    def gross(self) -> float:
        return round(self.net + self.vat, 2)


class BillingEngine:
    def __init__(self, fuel_surcharge_pct: float = 0.0, waiting_eur_per_h: float = 30.0, free_waiting_h: float = 2.0):
        self.fuel_surcharge_pct = fuel_surcharge_pct
        self.waiting_eur_per_h = waiting_eur_per_h
        self.free_waiting_h = free_waiting_h

    def invoice(self, s: Shipment, delivery_confirmed: bool, waiting_h: float = 0.0) -> Invoice:
        if not delivery_confirmed:
            raise ValueError("Brak potwierdzenia dostawy - faktura wstrzymana")
        if s.price_eur is None:
            raise ValueError("Brak ceny frachtu")
        intl = s.origin.country != s.destination.country
        inv = Invoice(id=new_id("INV"), shipment_id=s.id, buyer=s.shipper,
                      vat_rate=VAT_INTERNATIONAL if intl else VAT_DOMESTIC)
        inv.lines.append(InvoiceLine(f"Fracht {s.origin.name} -> {s.destination.name} ({s.reference or s.id})", s.price_eur))
        if self.fuel_surcharge_pct:
            inv.lines.append(InvoiceLine("Dopłata paliwowa", round(s.price_eur * self.fuel_surcharge_pct, 2)))
        extra_wait = max(0.0, waiting_h - self.free_waiting_h)
        if extra_wait:
            inv.lines.append(InvoiceLine(f"Postój {extra_wait:.1f} h", round(extra_wait * self.waiting_eur_per_h, 2)))
        s.documents["invoice"] = inv.id
        s.set_status(ShipmentStatus.INVOICED, inv.id)
        return inv
