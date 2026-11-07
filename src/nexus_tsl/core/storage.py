"""Trwały magazyn danych (SQLite, bez dodatkowych zależności).

Prosty magazyn dokumentowy: każdy obiekt zapisywany jest jako JSON pod parą
(rodzaj, id). Dzięki temu moduły nie muszą znać schematu bazy, a migracja na
PostgreSQL (kolumna JSONB) sprowadza się do podmiany tej klasy.
Ścieżka bazy: zmienna NEXUS_DB_PATH (domyślnie w pamięci).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    kind TEXT NOT NULL,
    id   TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    topic   TEXT NOT NULL,
    source  TEXT NOT NULL,
    at      TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def put(self, kind: str, obj_id: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self._lock:
            self._db.execute(
                "INSERT INTO objects(kind, id, data) VALUES (?, ?, ?) "
                "ON CONFLICT(kind, id) DO UPDATE SET data=excluded.data, updated_at=datetime('now')",
                (kind, obj_id, payload),
            )
            self._db.commit()

    def get(self, kind: str, obj_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM objects WHERE kind=? AND id=?", (kind, obj_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM objects WHERE kind=? ORDER BY updated_at DESC, rowid DESC LIMIT ?", (kind, limit)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_event(self, topic: str, source: str, at: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events(topic, source, at, payload) VALUES (?, ?, ?, ?)",
                (topic, source, at, json.dumps(payload, ensure_ascii=False, default=str)),
            )
            self._db.commit()

    def events(self, limit: int = 50, shipment_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT topic, source, at, payload FROM events", []
        if shipment_id:
            sql += " WHERE payload LIKE ?"
            args.append(f'%"{shipment_id}"%')
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [{"topic": t, "source": s, "at": a, "payload": json.loads(p)} for t, s, a, p in reversed(rows)]
