"""Prosta, synchroniczna szyna zdarzeń łącząca moduły.

W produkcji można ją zastąpić Kafka/RabbitMQ/NATS bez zmiany modułów -
wystarczy zachować interfejs `publish` / `subscribe`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import utcnow

Handler = Callable[["Event"], None]


@dataclass
class Event:
    topic: str
    payload: dict[str, Any]
    source: str
    at: str = field(default_factory=lambda: utcnow().isoformat())


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self.log: list[Event] = []

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Subskrypcja tematu; '*' oznacza wszystkie zdarzenia."""
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: dict[str, Any], source: str) -> Event:
        event = Event(topic=topic, payload=payload, source=source)
        self.log.append(event)
        for handler in [*self._subs.get(topic, []), *self._subs.get("*", [])]:
            handler(event)
        return event
