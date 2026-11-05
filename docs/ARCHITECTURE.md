# Architektura NexusTSL

## Zasady

1. **Jeden model domenowy.** Każdy moduł przyjmuje i zwraca obiekty z `core/models.py`. Nie ma lokalnych kopii danych przesyłki.
2. **Moduły bez wzajemnych importów.** Moduły nie importują się nawzajem. Łączy je orkiestrator lub szyna zdarzeń, więc każdy można wymienić albo wydzielić do mikroserwisu.
3. **Offline-first, AI tam, gdzie daje przewagę.** Deterministyczne reguły to fundament i fallback. LLM i modele wizyjne wchodzą przez interfejsy (`LLMProvider`, `Detector`).
4. **Dokument jako stan.** e-CMR i e-waybill są źródłem prawdy o etapie przewozu. Faktura powstaje dopiero po kryptograficznie spójnym potwierdzeniu dostawy.

## Warstwy

```mermaid
flowchart TB
    subgraph Wejście
        A[Mail / czat / giełda] --> I15[15 Intake AI]
    end
    subgraph Planowanie
        I15 --> M12[12 Giełda / matching]
        M12 --> P19[19 Predykcja serwisu]
        P19 --> R18[18 Trasa / ETA]
        R18 --> D04[04 Czas pracy kierowcy]
        D04 --> F06[06 Paliwo]
        D04 --> E11[11 Flota EV]
        E11 --> E02[02 Energia bazy]
        R18 --> C09[09 Ubezpieczenie cargo]
    end
    subgraph Dokumenty
        C09 --> X03[03 e-CMR]
        C09 --> W16[16 e-waybill]
    end
    subgraph Obiekt
        X03 --> G10[10 Brama ANPR]
        G10 --> R01[01 Agent rampy]
        R01 --> T05[05 Zadania mobilne]
        T05 --> V13[13 Inspekcja wizyjna]
    end
    subgraph Realizacja
        V13 --> K14[14 Śledzenie]
        K14 --> B17[17 Fakturowanie]
    end
    subgraph Zrównoważony rozwój
        B17 --> CO7[07 Emisje CO2e]
        CO7 --> ESG8[08 Raport ESG]
    end
    BUS[(Szyna zdarzeń)] -.- I15 & M12 & X03 & K14 & B17
```

## Zdarzenia

| Temat | Emiter | Przykładowi konsumenci |
|---|---|---|
| `shipment.booked` | intake | giełda, CRM |
| `shipment.assigned` | matching | brama (awizacja), tracking |
| `shipment.in_transit` | e-CMR | tracking, klient (powiadomienie) |
| `shipment.delay_risk` | tracking | rampa docelowa (przesunięcie slotu), klient |
| `shipment.delivered` | e-CMR | billing, ESG |
| `shipment.exception` | inspekcja | reklamacje, ubezpieczenie |
| `invoice.issued` | billing | księgowość / KSeF |

## Roadmapa

- [ ] Trwałość: PostgreSQL + SQLAlchemy, migracje Alembic
- [ ] Szyna: NATS/Kafka zamiast in-memory, outbox pattern
- [ ] Routing: integracja OSRM (docker) i macierze odległości
- [ ] Optymalizacja: OR-Tools VRP z oknami czasowymi i ładownością
- [ ] e-CMR: podpis kwalifikowany eIDAS, format zgodny z eFTI
- [ ] KSeF: eksport faktury w schemacie FA(3)
- [ ] Inspekcja: detektor YOLO / multimodalny LLM za interfejsem `Detector`
- [ ] Tachograf: import plików DDD
- [ ] Panel webowy (React) i aplikacja kierowcy (PWA)
- [ ] Uwierzytelnianie (OAuth2/OIDC) i role: spedytor, przewoźnik, kierowca, magazyn, klient
