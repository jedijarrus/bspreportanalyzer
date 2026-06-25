# Telekom BSP Report Analyzer

Web-Tool zum Auswerten von **Telekom-BSP-RVKU-KI-Reports** (Mobilfunk-Rahmenvertrag,
ein Datensatz pro SIM/Karte). Reports werden hochgeladen, in einer SQLite-DB als
Snapshots abgelegt und über die Zeit ausgewertet. Läuft als eigenständiger
Docker-Container. Zielnutzer: ein interner IT-Mitarbeiter, der die Verträge verwaltet.

## ⚠️ Sicherheitsregel (oberste Priorität)

**Echte Report-Daten dürfen NIEMALS auf GitHub gelangen.** Drei Schutzschichten:

1. **`.gitignore`** sperrt `data/`, `*.xlsx`, `*.db`, Exporte.
2. **pre-commit Hook** scannt gestagte Dateien auf PII (IBAN, Rufnummer, BIC) und
   verbotene Dateitypen → blockt den Commit.
3. **pre-push Hook** scannt vor jedem Push alle getrackten Dateien erneut.

Echte Daten leben ausschließlich im `data/`-Volume. Tests laufen gegen
**synthetische** Fixtures (faker), nie gegen Echtdaten.

> Nach dem Klonen **einmalig** die Hooks aktivieren:
> ```sh
> sh scripts/install-hooks.sh
> ```

## Zugang / Passwort

Beim **ersten Start** ist kein Passwort gesetzt — das Dashboard zeigt ein
Setup-Modal, in dem ein Passwort (mind. 8 Zeichen) festgelegt wird. Der Hash
liegt in der DB (`data/`, gitignored). Danach erscheint bei jedem Besuch ein
Login-Modal (kein Basic-Auth). Schutz ist **serverseitig** erzwungen: alle
`/api/*`-Datenendpunkte liefern ohne gültige Session 401.

Sessions laufen über ein signiertes HttpOnly-Cookie. Relevante ENV-Variablen:

| Variable | Default | Zweck |
|----------|---------|-------|
| `BSP_SECRET_KEY` | persistiert in `data/secret.key` | Signierschlüssel für Sessions |
| `BSP_MAX_UPLOAD_MB` | `25` | maximale Upload-Größe (OOM-/Zip-Bomb-Schutz) |

> Hinter einem HTTPS-Reverse-Proxy `https_only=True` in `app/api.py` setzen.

## Funktionen

| Tab | Inhalt |
|-----|--------|
| **Bestand** | Linien gesamt, gesperrt, Kartentyp-Verteilung, bald ablaufende |
| **VVL / Bindefrist** | Bindefrist-Buckets (abgelaufen / 0-3 / 3-12 / >12 Mon), Tabelle auslaufender Linien mit Ampel |
| **Tarife / Optionen** | Tarif-Verteilung; Daten-/Voice-/Roaming-Optionen (komma-separierte Mehrfachwerte korrekt zerlegt) |
| **Vergleich** | Zwei Reports gegenüberstellen: neue / entfernte / geänderte Linien (Schlüssel: Rufnummer) |
| **Trend** | Kennzahlen über alle Reports hinweg (Linien, gesperrt, ablaufend) |

## Schnellstart (Docker)

```sh
docker compose up --build
# -> http://localhost:8080
```

Die echten Reports landen beim Upload im gemounteten `./data`-Volume und bleiben dort.

## Lokale Entwicklung

```sh
pip install -r requirements-dev.txt
sh scripts/install-hooks.sh          # Git-Hooks aktivieren
uvicorn app.api:app --reload --port 8080
pytest -q                            # Tests
```

## Architektur

```
app/
  schema.py     kanonisches 101-Spalten-Schema (eine Quelle der Wahrheit)
  parser.py     xlsx -> normalisierte Zeilen (datetime, '\'-Platzhalter -> None)
  store.py      SQLite-Persistenz (reports + contracts, CASCADE-Delete)
  analytics.py  reine Auswertungsfunktionen (VVL, Verteilungen, Diff, Trend)
  api.py        FastAPI: Upload, Verwaltung, Auswertungs-Endpunkte
  config.py     Pfade/ENV
web/            Dashboard (HTML + Vanilla JS + Chart.js)
fixtures/       synthetischer Report-Generator (Tests/Entwicklung)
scripts/        sanitize_check.py, install-hooks.sh, explore.py (lokale Daten-Exploration)
tests/          pytest (parser, store, analytics, api)
```

## Daten-Exploration (lokal, optional)

`scripts/explore.py` lädt die echten xlsx in eine **separate** SQLite
(`data/explore.db`, gitignored) — unabhängig vom App-Code, für Ad-hoc-Analysen:

```sh
python scripts/explore.py import
python scripts/explore.py profile     # PII-sicheres Aggregat-Profil
```
