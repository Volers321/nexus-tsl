"""[14] Śledzenie przesyłek i przewidywanie opóźnień (visibility).

Przyjmuje pozycje GPS, wylicza postęp i ETA, a gdy prognoza przekracza okno
dostawy - publikuje zdarzenie `shipment.delay_risk` na szynę.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.events import EventBus
from ..core.geo import road_km
from ..core.models import Location, Shipment


@dataclass
class Ping:
    minute: float
    location: Location


@dataclass
class TrackState:
    shipment_id: str
    pings: list[Ping] = field(default_factory=list)
    eta_min: float | None = None
    progress: float = 0.0


class Tracker:
    def __init__(self, bus: EventBus, default_speed_kmh: float = 70.0) -> None:
        self.bus = bus
        self.speed = default_speed_kmh
        self.states: dict[str, TrackState] = {}

    def ping(self, s: Shipment, p: Ping, deadline_min: float | None = None) -> TrackState:
        st = self.states.setdefault(s.id, TrackState(s.id))
        st.pings.append(p)
        total = road_km(s.origin, s.destination) or 1.0
        left = road_km(p.location, s.destination)
        st.progress = round(max(0.0, min(1.0, 1 - left / total)), 3)
        speed = self.speed
        if len(st.pings) >= 2:
            a, b = st.pings[-2], st.pings[-1]
            dt_h = (b.minute - a.minute) / 60
            if dt_h > 0:
                observed = road_km(a.location, b.location) / dt_h
                speed = 0.5 * self.speed + 0.5 * observed if observed > 5 else self.speed * 0.5
        st.eta_min = round(p.minute + left / max(speed, 1) * 60, 1)
        if deadline_min is not None and st.eta_min > deadline_min:
            self.bus.publish(
                "shipment.delay_risk",
                {"shipment_id": s.id, "eta_min": st.eta_min, "deadline_min": deadline_min},
                source="tracking",
            )
        return st
