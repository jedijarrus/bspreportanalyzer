# BSP Report & Invoice Analyzer

Selbst-gehostetes Controlling-Dashboard für Telekom-Mobilfunk-Rahmenverträge.
Zwei Datenquellen — **Reports** (Stammdaten der Flotte) und **Rechnungen**
(Monatskosten + Datenverbrauch) — laufen zu einer durchsuchbaren Gesamtsicht
zusammen, verknüpft über die Rufnummer. Läuft als eigenständiger Docker-Container
mit Passwort- oder Microsoft-Entra-ID-Login.

## Zwei Datenquellen

Das Tool liest zwei sich ergänzende Telekom-Exporte ein; beim Upload wird der
Dateityp automatisch erkannt:

- **Report (`.xlsx`)** – RVKU-KI-Export aus dem Business Service Portal, ein
  Datensatz pro SIM/Anschluss: Tarif, Optionen, Status, Bindefrist/VVL,
  Kostenstelle, Nutzer. Liefert den **aktuellen Stand der Flotte**.
- **Rechnung (`.csv`)** – Positions-Export einer Monatsrechnung: Grundpreise,
  Optionen, Rabatte und **Datenverbrauch je Rufnummer**. Liefert die
  **tatsächlichen Kosten pro Monat**.

Report und Rechnung werden über die **Rufnummer** verknüpft – so steht neben
jedem Vertrag, was er im jeweiligen Monat gekostet und verbraucht hat.

## Sichten

Drei Bereiche (Reiter oben):

**Verträge** – die aktuelle Flotte aus den Reports
- Gesamtsicht über alle Rahmenverträge; pro Rahmenvertrag zählt jeweils der
  neueste Report, gekündigte Anschlüsse fallen automatisch heraus
- Faceted-Filter mit Live-Counts (Rahmenvertrag, Tarif, Kartentyp, Status,
  Bindefrist, MultiSIM, VVL), klickbare Charts, Volltextsuche, Filter-Chips
- VVL / Bindefrist mit Ampel-Buckets, Bestand & Verteilungen, Verlauf über
  mehrere Reports
- Frische-Hinweis: Report-Stände älter als 14 Tage werden als „veraltet"
  markiert (pro Rahmenvertrag + global); es wird nichts ausgeblendet
- Detail-Ansicht je Vertrag: alle Felder gruppiert, Notizfeld, Druck/PDF;
  CSV-Export der gefilterten Sicht

**Rechnungen** – die importierten Monatsrechnungen
- Mehrfach-Upload; identische Rechnungen werden erkannt und nicht doppelt gezählt
- Kostensplit je Position: Grundpreis, Optionen und Rabatte einzeln
  aufgeschlüsselt (z. B. sofort sichtbar, dass eine Daten-Flat 0 € kostet)
- Datenverbrauch je Rufnummer, Netto/Brutto umschaltbar

**Controlling** – Auswertung über mehrere Monate
- Monat wählen bzw. durchblättern (Selektor, Vor/Zurück, Klick im Diagramm)
- Top-Kostentreiber gesamt über alle Rechnungen, eindeutig je Rufnummer
  (Pools = mehrere Rufnummern) und mit Kostenstellennutzer
- Kosten je Kostenstelle, GB-Trend, Zuordnungs-Abgleich Report ↔ Rechnung
- Rufnummer-Monitoring: eine einzelne Rufnummer über die Monate – Kosten,
  Verbrauch, Tarif/Optionen, Auffälligkeiten. Aus Suche oder Controlling
  aufrufbar; der gewählte Monat wird in die Detailseite übernommen

## Schnellstart

```sh
git clone https://github.com/jedijarrus/bspreportanalyzer.git
cd bspreportanalyzer
docker compose up --build
```

Anschließend <http://localhost:8080> öffnen und ein Passwort festlegen.

## Nutzung

1. **Laden** – einen Report (`.xlsx`) oder eine Rechnung (`.csv`) hochladen
   (Mehrfachauswahl möglich); der Dateityp wird automatisch erkannt.
2. **Verträge** – die Flotte über Facetten, Charts oder Suche filtern; eine
   Zeile öffnen für alle Felder, Kosten, Notiz und Druck/PDF.
3. **Rechnungen** – die importierten Monatsrechnungen mit aufgeschlüsseltem
   Kostensplit prüfen.
4. **Controlling** – Monat wählen, Kostentreiber / Kostenstellen / Trend
   ansehen und einzelne Rufnummern über die Monate nachverfolgen.
5. **Verwalten** – „Einstellungen" listet Reports und Rechnungen zum Löschen.

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

**Login-Ablauf (MSAL / SPA):** Klick auf „Login mit Microsoft" → MSAL-Popup → Anmeldung
mit dem Firmenkonto → fertig. Das Frontend holt das Token (MSAL.js), der Server validiert
es per JWKS (Signatur/`iss`/`tid`/`aud`) und setzt die Session. **Braucht HTTPS** (der
Origin muss als SPA-Redirect registriert sein).

**Azure-Einrichtung:** vorhandene App-Registrierung nutzbar (Tenant-/Client-ID in die
`GRAPH_*`-Variablen). Unter **Authentication → „Single-page application (SPA)"** die
App-URL als Redirect-URI eintragen (z. B. `https://deine-app.example`) und
`BSP_BASE_URL`/`BSP_HTTPS_ONLY` setzen. Der Zugriff wird über die Enterprise-App gesteuert
(*Assignment required = Yes* + Nutzer/Gruppen zuweisen). **Break-glass:** die `GRAPH_*`-
Variablen entfernen ⇒ Rückfall auf Passwort-Login.

## Entwicklung

```sh
pip install -r requirements-dev.txt
sh scripts/install-hooks.sh        # Git-Hooks aktivieren
uvicorn app.api:app --reload --port 8080
pytest -q                          # Tests
```

Tests laufen gegen synthetische Fixtures (`fixtures/`), nicht gegen reale
Reports oder Rechnungen.

## Projektstruktur

```
app/
  schema.py          Kanonisches Spaltenschema (eine Quelle der Wahrheit)
  parser.py          Report-xlsx → normalisierte Datensätze
  invoice_parser.py  Rechnungs-csv → Positionen je Rufnummer
  store.py           SQLite-Persistenz (Reports, Rechnungen, Notizen)
  analytics.py       Auswertungen (Flotte, VVL, Kosten, Controlling, Monitoring)
  auth.py            Passwort-Hashing (PBKDF2) + Session
  azure_verify.py    Entra-ID-Token-Validierung (JWKS) fürs SSO
  api.py             FastAPI: Auth, Upload, Daten- und Auswertungs-Endpunkte
  config.py          Pfade & Konfiguration
  version.py         Build-Marker (SHA / Bauzeit)
web/                 Dashboard (HTML, Vanilla JS, Chart.js)
fixtures/            Synthetische Report- und Rechnungs-Generatoren
scripts/             Hilfsskripte (Sanitizer, Git-Hooks)
tests/               pytest (parser, store, analytics, api)
```

## Tech-Stack

Python 3.13 · FastAPI · SQLite · Vanilla JS + Chart.js · Docker

## Daten

Hochgeladene Reports und Rechnungen sowie die Datenbank liegen ausschließlich
im `data/`-Volume und sind nicht Teil des Repositorys.
