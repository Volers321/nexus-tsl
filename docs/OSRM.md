# Prawdziwe trasy drogowe (OSRM)

Domyślnie NexusTSL liczy dystans z linii prostej × 1,25. Po ustawieniu `NEXUS_OSRM_URL` platforma pyta serwer [OSRM](https://project-osrm.org/) o rzeczywistą trasę po drogach (dystans i czas przejazdu). Gdy serwer nie odpowiada, wraca do przybliżenia i oznacza to w odpowiedzi (`"routing": "osrm (fallback xN)"`), więc zlecenia nie stają.

## Szybki test (publiczny serwer demonstracyjny)

```bash
export NEXUS_OSRM_URL=https://router.project-osrm.org
uvicorn nexus_tsl.api:app
curl "localhost:8000/distance?origin=poznan&destination=berlin"
```

Publiczny serwer projektu OSRM służy tylko do testów: ma limity zapytań i nie gwarantuje dostępności. Do pracy produkcyjnej postaw własny.

## Własny serwer (Docker, mapa Polski)

Przygotowanie danych zajmuje ok. 10–20 minut i ~4 GB RAM. Wykonujesz je raz:

```bash
mkdir -p osrm-data && cd osrm-data
curl -LO https://download.geofabrik.de/europe/poland-latest.osm.pbf

docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/poland-latest.osm.pbf
docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-partition /data/poland-latest.osrm
docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-customize /data/poland-latest.osrm
cd ..
```

Potem uruchom API razem z OSRM:

```bash
NEXUS_OSRM_URL=http://osrm:5000 docker compose --profile osrm up
```

Profil `osrm` w `docker-compose.yml` startuje serwer na porcie 5000, a zmienna `NEXUS_OSRM_URL` kieruje do niego API.

Dla tras międzynarodowych pobierz większy wycinek (np. `europe/dach-latest.osm.pbf` razem z Polską scalone narzędziem `osmium merge`) albo całą Europę (wymaga ~60 GB RAM przy przygotowaniu).

## Uwagi

- Profil `car.lua` liczy czas dla samochodu osobowego. NexusTSL mnoży go przez 1,25, żeby przybliżyć ciężarówkę. Dokładniejszy wynik da własny profil ciężarówki (ograniczenia prędkości 80 km/h, zakazy wjazdu, nośność mostów).
- Wyniki są buforowane w pamięci procesu (do 4096 par punktów).
