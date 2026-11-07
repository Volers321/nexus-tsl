"""[17b] Eksport faktury do struktury KSeF FA(3).

Generuje XML zgodny ze schematem FA(3) (przestrzeń nazw
http://crd.gov.pl/wzor/2025/06/25/13775/), obowiązującym dla faktur
ustrukturyzowanych od 1 lutego 2026 r.

Mapowanie stawek dla usług transportowych:
- transport krajowy           -> 23%,    P_13_1 / P_14_1,  P_12 = "23"
- transport międzynarodowy    -> 0% KR,  P_13_6_1,          P_12 = "0 KR" (art. 83 ust. 1 pkt 23 ustawy o VAT)

Ograniczenia: moduł buduje plik, ale go nie wysyła (wysyłka wymaga
uwierzytelnienia w API KSeF 2.0 tokenem lub certyfikatem). Dane stron
(NIP, adres) pochodzą z rejestru `PARTIES` - w produkcji z bazy kontrahentów.
Kurs EUR/PLN do kwot VAT w walucie obcej podawaj z tabeli NBP z dnia
poprzedzającego dzień powstania obowiązku podatkowego.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from ..core.models import Shipment

NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"

# Przykładowi kontrahenci (fikcyjne numery). Klucz: nazwa jak na zleceniu.
PARTIES: dict[str, dict] = {
    "__seller__": {
        "nip": os.getenv("NEXUS_SELLER_NIP", "1111111111"),
        "name": os.getenv("NEXUS_SELLER_NAME", "NexusTSL Spedycja Sp. z o.o."),
        "country": "PL",
        "address": os.getenv("NEXUS_SELLER_ADDRESS", "ul. Przykładowa 1, 00-001 Warszawa"),
        "iban": os.getenv("NEXUS_SELLER_IBAN", ""),
    },
    "Elektro-Hurt Sp. z o.o.": {"nip": "2222222222", "country": "PL", "address": "ul. Testowa 5, 60-001 Poznań"},
}


def _party(name: str) -> dict:
    return {"name": name, "country": "PL", "address": "", **PARTIES.get(name, {})}


def _sub(parent: ET.Element, tag: str, text: object | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{NS}}}{tag}", attrs)
    if text is not None:
        el.text = str(text)
    return el


def _amt(v: float) -> str:
    return f"{v:.2f}"


def invoice_xml(inv: dict, s: Shipment, *, issue_date: str | None = None, currency: str = "EUR",
                eur_pln: float | None = None, number: str | None = None, payment_days: int = 30) -> str:
    """Buduje XML FA(3) z faktury (dict z BillingEngine/Store) i przesyłki."""
    ET.register_namespace("", NS)
    now = datetime.now(timezone.utc)
    issue_date = issue_date or now.date().isoformat()
    eur_pln = eur_pln or float(os.getenv("NEXUS_EUR_PLN", "4.25"))
    vat_rate = float(inv.get("vat_rate", 0.0))
    lines = inv.get("lines", [])
    net = round(sum(float(x["net_eur"]) for x in lines), 2)
    vat = round(net * vat_rate, 2)

    root = ET.Element(f"{{{NS}}}Faktura")

    nag = _sub(root, "Naglowek")
    _sub(nag, "KodFormularza", "FA", kodSystemowy="FA (3)", wersjaSchemy="1-0E")
    _sub(nag, "WariantFormularza", 3)
    _sub(nag, "DataWytworzeniaFa", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    _sub(nag, "SystemInfo", "NexusTSL")

    seller, buyer = _party("__seller__"), _party(inv.get("buyer", s.shipper))
    p1 = _sub(root, "Podmiot1")
    d1 = _sub(p1, "DaneIdentyfikacyjne")
    _sub(d1, "NIP", seller["nip"])
    _sub(d1, "Nazwa", seller["name"])
    a1 = _sub(p1, "Adres")
    _sub(a1, "KodKraju", seller["country"])
    _sub(a1, "AdresL1", seller["address"] or "-")

    p2 = _sub(root, "Podmiot2")
    d2 = _sub(p2, "DaneIdentyfikacyjne")
    if buyer.get("nip") and buyer["country"] == "PL":
        _sub(d2, "NIP", buyer["nip"])
    elif buyer.get("vat_ue"):
        _sub(d2, "KodUE", buyer["country"])
        _sub(d2, "NrVatUE", buyer["vat_ue"])
    else:
        _sub(d2, "BrakID", 1)
    _sub(d2, "Nazwa", buyer["name"])
    if buyer.get("address"):
        a2 = _sub(p2, "Adres")
        _sub(a2, "KodKraju", buyer["country"])
        _sub(a2, "AdresL1", buyer["address"])
    _sub(p2, "JST", 2)   # nabywca nie jest jednostką podrzędną JST
    _sub(p2, "GV", 2)    # nabywca nie jest członkiem grupy VAT

    fa = _sub(root, "Fa")
    _sub(fa, "KodWaluty", currency)
    _sub(fa, "P_1", issue_date)
    _sub(fa, "P_2", number or inv["id"])
    _sub(fa, "P_6", issue_date)   # data wykonania usługi = data dostawy
    if vat_rate > 0:
        _sub(fa, "P_13_1", _amt(net))
        _sub(fa, "P_14_1", _amt(vat))
        if currency != "PLN":
            _sub(fa, "P_14_1W", _amt(vat * eur_pln))
    else:
        _sub(fa, "P_13_6_1", _amt(net))
    _sub(fa, "P_15", _amt(net + vat))
    if currency != "PLN":
        _sub(fa, "KursWalutyZ", f"{eur_pln:.4f}")

    adn = _sub(fa, "Adnotacje")
    for tag in ("P_16", "P_17", "P_18", "P_18A"):   # 2 = nie dotyczy
        _sub(adn, tag, 2)
    _sub(_sub(adn, "Zwolnienie"), "P_19N", 1)
    _sub(_sub(adn, "NoweSrodkiTransportu"), "P_22N", 1)
    _sub(adn, "P_23", 2)
    _sub(_sub(adn, "PMarzy"), "P_PMarzyN", 1)
    _sub(fa, "RodzajFaktury", "VAT")
    if s.reference:
        dop = _sub(fa, "DodatkowyOpis")
        _sub(dop, "Klucz", "Nr zlecenia")
        _sub(dop, "Wartosc", s.reference)

    p12 = "23" if vat_rate > 0 else "0 KR"
    for i, line in enumerate(lines, 1):
        w = _sub(fa, "FaWiersz")
        _sub(w, "NrWierszaFa", i)
        _sub(w, "P_7", line["description"][:512])
        _sub(w, "P_8A", "usł.")
        _sub(w, "P_8B", 1)
        _sub(w, "P_9A", _amt(float(line["net_eur"])))
        _sub(w, "P_11", _amt(float(line["net_eur"])))
        _sub(w, "P_12", p12)
        _sub(w, "GTU", "GTU_13")   # usługi transportowe i gospodarki magazynowej

    if seller.get("iban"):
        pl = _sub(fa, "Platnosc")
        tp = _sub(pl, "TerminPlatnosci")
        _sub(tp, "Termin", (date.fromisoformat(issue_date) + timedelta(days=payment_days)).isoformat())
        rb = _sub(pl, "RachunekBankowy")
        _sub(rb, "NrRB", seller["iban"].replace(" ", ""))

    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
