"""[15] Intake zleceń AI - copilot spedytora.

Zamienia nieustrukturyzowaną wiadomość (mail, czat, giełda) w obiekt `Shipment`.
Tryb offline: reguły regex dla PL/EN. Tryb LLM: model wyciąga pola do JSON,
a reguły służą jako walidacja i fallback.
"""
from __future__ import annotations

import os
import re
import unicodedata

from ..core.geo import CITIES, CITY_ALIASES
from ..core.llm import LLMProvider, OfflineProvider, try_parse_json
from ..core.models import Location, Shipment, new_id

SYSTEM_PROMPT = (
    "Jesteś asystentem spedytora. Z treści zlecenia transportowego (PL/EN/DE) wyciągnij JSON z polami: "
    "shipper, consignee, origin_city (miejsce ZAŁADUNKU), destination_city (miejsce ROZŁADUNKU, przy kilku "
    "punktach - ostatni), weight_kg (liczba w kg), pallets (liczba), pickup_date (YYYY-MM-DD, data załadunku; "
    "zapis 12/02/2026 interpretuj z kontekstu), goods_description, cargo_value_eur (tylko jeśli w EUR), "
    "reference (numer zlecenia/referencji klienta dokładnie jak w tekście). "
    "Nazwy miast podawaj po polsku (np. Monachium, Wiedeń, Wrocław). Brakujące pola ustaw na null. "
    "Zwróć wyłącznie JSON."
)


def _norm(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _city_names() -> list[tuple[str, str]]:
    """(wariant nazwy znormalizowany, klucz CITIES), najdłuższe najpierw."""
    names = [(_norm(k), k) for k in CITIES] + [(_norm(loc.name), k) for k, loc in CITIES.items()]
    names += [(_norm(a), k) for a, k in CITY_ALIASES.items()]
    return sorted(set(names), key=lambda x: -len(x[0]))


def cities_in(text: str) -> list[tuple[int, str]]:
    """Miasta znalezione w tekście jako (pozycja, klucz), w kolejności występowania."""
    t = _norm(text)
    found: dict[int, str] = {}
    for name, key in _city_names():
        for m in re.finditer(rf"(?<![a-z]){re.escape(name)}(?![a-z])", t):
            if not any(p <= m.start() < p + 30 and found[p] == key for p in found):
                found.setdefault(m.start(), key)
    return sorted(found.items())


def find_city(fragment: str) -> Location | None:
    hits = cities_in(fragment)
    return CITIES[hits[0][1]] if hits else None


_find_city = find_city  # zgodność wsteczna


ORIGIN_LABEL = re.compile(
    r"(?:\bmiejsce zaladunku|\bzaladunek(?: w)?|\bzaladunku|\bodbior z|\bz|\bze|\bod|\bfrom|\bvon|"
    r"\bpickup|\bpick-up|\bloading|\bbeladung|\bladeort)\W*$"
)
DEST_LABEL = re.compile(
    r"(?:\bmiejsce rozladunku|\brozladunek(?: koncowy)?(?: w)?|\brozladunku|\bdo|\bto|\bnach|"
    r"\bdelivery|\bunloading|\bentladung|\bentladeort)\W*$"
)
REF_LABEL = re.compile(
    r"\b(?:nr zlecenia|zlecenie nr|zlecenie|nr ref|nasz numer|nasz nr|our ref|numer zamowienia|"
    r"auftragsnummer|referenz|reference|po number|order|ref)\b[\s.:#]*(?:nr|no|number|numer)?[\s.:#]*"
)
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
PICKUP_HINT = re.compile(r"(zaladun|odbior|podstawien|termin|pickup|loading|lade|data|date)\w*\W*$")
AMOUNT = r"(\d{1,3}(?:[ .,]\d{3})+(?![\d.,]\d)|\d+(?:[.,]\d+)?)"


def _num(s: str) -> float:
    """Liczba w formacie PL/EN/DE: '8 500', '12,000', '16.000' (tysiące) lub '15,5', '13.5' (ułamki)."""
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", s):
        return float(re.sub(r"[ .,]", "", s))
    return float(s.replace(" ", "").replace(",", "."))


def _mask(t: str, start: int, end: int) -> str:
    return t[:start] + " " * (end - start) + t[end:]


def _dates(t: str) -> list[tuple[int, int, str]]:
    out = []
    for m in DATE_RE.finditer(t):
        if m.group(1):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            a, b, y = int(m.group(4)), int(m.group(5)), int(m.group(6))
            # domyślnie europejski DD.MM; zapis amerykański rozpoznajemy, gdy "dzień" > 12
            d, mo = (b, a) if (m.group(0).count("/") == 2 and b > 12 >= a) else (a, b)
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.append((m.start(), m.end(), f"{y:04d}-{mo:02d}-{d:02d}"))
    return out


def parse_rules(text: str) -> dict:
    t = _norm(text)
    same_len = len(t) == len(text)
    out: dict = {}

    # 1) Numer referencyjny (z oryginału - zachowuje polskie litery), potem maskujemy.
    for m in REF_LABEL.finditer(t):
        tok = re.match(r"[^\s,;()]+", t[m.end():])
        if not tok:
            continue
        a, b = m.end(), m.end() + len(tok.group(0).rstrip(".:"))
        value = (text[a:b] if same_len else t[a:b]).upper()
        if re.search(r"\d", value):
            out["reference"] = value
            t = _mask(t, m.start(), b)
            break

    # 2) Daty - preferujemy tę opisaną jako załadunek/odbiór.
    dates = _dates(t)
    if dates:
        hinted = [d for d in dates if PICKUP_HINT.search(t[max(0, d[0] - 30):d[0]])]
        out["pickup_date"] = (hinted or dates)[0][2]
        for a, b, _ in dates:
            t = _mask(t, a, b)

    # 3) Wartość ładunku.
    m = re.search(r"(?:wartosc(?: towaru)?|cargo value|value|warenwert)\D{0,15}?" + AMOUNT + r"\s*(eur|€|pln|zl)?", t)
    if m and (m.group(2) or "eur") in ("eur", "€"):
        out["cargo_value_eur"] = _num(m.group(1))
    if m:
        t = _mask(t, m.start(), m.end())

    # 4) Waga.
    m = re.search(AMOUNT + r"\s*(kg|t|ton|tony|tons|tonnes|tonn?)\b", t)
    if m:
        val = _num(m.group(1))
        out["weight_kg"] = round(val * 1000 if m.group(2) != "kg" else val, 1)
        t = _mask(t, m.start(), m.end())

    # 5) Palety.
    m = (re.search(r"(\d{1,3})\s*(?:palet\w*|pallets?|paletten|europalet\w*|epal\w*|ep)\b", t)
         or re.search(r"(?:palet\w*|pallets?|paletten)\s*[:=]\s*(\d{1,3})\b", t))
    if m and int(m.group(1)) <= 66:
        out["pallets"] = int(m.group(1))

    # 6) Miasta: etykiety (załadunek/rozładunek, z/do, from/to...), w braku - kolejność w tekście.
    hits = cities_in(text)
    origin = dest = None
    for pos, key in hits:
        ctx = _norm(text)[max(0, pos - 30):pos]
        if DEST_LABEL.search(ctx):
            dest = key
        elif ORIGIN_LABEL.search(ctx) and origin is None:
            origin = key
    if hits:
        origin = origin or next((k for _, k in hits if k != dest), None)
        dest = dest or next((k for _, k in reversed(hits) if k != origin), None)
    if origin:
        out["origin_city"] = CITIES[origin].name
    if dest:
        out["destination_city"] = CITIES[dest].name

    # 7) Pola opisowe (z oryginału).
    m = re.search(r"(?:towar|goods|ware)[:\s]+([^\n,.]+)", text, re.I)
    if m:
        out["goods_description"] = m.group(1).strip()
    m = re.search(r"(?:nadawca|shipper|absender)[:\s]+([^\n,]+)", text, re.I)
    if m:
        out["shipper"] = m.group(1).strip()
    m = re.search(r"(?:odbiorca|consignee|empf[aä]nger)[:\s]+([^\n,]+)", text, re.I)
    if m:
        out["consignee"] = m.group(1).strip()
    return out


class OrderIntake:
    """Ekstrakcja zlecenia.

    prefer_llm=False (domyślnie): reguły są źródłem prawdy, model uzupełnia brakujące pola.
    prefer_llm=True: model jest źródłem prawdy, reguły uzupełniają luki (np. gdy model zawiedzie).
    Wybór na podstawie ewaluacji: evals/run_intake_eval.py. Zmienna: NEXUS_INTAKE_PREFER_LLM=1.
    """

    def __init__(self, llm: LLMProvider | None = None, prefer_llm: bool | None = None) -> None:
        self.llm = llm or OfflineProvider()
        if prefer_llm is None:
            prefer_llm = os.getenv("NEXUS_INTAKE_PREFER_LLM", "0") == "1"
        self.prefer_llm = prefer_llm

    def extract(self, text: str) -> dict:
        rules = parse_rules(text)
        llm_fields = {k: v for k, v in (try_parse_json(self.llm.complete(SYSTEM_PROMPT, text)) or {}).items()
                      if v not in (None, "")}
        primary, secondary = (llm_fields, rules) if self.prefer_llm else (rules, llm_fields)
        fields = {**secondary, **primary}
        fields["source"] = "llm+rules" if llm_fields else "rules"
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
