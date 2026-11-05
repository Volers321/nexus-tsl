"""[09] Ubezpieczenie ładunku per przesyłka (embedded insurance).

Wycena składki na podstawie wartości ładunku, rodzaju towaru, trasy
i jakości przewoźnika. Odpowiedzialność przewoźnika wg CMR jest ograniczona
do 8,33 SDR/kg - moduł pokazuje lukę, którą pokrywa polisa cargo.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import Shipment, new_id

SDR_PER_KG_CMR = 8.33
EUR_PER_SDR = 1.15  # kurs orientacyjny - w produkcji pobieraj aktualny z MFW/NBP

RISK_BY_GOODS = {
    "elektronika": 0.0045,
    "leki": 0.0040,
    "alkohol": 0.0035,
    "spozywcze": 0.0020,
    "chemia": 0.0030,
    "default": 0.0015,
}


@dataclass
class InsuranceQuote:
    id: str
    shipment_id: str
    insured_value_eur: float
    cmr_liability_eur: float
    uncovered_gap_eur: float
    premium_eur: float
    rate: float


class CargoInsurance:
    def quote(self, s: Shipment, carrier_rating: float = 4.0) -> InsuranceQuote:
        goods = s.goods_description.lower()
        rate = next((r for k, r in RISK_BY_GOODS.items() if k in goods), RISK_BY_GOODS["default"])
        if s.origin.country != s.destination.country:
            rate *= 1.2
        rate *= 1 + (4.0 - carrier_rating) * 0.1
        cmr_limit = s.weight_kg * SDR_PER_KG_CMR * EUR_PER_SDR
        premium = max(15.0, s.cargo_value_eur * rate)
        return InsuranceQuote(
            id=new_id("INS"),
            shipment_id=s.id,
            insured_value_eur=s.cargo_value_eur,
            cmr_liability_eur=round(cmr_limit, 2),
            uncovered_gap_eur=round(max(0.0, s.cargo_value_eur - cmr_limit), 2),
            premium_eur=round(premium, 2),
            rate=round(rate, 5),
        )
