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
- Frische-Hinweis: Report-Stände älter als 14 Tage werden als „veraltet"
  markiert (pro Rahmenvertrag + global); es wird nichts ausgeblendet

**Verträge**
- Sortierbare Vertrags-Tabelle als Drill-down-Ziel
- Detail-Ansicht je Vertrag: alle Felder gruppiert, Notizfeld, Druck/PDF
- CSV-Export der aktuell gefilterten Sicht

**Auswertungen**
- VVL / Bindefrist mit Ampel-Buckets (abgelaufen, 0–3, 3–12, > 12 Monate)
- Bestand & Status, Tarif- und Options-Verteilung, MultiSIM
- Verlauf über mehrere Reports

**Kosten & Controlling**
- Import von Telekom-Rechnungen als CSV (Positions-Export, enthält den
  Datenverbrauch je Vertrag); Verknüpfung mit den Verträgen über die Rufnummer
- Monatskosten und Rabatt je Vertrag (in Tabelle, Facetten und Detail-Ansicht)
- Kosten je Kostenstelle und Kostentrend über mehrere Rechnungen
- Netto/Brutto umschaltbar

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

1. **Laden** – einen RVKU-KI-Report (`.xlsx`) oder eine Rechnung (`.csv`)
   hochladen; der Dateityp wird automatisch erkannt.
2. **Filtern** – links über die Facetten oder per Klick auf die Diagramme.
3. **Details** – eine Tabellenzeile öffnen: alle Felder, Kosten, Notiz, Druck/PDF.
4. **Kosten** – Button oben öffnet Kostenstellen-Auswertung und Kostentrend.
5. **Exportieren** – „CSV export" gibt die gefilterte Sicht (inkl. Kosten) aus.

## Konfiguration

Steuerung über Umgebungsvariablen (z. B. in `docker-compose.yml`):

| Variable | Default | Bedeutung |
|---|---|---|
| `BSP_PORT` | `8080` | veröffentlichter Host-Port (docker-compose); im Container lauscht uvicorn immer auf 8080 |
| `BSP_DATA_DIR` | `data` | Verzeichnis für Datenbank, Uploads und Exporte |
| `BSP_MAX_UPLOAD_MB` | `25` | maximale Upload-Größe in MB |
| `BSP_MAX_REPORT_AGE_DAYS` | `14` | ab welchem Alter ein Report-Stand als „veraltet" markiert wird |
| `BSP_SECRET_KEY` | wird in `data/secret.key` erzeugt | Schlüssel für signierte Session-Cookies |
| `BSP_HTTPS_ONLY` | `false` | Session-Cookie nur über HTTPS (hinter TLS-Proxy auf `true`) |
| `BSP_BASE_URL` | aus Request abgeleitet | Basis-URL für die SSO-Redirect-URI hinter einem Proxy |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | — | Azure/Entra-ID-SSO (alle drei = SSO aktiv) |

### Anmeldung

Standard: Passwort beim ersten Start setzen (Session-Cookie). Sind die drei
`GRAPH_*`-Variablen gesetzt, läuft die Anmeldung **ausschließlich über Microsoft
Entra ID (SSO)** — das Passwort-Login ist dann deaktiviert.

**Login-Ablauf (Device-Code):** Klick auf „Login mit Microsoft" → die App zeigt einen
Code an → auf `https://microsoft.com/devicelogin` eingeben und mit dem Firmenkonto
anmelden → fertig. **Kein Redirect-URI und kein HTTPS nötig** (der Server spricht
direkt mit Microsoft) — läuft also auch hinter `http://host:port`.

**Azure-Einrichtung:** vorhandene App-Registrierung nutzbar (Tenant-/Client-ID/Secret in
die `GRAPH_*`-Variablen). In der App-Registrierung unter **Authentication** →
**„Allow public client flows = Yes"** aktivieren (für den Device-Code-Flow). Der Zugriff
wird über die Enterprise-App gesteuert (*Assignment required = Yes* + Nutzer/Gruppen
zuweisen) — nur zugewiesene Nutzer des Tenants kommen rein. **Break-glass:** die
`GRAPH_*`-Variablen entfernen ⇒ Rückfall auf Passwort-Login.

*(Alternativ existiert auch der klassische Redirect-Flow unter
`/api/auth/azure/callback` — nur relevant, wenn HTTPS + Web-Redirect-URI vorhanden sind;
die UI nutzt standardmäßig den Device-Code-Flow.)*

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
