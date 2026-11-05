"""[13] Inspekcja wizyjna AI - uszkodzenia ładunku i naczepy.

Interfejs `Detector` przyjmuje zdjęcie i zwraca wykryte anomalie. Dołączony
`MetadataDetector` działa offline na tagach (do testów i demo); w produkcji
podłącz model wizyjny (YOLO, multimodalny LLM) implementujący ten sam interfejs.
Wynik inspekcji trafia jako uwaga do podpisu e-CMR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

SEVERITY = {"scratch": 1, "dent": 2, "wet": 2, "torn_wrap": 2, "broken_seal": 3, "crushed_pallet": 3, "leak": 3}


@dataclass
class Photo:
    id: str
    tags: list[str] = field(default_factory=list)   # w produkcji: bytes / URL obrazu


@dataclass
class Finding:
    photo_id: str
    kind: str
    severity: int


class Detector(Protocol):
    def detect(self, photo: Photo) -> list[Finding]: ...


class MetadataDetector:
    def detect(self, photo: Photo) -> list[Finding]:
        return [Finding(photo.id, t, SEVERITY[t]) for t in photo.tags if t in SEVERITY]


@dataclass
class InspectionResult:
    findings: list[Finding]
    verdict: str            # "clean" | "remarks" | "reject"
    ecmr_remark: str


class VisionInspection:
    def __init__(self, detector: Detector | None = None) -> None:
        self.detector = detector or MetadataDetector()

    def inspect(self, photos: list[Photo]) -> InspectionResult:
        findings = [f for p in photos for f in self.detector.detect(p)]
        worst = max((f.severity for f in findings), default=0)
        verdict = "clean" if worst == 0 else ("reject" if worst >= 3 else "remarks")
        remark = "" if not findings else "Zastrzeżenia: " + ", ".join(sorted({f.kind for f in findings}))
        return InspectionResult(findings, verdict, remark)
