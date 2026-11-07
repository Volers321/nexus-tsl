"""[15] Intake zleceń AI - copilot spedytora.

Zamienia nieustrukturyzowaną wiadomość (mail, czat, giełda) w obiekt `Shipment`.
Tryb offline: reguły regex dla PL/EN. Tryb LLM: model wyciąga pola do JSON,
a reguły służą jako walidacja i fallback.
"""
from __future__ import annotations

import re
import unicodedata

from ..core.geo import CITIES
from ..core.llm import LLMProvider, OfflineProvider, try_parse_json
from ..core.models import Location, Shipment, new_id

SYSTEM_PROMPT = (
    "Jesteś asystentem spedytora. Z treści zlecenia transportowego wyciągnij JSON z polami: "
    "shipper, consignee, origin_city, destination_city, weight_kg, pallets, pickup_date (YYYY-MM-DD), "
    "goods_description, cargo_value_eur, reference. Brakujące pola ustaw na null. Zwróć tylko JSON."
)


def _norm(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _find_city(fragment: str) -> Location | None:
    frag = _norm(fragment)
    for key, loc in CITIES.items():
        if key in frag or _norm(loc.name) in frag:
            return loc
    return None


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(",", "."))


def parse_rules(text: str) -> dict:
    t = _norm(text)
    out: dict = {}
    m = re.search(r"(?:z|from|zaladunek[:\s]*)\s+([a-z ]+?)\s+(?:do|to)\s+([a-z ]+?)\s*(?=[,.\n\d]|$)", t)
    if m:
        out["origin_city"], out["destination_city"] = m.group(1).strip(), m.group(2).strip()
    m = re.search(r"(\d+[\d ,.]*)\s*(t|ton|tony|kg)\b", t)
    if m:
        val = _num(m.group(1))
        out["weight_kg"] = val * 1000 if m.group(2).startswith("t") else val
    m = re.search(r"(\d+)\s*(?:palet|pallet|epal|eur)", t)
    if m:
        out["pallets"] = int(m.group(1))
    m = re.search(r"(\d{4}-\d{2}-\d{2})|(\d{1,2})[./](\d{1,2})[./](\d{4})", t)
    if m:
        out["pickup_date"] = m.group(1) or f"{m.group(4)}-{int(m.group(3)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"(?:wartosc|value)[^\d]*(\d+[\d ,.]*)", t)
    if m:
        out["cargo_value_eur"] = _num(m.group(1))
    m = re.search(r"(?:ref|nr zlecenia|order)[.:#\s]*([a-z0-9/-]{3,})", t)
    if m:
        out["reference"] = m.group(1).upper()
    m = re.search(r"(?:towar|goods)[:\s]+([^\n,.]+)", text, re.I)
    if m:
        out["goods_description"] = m.group(1).strip()
    m = re.search(r"(?:nadawca|shipper)[:\s]+([^\n,]+)", text, re.I)
    if m:
        out["shipper"] = m.group(1).strip()
    m = re.search(r"(?:odbiorca|consignee)[:\s]+([^\n,]+)", text, re.I)
    if m:
        out["consignee"] = m.group(1).strip()
    return out


class OrderIntake:
    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm or OfflineProvider()

    def extract(self, text: str) -> dict:
        fields = parse_rules(text)
        llm_fields = try_parse_json(self.llm.complete(SYSTEM_PROMPT, text)) or {}
        # LLM uzupełnia luki; reguły mają pierwszeństwo przy liczbach (deterministyczne).
        for k, v in llm_fields.items():
            if v is not None and k not in fields:
                fields[k] = v
        missing = [k for k in ("origin_city", "destination_city", "weight_kg") if k not in fields]
        fields["missing"] = missing
        fields["confidence"] = round(1 - len(missing) / 3, 2)
        return fields

    def to_shipment(self, text: str) -> Shipment:
        f = self.extract(text)
        origin = _find_city(f.get("origin_city", ""))
        dest = _find_city(f.get("destination_city", ""))
        if not origin or not dest or "weight_kg" not in f:
            raise ValueError(f"Niekompletne zlecenie, brakuje: {f['missing'] or ['nieznane miasto']}")
        return Shipment(
            id=new_id("SHP"),
            shipper=f.get("shipper", "nieznany nadawca"),
            consignee=f.get("consignee", "nieznany odbiorca"),
            origin=origin,
            destination=dest,
            weight_kg=float(f["weight_kg"]),
            pallets=int(f.get("pallets", 0)),
            goods_description=f.get("goods_description", "drobnica"),
            cargo_value_eur=float(f.get("cargo_value_eur", 0.0)),
            pickup_date=f.get("pickup_date"),
            reference=f.get("reference"),
        )
