"""[05] Zadania pracowników mobilnych (kierowcy, magazynierzy, serwis).

Zadania (np. "podstaw naczepę na rampę 3", "zrób zdjęcia plomby") trafiają
do najbliższego dostępnego pracownika z wymaganymi uprawnieniami; zamknięcie
zadania wymaga potwierdzenia (podpis/zdjęcie) i nalicza czas do rozliczenia.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.geo import haversine_km
from ..core.models import Location, new_id


@dataclass
class Worker:
    id: str
    name: str
    location: Location
    skills: set[str] = field(default_factory=set)
    busy: bool = False
    rate_eur_h: float = 25.0


@dataclass
class Task:
    id: str
    title: str
    location: Location
    required_skill: str
    assignee: str | None = None
    status: str = "open"
    proof: str | None = None
    minutes: float = 0.0


class FieldTaskManager:
    def __init__(self, workers: list[Worker]) -> None:
        self.workers = {w.id: w for w in workers}
        self.tasks: dict[str, Task] = {}

    def create(self, title: str, location: Location, required_skill: str) -> Task:
        t = Task(new_id("TSK"), title, location, required_skill)
        self.tasks[t.id] = t
        return t

    def dispatch(self, task_id: str) -> Task:
        t = self.tasks[task_id]
        candidates = [w for w in self.workers.values() if not w.busy and t.required_skill in w.skills]
        if not candidates:
            raise LookupError(f"Brak dostępnego pracownika z uprawnieniem '{t.required_skill}'")
        w = min(candidates, key=lambda w: haversine_km(w.location, t.location))
        w.busy, t.assignee, t.status = True, w.id, "assigned"
        return t

    def complete(self, task_id: str, proof: str, minutes: float) -> Task:
        t = self.tasks[task_id]
        if not proof:
            raise ValueError("Zamknięcie zadania wymaga potwierdzenia (podpis lub zdjęcie)")
        t.status, t.proof, t.minutes = "done", proof, minutes
        if t.assignee:
            self.workers[t.assignee].busy = False
        return t

    def payroll(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for t in self.tasks.values():
            if t.status == "done" and t.assignee:
                w = self.workers[t.assignee]
                out[w.name] = round(out.get(w.name, 0) + t.minutes / 60 * w.rate_eur_h, 2)
        return out
