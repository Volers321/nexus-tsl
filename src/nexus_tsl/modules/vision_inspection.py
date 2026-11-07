"""[13] Inspekcja wizyjna AI - uszkodzenia ładunku i naczepy.

Interfejs `Detector` przyjmuje zdjęcie i zwraca wykryte anomalie. Dołączony
`MetadataDetector` działa offline na tagach (do testów i demo); w produkcji
podłącz model wizyjny (YOLO, multimodalny LLM) implementujący ten sam interfejs.
Wynik inspekcji trafia jako uwaga do podpisu e-CMR.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

SEVERITY = {"scratch": 1, "dent": 2, "wet": 2, "torn_wrap": 2, "broken_seal": 3, "crushed_pallet": 3, "leak": 3}


@dataclass
class Photo:
    id: str
    tags: list[str] = field(default_factory=list)   # ręczne/testowe tagi uszkodzeń
    data: bytes | None = None                       # obraz (JPEG/PNG) dla detektorów wizyjnych
    media_type: str = "image/jpeg"


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


VISION_PROMPT = (
    "Jesteś inspektorem jakości w magazynie. Oceń zdjęcie ładunku lub naczepy. "
    "Zwróć WYŁĄCZNIE JSON: {\"findings\": [lista z: " + ", ".join(SEVERITY) + "]}. "
    "Pusta lista, jeśli nie widać uszkodzeń. Nie zgaduj - wpisuj tylko to, co wyraźnie widać."
)


class ClaudeVisionDetector:
    """Detektor uszkodzeń oparty na multimodalnym modelu Claude.

    Wymaga `pip install anthropic`, ANTHROPIC_API_KEY oraz NEXUS_VISION_PROVIDER=anthropic.
    Dla zdjęć bez obrazu (tylko tagi) korzysta z MetadataDetector.
    """

    def __init__(self, client: Any = None, model: str | None = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model or os.getenv("NEXUS_VISION_MODEL", os.getenv("NEXUS_LLM_MODEL", "claude-sonnet-5-5"))
        self.fallback = MetadataDetector()

    def detect(self, photo: Photo) -> list[Finding]:
        if not photo.data:
            return self.fallback.detect(photo)
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": photo.media_type,
                                             "data": base64.b64encode(photo.data).decode()}},
                {"type": "text", "text": VISION_PROMPT},
            ]}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip().strip("`")
        text = text[text.find("{"): text.rfind("}") + 1] if "{" in text else "{}"
        try:
            kinds = json.loads(text).get("findings", [])
        except (json.JSONDecodeError, AttributeError):
            kinds = []
        found = [Finding(photo.id, k, SEVERITY[k]) for k in kinds if k in SEVERITY]
        return found + self.fallback.detect(photo)   # ręczne tagi kierowcy też się liczą


def get_detector() -> Detector:
    if os.getenv("NEXUS_VISION_PROVIDER", "offline").lower() == "anthropic":
        return ClaudeVisionDetector()
    return MetadataDetector()


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
