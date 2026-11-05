"""[10] Inteligentna brama - kontrola wjazdu na teren obiektu.

Odczyt tablicy (z kamery ANPR) jest porównywany z awizacjami. Tolerancja
na typowe błędy OCR (0/O, 1/I, 8/B...) i okno czasowe awizacji.
"""
from __future__ import annotations

from dataclasses import dataclass

OCR_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "B": "8", "S": "5", "Z": "2", "G": "6"})


def normalize_plate(p: str) -> str:
    return "".join(ch for ch in p.upper() if ch.isalnum()).translate(OCR_CONFUSIONS)


@dataclass
class Booking:
    plate: str
    shipment_id: str
    window_start_min: float
    window_end_min: float


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    shipment_id: str | None = None


class GateControl:
    def __init__(self, tolerance_min: float = 30) -> None:
        self.bookings: list[Booking] = []
        self.tolerance = tolerance_min
        self.audit: list[tuple[float, str, GateDecision]] = []

    def add_booking(self, booking: Booking) -> None:
        self.bookings.append(booking)

    def check(self, ocr_plate: str, now_min: float) -> GateDecision:
        plate = normalize_plate(ocr_plate)
        matches = [b for b in self.bookings if normalize_plate(b.plate) == plate]
        if not matches:
            decision = GateDecision(False, "Brak awizacji - skieruj do biura przepustek")
        else:
            b = min(matches, key=lambda x: abs(x.window_start_min - now_min))
            if b.window_start_min - self.tolerance <= now_min <= b.window_end_min + self.tolerance:
                decision = GateDecision(True, "Awizacja potwierdzona", b.shipment_id)
            else:
                decision = GateDecision(False, "Poza oknem awizacji - parking buforowy", b.shipment_id)
        self.audit.append((now_min, ocr_plate, decision))
        return decision
