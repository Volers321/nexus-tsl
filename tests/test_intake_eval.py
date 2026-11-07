import json
import subprocess
import sys
from pathlib import Path

from nexus_tsl.modules.order_intake import OrderIntake, parse_rules

ROOT = Path(__file__).resolve().parent.parent


class FakeLLM:
    def __init__(self, answer: dict):
        self.answer = answer

    def complete(self, system: str, prompt: str) -> str:
        return json.dumps(self.answer)


def test_dev_set_regression_guard():
    out = subprocess.run([sys.executable, "-I", str(ROOT / "evals" / "run_intake_eval.py")],
                         capture_output=True, text=True, check=True).stdout
    line = next(x for x in out.splitlines() if "wszystkie pola" in x)
    hits, total = map(int, line.split("**")[3].split()[0].split("/"))
    assert hits / total >= 0.95, out


def test_rules_never_crash_on_holdout():
    for line in (ROOT / "evals" / "orders_holdout.jsonl").read_text(encoding="utf-8").splitlines():
        parse_rules(json.loads(line)["text"])


def test_llm_first_overrides_rules_and_rules_fill_gaps():
    text = "Kierunek: Paryż. Start: Rzeszów. 14,5 t, 28 palet. 11.12.2026. Ref RZE-PAR-2"
    llm = FakeLLM({"origin_city": "Rzeszów", "destination_city": "Paryż", "weight_kg": None})
    rules_first = OrderIntake(llm, prefer_llm=False).extract(text)
    llm_first = OrderIntake(llm, prefer_llm=True).extract(text)
    assert rules_first["origin_city"] == "Paryż"            # znany błąd reguł
    assert llm_first["origin_city"] == "Rzeszów"            # model poprawia
    assert llm_first["weight_kg"] == 14500                  # reguły uzupełniają lukę modelu
    assert llm_first["source"] == "llm+rules"
