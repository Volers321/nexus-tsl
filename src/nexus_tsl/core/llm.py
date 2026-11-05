"""Warstwa abstrakcji nad modelem językowym.

Domyślnie platforma działa w pełni offline (reguły + heurystyki). Jeśli ustawisz
zmienną NEXUS_LLM_PROVIDER=anthropic oraz ANTHROPIC_API_KEY, moduły korzystające
z LLM (intake zleceń, inspekcja wizyjna, asystent) użyją modelu jako wsparcia.
"""
from __future__ import annotations

import json
import os
from typing import Protocol


class LLMProvider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class OfflineProvider:
    """Brak modelu - moduły używają swoich heurystyk."""

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - trywialne
        return ""


class AnthropicProvider:
    def __init__(self, model: str | None = None) -> None:
        import anthropic  # opcjonalna zależność: pip install anthropic

        self._client = anthropic.Anthropic()
        self._model = model or os.getenv("NEXUS_LLM_MODEL", "claude-sonnet-5-5")

    def complete(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")


def get_provider() -> LLMProvider:
    if os.getenv("NEXUS_LLM_PROVIDER", "offline").lower() == "anthropic":
        return AnthropicProvider()
    return OfflineProvider()


def try_parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
