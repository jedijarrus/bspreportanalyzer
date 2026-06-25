# BSP Report Analyzer

Interaktives Dashboard zur Auswertung von Telekom-BSP-Reports (RVKU-KI,
Mobilfunk-Rahmenverträge). Reports hochladen, den Bestand filtern und Verträge
im Blick behalten – als eigenständiger Docker-Container.

## Überblick

Der Analyzer liest die Excel-Exporte des Telekom Business Service Portals
(ein Datensatz pro SIM/Anschluss) ein und stellt sie als durchsuchbare,
filterbare Gesamtsicht dar. Statt einzelne Exporte nebeneinanderzulegen, zeigt
das Dashboard immer den **aktuellen Stand über alle Rahmenverträge**: pro
Rahmenvertrag zählt jeweils der neueste Report, gekündigte Anschlüsse fallen
automatisch heraus.

## Features

**Flottensicht & Filter**
- Aktuelle Gesamtsicht über alle Rahmenverträge
- Faceted-Filter mit Live-Counts: Rahmenvertrag, Tarif, Kartentyp, Status,
  Bindefrist, MultiSIM, VVL-Berechtigung
- Klickbare Charts – ein Klick auf ein Balken-/Segment filtert die gesamte Sicht
- Volltextsuche (Rufnummer, Nutzer, Kostenstelle), entfernbare Filter-Chips
- Smart-Filter für typische Aufgaben, z. B. „VVL fällig ≤ 2 Monate"

**Verträge**
- Sortierbare Vertrags-Tabelle als Drill-down-Ziel
- Detail-Ansicht je Vertrag: alle Felder gruppiert, Notizfeld, Druck/PDF
- CSV-Export der aktuell gefilterten Sicht

**Auswertungen**
- VVL / Bindefrist mit Ampel-Buckets (abgelaufen, 0–3, 3–12, > 12 Monate)
- Bestand & Status, Tarif- und Options-Verteilung, MultiSIM
- Verlauf über mehrere Reports

**Betrieb**
- Ein Docker-Container, Daten in einem Volume
- Passwortschutz per Session-Cookie (Einrichtung beim ersten Start)

## Schnellstart

```sh
git clone https://github.com/jedijarrus/bspreportanalyzer.git
cd bspreportanalyzer
docker compose up --build
```

Anschließend <http://localhost:8080> öffnen und ein Passwort festlegen.

## Nutzung

1. **Report laden** – einen RVKU-KI-Export (`.xlsx`) hochladen. Mehrere
   Rahmenverträge bzw. Reports werden automatisch zusammengeführt.
2. **Filtern** – links über die Facetten oder per Klick auf die Diagramme.
3. **Details** – eine Tabellenzeile öffnen: alle Felder, Notiz, Druck/PDF.
4. **Exportieren** – „CSV export" gibt die gefilterte Sicht aus.

## Konfiguration

Steuerung über Umgebungsvariablen (z. B. in `docker-compose.yml`):

| Variable | Default | Bedeutung |
|---|---|---|
| `BSP_DATA_DIR` | `data` | Verzeichnis für Datenbank, Uploads und Exporte |
| `BSP_MAX_UPLOAD_MB` | `25` | maximale Upload-Größe in MB |
| `BSP_SECRET_KEY` | wird in `data/secret.key` erzeugt | Schlüssel für signierte Session-Cookies |

Hinter einem HTTPS-Reverse-Proxy in `app/api.py` `https_only=True` setzen.

## Entwicklung

```sh
pip install -r requirements-dev.txt
sh scripts/install-hooks.sh        # Git-Hooks aktivieren
uvicorn app.api:app --reload --port 8080
pytest -q                          # Tests
```

Tests laufen gegen synthetische Fixtures
(`fixtures/fake_report_generator.py`), nicht gegen reale Reports.

## Projektstruktur

```
app/
  schema.py     Kanonisches Spaltenschema (eine Quelle der Wahrheit)
  parser.py     xlsx → normalisierte Datensätze
  store.py      SQLite-Persistenz (Reports, Verträge, Notizen)
  analytics.py  Auswertungen (aktuelle Flotte, VVL, Verteilungen, Verlauf)
  api.py        FastAPI: Auth, Upload, Daten- und Auswertungs-Endpunkte
  config.py     Pfade & Konfiguration
web/            Dashboard (HTML, Vanilla JS, Chart.js)
fixtures/       Synthetischer Report-Generator
scripts/        Hilfsskripte
tests/          pytest (parser, store, analytics, api)
```

## Tech-Stack

Python 3.13 · FastAPI · SQLite · Vanilla JS + Chart.js · Docker

## Daten

Hochgeladene Reports und die Datenbank liegen ausschließlich im `data/`-Volume
und sind nicht Teil des Repositorys.
