"""[01] Agent AI rampy i placu manewrowego (inbound / dock / yard).

Przydziela przyjeżdżające pojazdy do ramp tak, by zminimalizować łączny czas
oczekiwania, z priorytetem dla ładunków pilnych i chłodniczych. Heurystyka
zachłanna "najwcześniej wolna rampa zgodna z typem".
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field


@dataclass(order=True)
class Arrival:
    eta_min: float
    plate: str = field(compare=False)
    handling_min: float = field(default=45, compare=False)
    reefer: bool = field(default=False, compare=False)
    priority: int = field(default=0, compare=False)   # wyższy = pilniejszy


@dataclass
class Dock:
    id: str
    reefer: bool = False


@dataclass
class Slot:
    plate: str
    dock: str
    start_min: float
    end_min: float
    wait_min: float


class DockScheduler:
    def __init__(self, docks: list[Dock]) -> None:
        self.docks = docks

    def schedule(self, arrivals: list[Arrival]) -> list[Slot]:
        free = [(0.0, d.id) for d in self.docks]
        heapq.heapify(free)
        reefer_docks = {d.id for d in self.docks if d.reefer}
        queue = sorted(arrivals, key=lambda a: (a.eta_min - a.priority * 30, a.eta_min))
        slots: list[Slot] = []
        for a in queue:
            candidates = [(t, d) for t, d in free if (d in reefer_docks) or not a.reefer]
            if not candidates:
                raise ValueError(f"Brak rampy chłodniczej dla {a.plate}")
            t, d = min(candidates, key=lambda x: (max(x[0], a.eta_min), x[1]))
            free.remove((t, d))
            heapq.heapify(free)
            start = max(t, a.eta_min)
            end = start + a.handling_min
            heapq.heappush(free, (end, d))
            slots.append(Slot(a.plate, d, start, end, start - a.eta_min))
        return sorted(slots, key=lambda s: s.start_min)

    @staticmethod
    def kpis(slots: list[Slot]) -> dict:
        if not slots:
            return {"trucks": 0, "avg_wait_min": 0, "max_wait_min": 0}
        waits = [s.wait_min for s in slots]
        return {"trucks": len(slots), "avg_wait_min": round(sum(waits) / len(waits), 1), "max_wait_min": max(waits)}
