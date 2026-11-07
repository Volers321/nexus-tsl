# NexusTSL 🚛🤖

[![CI](https://github.com/Volers321/nexus-tsl/actions/workflows/ci.yml/badge.svg)](https://github.com/Volers321/nexus-tsl/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Zintegrowana platforma AI dla transportu, spedycji i logistyki.** Jeden przepływ danych od maila ze zleceniem do faktury i raportu ESG, realizowany przez 19 współpracujących modułów.

---

## O projekcie

NexusTSL to otwarty, modułowy prototyp systemu dla firm spedycyjnych, przewoźników i operatorów magazynów. Zamiast kilkunastu osobnych narzędzi, z których każde wymaga przepisywania tych samych danych, platforma prowadzi zlecenie przez cały cykl życia w jednym miejscu:

- **Przyjęcie zlecenia** – AI wyciąga z maila trasę, wagę, palety, wartość i referencję.
- **Planowanie** – wybór przewoźnika, kontrola stanu technicznego pojazdu, trasa, czas pracy kierowcy, paliwo lub ładowanie e-ciężarówki.
- **Dokumenty** – e-CMR z kryptograficznym łańcuchem podpisów i e-waybill z pełną historią stanów.
- **Obiekt** – brama z rozpoznawaniem tablic, przydział ramp, zadania dla pracowników, inspekcja zdjęć ładunku.
- **Realizacja i rozliczenie** – śledzenie z ETA, faktura wystawiana automatycznie po potwierdzonej dostawie.
- **Zrównoważony rozwój** – emisje CO₂e każdej przesyłki i raport Scope 3 dla klientów.

**Dla kogo:** dla zespołów IT w firmach TSL jako punkt wyjścia do własnego systemu, dla studentów i osób uczących się logistyki cyfrowej, dla każdego, kto chce zobaczyć, jak AI wpina się w realny proces przewozowy.

**Status:** prototyp (v0.1). Logika działa i jest pokryta testami. Dane są trzymane w pamięci, a część obliczeń to świadome uproszczenia (patrz [Ograniczenia](#ograniczenia-świadome-uproszczenia) i [roadmapa](docs/ARCHITECTURE.md#roadmapa)).

**Panel webowy:** po uruchomieniu API otwórz `http://localhost:8000/`, wklej zlecenie i zobacz jego przejście przez wszystkie moduły.

![Panel NexusTSL](docs/panel.png)

---

## Dlaczego jedna platforma?

Typowe narzędzia dla branży TSL rozwiązują pojedyncze wycinki procesu. W praktyce te same dane są w firmie przepisywane 5–10 razy: z maila do TMS, z TMS do listu przewozowego, z listu do faktury, z faktury do raportu ESG. NexusTSL ma **wspólny model domenowy** (`Shipment`, `Vehicle`, `Location`) i **szynę zdarzeń**, więc dane wpisane raz płyną przez wszystkie moduły.

```
 mail ─► [15] Intake AI ─► [12] Giełda ─► [19] Serwis? ─► [18] Trasa ─► [04] Czas pracy
      ─► [06] Paliwo │ [11] EV + [02] Energia bazy ─► [09] Ubezpieczenie
      ─► [03] e-CMR + [16] e-waybill ─► [10] Brama ─► [01] Rampa ─► [05] Zadania
      ─► [13] Inspekcja wizyjna ─► [14] Śledzenie/ETA ─► dostawa
      ─► [17] Faktura ─► [07] Emisje CO2e ─► [08] Raport ESG
```

## Moduły

| # | Moduł (`src/nexus_tsl/modules/`) | Co robi |
|---|---|---|
| 01 | `dock_scheduler.py` | Agent AI przydzielający rampy i kolejkę na placu, priorytety, rampy chłodnicze, KPI oczekiwania |
| 02 | `depot_energy.py` | Harmonogram ładowania e-ciężarówek w bazie: limit mocy, PV, taryfy |
| 03 | `ecmr.py` | e-CMR z łańcuchem podpisów nadawca→przewoźnik→odbiorca i wykrywaniem manipulacji |
| 04 | `driver_compliance.py` | Czas jazdy wg rozp. 561/2006: 4,5 h / 9 (10) h / 56 h / 90 h, planowanie przerw |
| 05 | `field_tasks.py` | Zadania dla pracowników mobilnych, dispatch wg kompetencji i odległości, potwierdzenia, rozliczenie |
| 06 | `fuel_optimizer.py` | Koszt paliwa trasy, wybór stacji z uwzględnieniem zasięgu i objazdu |
| 07 | `emissions.py` | Emisje CO2e WTW w duchu ISO 14083/GLEC, alokacja na przesyłkę |
| 08 | `esg_reporting.py` | Raport Scope 3 per klient i relacja, potencjał redukcji, eksport CSV |
| 09 | `cargo_insurance.py` | Polisa cargo per przesyłka, luka względem limitu CMR 8,33 SDR/kg |
| 10 | `gate_control.py` | Brama: ANPR z tolerancją błędów OCR, okna awizacji, audyt |
| 11 | `ev_fleet.py` | Wykonalność trasy e-ciężarówką, liczba ładowań, dopasowanie do przerw |
| 12 | `freight_matching.py` | Wielokryterialny ranking ofert przewoźników (cena, pusty przebieg, ocena, emisyjność) |
| 13 | `vision_inspection.py` | Inspekcja zdjęć ładunku/naczepy, werdykt i uwagi do e-CMR (wymienny detektor) |
| 14 | `tracking.py` | Pozycje GPS, postęp, ETA, zdarzenie ryzyka opóźnienia |
| 15 | `order_intake.py` | Zlecenie z maila → strukturalna przesyłka (reguły PL/EN + opcjonalnie LLM) |
| 16 | `ewaybill.py` | E-waybill: maszyna stanów, wgląd dla stron w czasie rzeczywistym |
| 17 | `billing.py` | Faktura po potwierdzonej dostawie, dopłaty, postojowe, VAT 23% / 0% |
| 18 | `route_optimizer.py` | Trasy wielopunktowe (najbliższy sąsiad + 2-opt), ETA |
| 19 | `predictive_maintenance.py` | Ryzyko awarii pojazdu, blokada kursu przy wysokim ryzyku |

## Szybki start

```bash
git clone https://github.com/<twoj-login>/nexus-tsl.git
cd nexus-tsl
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m nexus_tsl.demo        # pełny przepływ zlecenia w konsoli
pytest                          # 25 testów
uvicorn nexus_tsl.api:app --reload   # API → http://localhost:8000/docs
```

Albo w Dockerze:

```bash
docker compose up --build       # API na porcie 8000
```

### Przykład wywołania API

```bash
curl -X POST http://localhost:8000/orders/run \
  -H "Content-Type: application/json" \
  -d '{"text": "Transport z Poznań do Berlin, 12 t, 22 palet. Towar: elektronika, wartość 180000 EUR. Nadawca: Elektro-Hurt", "loading_photo_tags": [["scratch"]]}'
```

| Endpoint | Opis |
|---|---|
| `POST /orders/parse` | Tylko ekstrakcja pól ze zlecenia |
| `POST /orders/run` | Pełny przepływ przez wszystkie moduły |
| `GET /shipments` | Lista przesyłek |
| `GET /documents/ecmr/{id}` | e-CMR z weryfikacją łańcucha podpisów |
| `POST /compliance/check` | Kontrola dnia pracy kierowcy |
| `GET /distance?origin=&destination=` | Dystans drogowy (przybliżony) |
| `GET /esg` | Raport emisji |
| `GET /events` | Dziennik zdarzeń szyny |

## Tryb z modelem językowym (opcjonalnie)

Domyślnie wszystko działa **offline** (reguły i heurystyki), więc testy i demo nie wymagają klucza API. Moduł intake może korzystać z LLM:

```bash
pip install -e ".[llm]"
export NEXUS_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Interfejs `LLMProvider` w `core/llm.py` pozwala podpiąć dowolnego dostawcę.

## Struktura

```
src/nexus_tsl/
├── core/            # model domenowy, szyna zdarzeń, geografia, warstwa LLM
├── modules/         # 19 modułów funkcjonalnych
├── orchestrator.py  # przepływ end-to-end
├── api.py           # REST API (FastAPI)
└── demo.py          # dane i scenariusz demonstracyjny
tests/               # testy jednostkowe i end-to-end
docs/ARCHITECTURE.md # architektura i roadmapa
```

## Ograniczenia (świadome uproszczenia)

- Dystanse liczone z ortodromy × 1,25. W produkcji użyj OSRM/GraphHopper/HERE.
- Współczynniki emisji są **orientacyjne**. Do raportowania zastąp je wartościami z GLEC Framework / KOBiZE.
- Kontrola czasu pracy obejmuje główne limity 561/2006, bez pełnej analizy tachografu (odpoczynki skrócone, prom/pociąg, praca w załodze).
- e-CMR używa SHA-256 jako demonstracji integralności. Ważność prawna wymaga podpisu/pieczęci eIDAS i dostawcy zgodnego z eFTI.
- Dane w pamięci procesu. Następny krok: PostgreSQL + kolejka zdarzeń (patrz roadmapa).

## Licencja

MIT, patrz [LICENSE](LICENSE).
