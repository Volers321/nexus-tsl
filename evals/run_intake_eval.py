"""Ewaluacja modułu [15] intake: jak dobrze wyciągamy pola z maili ze zleceniami.

Uruchomienie:
    python evals/run_intake_eval.py                     # same reguły (offline)
    python evals/run_intake_eval.py --provider anthropic  # reguły + model Claude (ANTHROPIC_API_KEY)
    python evals/run_intake_eval.py --mode llm-first --provider anthropic  # model ważniejszy, reguły uzupełniają
    python evals/run_intake_eval.py --mode llm-only --provider anthropic   # sam model, bez reguł
    python evals/run_intake_eval.py --show-errors

Wynik: trafność per pole i dla całych zleceń (wszystkie pola poprawne).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nexus_tsl.core.llm import AnthropicProvider, OfflineProvider, try_parse_json  # noqa: E402
from nexus_tsl.modules.order_intake import SYSTEM_PROMPT, OrderIntake, find_city  # noqa: E402

FIELDS = ["origin", "destination", "weight_kg", "pallets", "pickup_date", "reference", "cargo_value_eur"]


def predict(intake: OrderIntake, text: str, mode: str) -> dict:
    if mode == "llm-only":
        raw = try_parse_json(intake.llm.complete(SYSTEM_PROMPT, text)) or {}
    else:
        raw = intake.extract(text)
    origin = find_city(str(raw.get("origin_city") or ""))
    dest = find_city(str(raw.get("destination_city") or ""))
    return {
        "origin": origin.name if origin else None,
        "destination": dest.name if dest else None,
        "weight_kg": raw.get("weight_kg"),
        "pallets": raw.get("pallets"),
        "pickup_date": raw.get("pickup_date"),
        "reference": (str(raw["reference"]).upper() if raw.get("reference") else None),
        "cargo_value_eur": raw.get("cargo_value_eur"),
    }


def same(field: str, got, exp) -> bool:
    if got is None:
        return False
    if field in ("weight_kg", "pallets", "cargo_value_eur"):
        try:
            return abs(float(got) - float(exp)) < 0.5
        except (TypeError, ValueError):
            return False
    return str(got).strip().upper() == str(exp).strip().upper()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "evals" / "orders.jsonl"))
    ap.add_argument("--provider", choices=["offline", "anthropic"], default="offline")
    ap.add_argument("--mode", choices=["hybrid", "llm-first", "llm-only"], default="hybrid")
    ap.add_argument("--show-errors", action="store_true")
    ap.add_argument("--json", help="zapisz szczegółowe wyniki do pliku")
    args = ap.parse_args()

    if args.mode != "hybrid" and args.provider == "offline":
        ap.error(f"--mode {args.mode} wymaga --provider anthropic")
    llm = AnthropicProvider() if args.provider == "anthropic" else OfflineProvider()
    intake = OrderIntake(llm, prefer_llm=args.mode == "llm-first")

    cases = [json.loads(line) for line in Path(args.data).read_text(encoding="utf-8").splitlines() if line.strip()]
    hits = {f: 0 for f in FIELDS}
    totals = {f: 0 for f in FIELDS}
    perfect, errors, rows = 0, [], []
    t0 = time.time()
    for case in cases:
        pred = predict(intake, case["text"], args.mode)
        ok_all = True
        for f, exp in case["expected"].items():
            totals[f] += 1
            if same(f, pred.get(f), exp):
                hits[f] += 1
            else:
                ok_all = False
                errors.append((case["id"], f, exp, pred.get(f)))
        perfect += ok_all
        rows.append({"id": case["id"], "pred": pred, "expected": case["expected"], "ok": ok_all})
    dt = time.time() - t0

    label = f"{args.provider}/{args.mode}"
    print(f"\n## Ewaluacja intake: {label} ({len(cases)} zleceń, {dt:.1f} s)\n")
    print("| Pole | Trafność |")
    print("|---|---|")
    for f in FIELDS:
        if totals[f]:
            print(f"| {f} | {hits[f]}/{totals[f]} ({hits[f] / totals[f]:.0%}) |")
    all_hits, all_tot = sum(hits.values()), sum(totals.values())
    print(f"| **wszystkie pola** | **{all_hits}/{all_tot} ({all_hits / all_tot:.0%})** |")
    print(f"| **zlecenia w 100% poprawne** | **{perfect}/{len(cases)} ({perfect / len(cases):.0%})** |")

    if args.show_errors and errors:
        print("\n### Błędy\n")
        for cid, f, exp, got in errors:
            print(f"- `{cid}` {f}: oczekiwano `{exp}`, jest `{got}`")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
