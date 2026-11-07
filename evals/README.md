# Ewaluacja AI

## Intake zleceń (moduł 15)

Mierzymy, jak poprawnie system wyciąga z maila 7 pól: miejsce załadunku i rozładunku, wagę, liczbę palet, datę załadunku, numer referencyjny i wartość ładunku.

| Zestaw | Plik | Zleceń | Do czego służy |
|---|---|---|---|
| Rozwojowy | `orders.jsonl` | 24 | Na nim rozwijano reguły (PL/EN/DE, różne formaty) |
| Kontrolny | `orders_holdout.jsonl` | 12 | Nowe sformułowania, **nie używane** przy pisaniu reguł - uczciwa miara |

### Wyniki (7 listopada 2026)

| Strategia | Rozwojowy: pola | Rozwojowy: całe zlecenia | Kontrolny: pola | Kontrolny: całe zlecenia |
|---|---|---|---|---|
| Same reguły (offline) | 100% | 100% | **84%** | **42%** |
| Reguły + Claude (reguły ważniejsze) | *uruchom workflow* | | | |
| Claude + reguły (model ważniejszy) | *uruchom workflow* | | | |
| Sam Claude | *uruchom workflow* | | | |

Wynik reguł na zestawie rozwojowym jest zawyżony (reguły dopasowano do tych przykładów). Miarodajny jest zestaw kontrolny. Na nim reguły mylą się przy:
- datach zapisanych słownie („15 listopada 2026”) i wadze „20 tys. kg”,
- miastach spoza słownika (Opole),
- nietypowych etykietach („Kierunek: … Start: …”, „Nr: …”, „PO 4500123”),
- niejednoznacznych datach amerykańskich (`12/02/2026` = 2 grudnia).

To dokładnie te przypadki, w których model językowy powinien dawać przewagę. Dlatego platforma pozwala wybrać strategię (`NEXUS_INTAKE_PREFER_LLM=1`) po zmierzeniu wyników.

### Jak uruchomić

Lokalnie, bez klucza API:

```bash
python evals/run_intake_eval.py --show-errors
python evals/run_intake_eval.py --data evals/orders_holdout.jsonl --show-errors
```

Z modelem Claude:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-ant-...
python evals/run_intake_eval.py --data evals/orders_holdout.jsonl --provider anthropic --mode llm-first --show-errors
```

Albo na GitHubie, bez instalowania niczego:
1. **Settings → Secrets and variables → Actions → New repository secret**: `ANTHROPIC_API_KEY`.
2. **Actions → Ewaluacja AI (intake) → Run workflow**.
3. Tabela z porównaniem wszystkich strategii pojawi się w podsumowaniu przebiegu. Przepisz ją do tabeli powyżej.

### Zasady

- Nie poprawiaj reguł na podstawie błędów z zestawu kontrolnego. Gdy chcesz to zrobić, przenieś te przykłady do zestawu rozwojowego i dopisz nowy zestaw kontrolny.
- Test `tests/test_intake_eval.py` pilnuje, żeby trafność na zestawie rozwojowym nie spadła poniżej 95% i żeby reguły nie wywracały się na żadnym mailu.

## Inspekcja zdjęć (moduł 13)

`ClaudeVisionDetector` (włączany `NEXUS_VISION_PROVIDER=anthropic`) wysyła zdjęcie do modelu i mapuje odpowiedź na typy uszkodzeń. Do rzetelnej oceny potrzebny jest zestaw zdjęć z oznaczeniami (np. 50 zdjęć palet: czyste / rysa / zgnieciona / zerwana plomba). Struktura jest gotowa, ale zdjęć nie dołączono do repozytorium. Kolejny krok to zebranie ich z aplikacji kierowcy.
